"""
mib_store.py — In-process OID cache backed by Redis.

Loads the full OID→raw_json map at startup and refreshes it whenever the
backend publishes a message to the device's update channel.

Key design decisions
--------------------
* OIDs are stored sorted in **numeric** order (each segment as an integer).
  This is mandatory for correct GETNEXT/GETBULK — lexicographic sort breaks
  at any instance index ≥ 10 (e.g. ".10" < ".2" lexicographically).
* The sorted (tuple, oid_str) pairs list is built once on load/reload and
  exposed directly so the agent never rebuilds it per-request.
* Non-numeric OID keys (symbolic names stored by mistake) are silently
  discarded at load time so they never reach the bisect logic.
"""

import logging
import threading

import redis as redis_lib

log = logging.getLogger(__name__)


def _is_numeric_oid(oid: str) -> bool:
    """Return True only if every segment of *oid* is a non-negative integer."""
    if not oid:
        return False
    try:
        for seg in oid.strip(".").split("."):
            if not seg.isdigit():
                return False
        return True
    except Exception:
        return False


def _oid_tuple(oid: str) -> tuple:
    """Convert '1.3.6.1.2.1.1.1.0' → (1, 3, 6, 1, 2, 1, 1, 1, 0)."""
    return tuple(int(x) for x in oid.strip(".").split("."))


class MibStore:
    """
    Thread-safe, numerically-sorted OID cache for one device.

    Redis layout
    ------------
    HSET device:{device_id}:oids  {oid_dotted_string}  {value_json}
    PUBLISH device:{device_id}:updates  <any message triggers full reload>

    Public interface
    ----------------
    get(oid)       → raw JSON string or None
    sorted_pairs() → list of (numeric_tuple, oid_str) in numeric OID order
    """

    def __init__(self, redis_url: str, device_id: str) -> None:
        self.device_id = device_id
        self._key     = f"device:{device_id}:oids"
        self._channel = f"device:{device_id}:updates"

        # Two separate connections: one for commands, one for blocking pubsub.
        self._r     = redis_lib.from_url(redis_url, decode_responses=True)
        self._r_sub = redis_lib.from_url(redis_url, decode_responses=True)

        # _cache: oid_str → raw_json  (all lookups)
        self._cache: dict[str, str] = {}
        # _pairs: [(numeric_tuple, oid_str)] sorted numerically (GETNEXT / GETBULK)
        self._pairs: list[tuple] = []
        # _tuples: just the numeric tuples from _pairs, for fast bisect
        self._tuples: list[tuple] = []
        self._lock = threading.Lock()

        self._load_all()
        self._start_listener()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def get(self, oid: str) -> str | None:
        """Return the raw JSON string for *oid*, or None if not present."""
        with self._lock:
            return self._cache.get(oid)

    def sorted_pairs(self) -> tuple:
        """Return (pairs, tuples) — the pre-built sorted structures.

        pairs:  [(numeric_tuple, oid_str)] in numeric OID order
        tuples: [numeric_tuple] — same order, for direct bisect_right use

        Both are shallow-copied so the lock can be released immediately.
        """
        with self._lock:
            return list(self._pairs), list(self._tuples)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_all(self) -> None:
        """Pull the entire OID hash from Redis, validate, and sort numerically.

        Non-numeric OID keys are silently discarded with a warning.
        """
        try:
            raw = self._r.hgetall(self._key)
        except Exception:
            raw = {}

        cache: dict[str, str] = {}
        skipped = 0
        for oid, val in raw.items():
            if _is_numeric_oid(oid):
                cache[oid] = val
            else:
                skipped += 1

        if skipped:
            log.warning(
                "device %s: discarded %d non-numeric OID key(s) from Redis.",
                self.device_id, skipped,
            )

        # Sort numerically — critical for correct GETNEXT traversal
        pairs = sorted(
            [(_oid_tuple(oid), oid) for oid in cache],
            key=lambda p: p[0],
        )
        tuples = [p[0] for p in pairs]

        with self._lock:
            self._cache = cache
            self._pairs = pairs
            self._tuples = tuples

        log.info("device %s: loaded %d OIDs.", self.device_id, len(cache))

    def _start_listener(self) -> None:
        """Start a daemon thread that watches for update notifications."""
        t = threading.Thread(
            target=self._listen, daemon=True, name=f"mib-listener-{self.device_id}"
        )
        t.start()

    def _listen(self) -> None:
        while True:
            try:
                p = self._r_sub.pubsub()
                p.subscribe(self._channel)
                for msg in p.listen():
                    if msg["type"] == "message":
                        self._load_all()
            except Exception:
                import time as _time
                _time.sleep(2)
