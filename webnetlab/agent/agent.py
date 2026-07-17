"""
agent.py — WebNetLab SNMP agent (pysnmp 4.4.x, SNMPv2c only).

Environment variables
---------------------
DEVICE_ID       integer device ID (matches Redis key device:{DEVICE_ID}:oids)
SNMP_COMMUNITY  community string to accept  (default: public)
REDIS_URL       redis://host:port/db        (default: redis://localhost:6379/0)
LISTEN_IP       UDP bind address             (default: 0.0.0.0)
LISTEN_PORT     UDP bind port                (default: 161)

Supported PDU types
-------------------
GetRequest      — returns exact OID value or noSuchObject
GetNextRequest  — returns next OID in lexicographic order or endOfMibView
GetBulkRequest  — iterates up to max-repetitions OIDs via GETNEXT logic

SNMPv1 and SNMPv3 packets are silently discarded.
Wrong community strings are silently discarded.

Performance notes (3 000+ OIDs)
--------------------------------
* MibStore keeps OIDs sorted in NUMERIC order internally.  sorted_pairs()
  returns the pre-built [(tuple, oid_str)] list — O(1), no rebuild per request.
* next_oid() does a single bisect_right on that list — O(log n).
* A full walk of N OIDs costs O(N log N) total (one bisect per GETNEXT).
* GETBULK max-repetitions is capped at MAX_REPETITIONS (default 1 000).
  Additionally, response var-binds are cut off once the encoded byte estimate
  exceeds MAX_RESPONSE_BYTES (~45 000 bytes) to stay safely under the 65 535
  UDP limit.
"""

import bisect
import logging
import os
import sys

import redis as _redis_sync

from pyasn1.codec.ber import decoder, encoder
from pyasn1.type.univ import OctetString, Integer, ObjectIdentifier
from pysnmp.proto.rfc1902 import Counter32, Gauge32, TimeTicks, IpAddress
from pysnmp.carrier.asyncore.dgram import udp
from pysnmp.carrier.asyncore.dispatch import AsyncoreDispatcher
from pysnmp.proto import api as proto_api
from pysnmp.proto.rfc1905 import NoSuchObject, EndOfMibView

from mib_store import MibStore
from oid_resolver import resolve_oid_value

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [agent] %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------

DEVICE_ID    = os.environ.get("DEVICE_ID", "0")
COMMUNITY    = os.environ.get("SNMP_COMMUNITY", "public").encode()
REDIS_URL    = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
LISTEN_IP    = os.environ.get("LISTEN_IP", "0.0.0.0")
LISTEN_PORT  = int(os.environ.get("LISTEN_PORT", "161"))

# GETBULK: absolute upper bound on repetitions per request
MAX_REPETITIONS = 1_000

# Soft byte budget per GETBULK response.
# UDP max payload = 65535 bytes; we stop building var-binds before that.
# 45 000 gives comfortable headroom for SNMP/UDP/IP headers.
MAX_RESPONSE_BYTES = 45_000

# ---------------------------------------------------------------------------
# OID helpers
# ---------------------------------------------------------------------------


def oid_to_tuple(oid_str: str) -> tuple:
    """Convert '1.3.6.1.2.1.1.1.0' → (1, 3, 6, 1, 2, 1, 1, 1, 0).

    Returns an empty tuple for non-numeric strings so callers can skip them.
    """
    try:
        return tuple(int(x) for x in oid_str.strip(".").split("."))
    except ValueError:
        log.warning("oid_to_tuple: skipping non-numeric OID %r", oid_str)
        return ()


def tuple_to_oid(t: tuple) -> str:
    return ".".join(str(x) for x in t)


def next_oid(pairs: list, tuples: list, oid_str: str) -> str | None:
    """Return the numerically next OID after *oid_str*.

    pairs:  [(numeric_tuple, oid_str)] from MibStore.sorted_pairs()
    tuples: [numeric_tuple] — parallel list for O(log n) bisect_right
    """
    target = oid_to_tuple(oid_str) if oid_str else ()
    if not target:
        return pairs[0][1] if pairs else None
    idx = bisect.bisect_right(tuples, target)
    return pairs[idx][1] if idx < len(pairs) else None


# ---------------------------------------------------------------------------
# Value encoding helpers
# ---------------------------------------------------------------------------


def _encode_value(raw_value, type_hint: str = "string"):
    """
    Encode a Python value into the correct ASN.1 type using the type hint
    returned by resolve_oid_value.

    type_hint values: string | integer | counter | gauge | timeticks | ipaddress
    """
    if type_hint == "counter":
        return Counter32(int(raw_value) if raw_value else 0)
    if type_hint == "gauge":
        return Gauge32(int(raw_value) if raw_value else 0)
    if type_hint == "timeticks":
        return TimeTicks(int(raw_value) if raw_value else 0)
    if type_hint == "integer":
        return Integer(int(raw_value) if raw_value else 0)
    if type_hint == "ipaddress":
        try:
            return IpAddress(raw_value)
        except Exception:
            return OctetString(str(raw_value).encode())
    if isinstance(raw_value, (bytes, bytearray)):
        return OctetString(raw_value)
    if isinstance(raw_value, int):
        return Integer(raw_value)
    return OctetString(str(raw_value).encode())


# ---------------------------------------------------------------------------
# Main request callback
# ---------------------------------------------------------------------------

_store: MibStore  # set in main()


def _cb_fun(transport_dispatcher, transport_domain, transport_address, whole_msg):
    """
    Called by AsyncoreDispatcher for every incoming UDP datagram.

    Any unhandled exception is caught here so a bad packet or corrupt OID
    never propagates into pysnmp's asyncore loop and kills the process.
    """
    try:
        whole_msg = _cb_fun_inner(
            transport_dispatcher, transport_domain, transport_address, whole_msg
        )
    except Exception as exc:
        log.error(
            "Unhandled error in packet handler (packet dropped): %s", exc, exc_info=True
        )
        whole_msg = bytes()
    return whole_msg


def _cb_fun_inner(transport_dispatcher, transport_domain, transport_address, whole_msg):
    """Inner handler — separated so _cb_fun can catch all exceptions."""
    while whole_msg:
        # ----------------------------------------------------------------
        # Decode SNMP version
        # ----------------------------------------------------------------
        try:
            msg_ver = proto_api.decodeMessageVersion(whole_msg)
        except Exception:
            break

        if msg_ver not in proto_api.protoModules:
            log.debug("Unknown SNMP version byte; discarding.")
            break

        # ----------------------------------------------------------------
        # Only handle SNMPv2c (proto_api.protoVersion2c == 1)
        # ----------------------------------------------------------------
        if msg_ver != proto_api.protoVersion2c:
            log.debug("Non-v2c message (version=%s); discarding.", msg_ver)
            break

        p_mod = proto_api.protoModules[msg_ver]

        try:
            req_msg, whole_msg = decoder.decode(whole_msg, asn1Spec=p_mod.Message())
        except Exception as exc:
            log.warning("Decode error: %s", exc)
            break

        # ----------------------------------------------------------------
        # Community string check
        # ----------------------------------------------------------------
        req_community = bytes(p_mod.apiMessage.getCommunity(req_msg))
        if req_community != COMMUNITY:
            log.debug("Wrong community '%s'; discarding.", req_community)
            whole_msg = bytes()
            continue

        req_pdu      = p_mod.apiMessage.getPDU(req_msg)
        req_pdu_type = req_pdu.__class__.__name__

        # ----------------------------------------------------------------
        # Build the response scaffold
        # ----------------------------------------------------------------
        rsp_pdu = p_mod.GetResponsePDU()
        p_mod.apiPDU.setDefaults(rsp_pdu)
        p_mod.apiPDU.setRequestID(rsp_pdu, p_mod.apiPDU.getRequestID(req_pdu))

        rsp_msg = p_mod.Message()
        p_mod.apiMessage.setDefaults(rsp_msg)
        p_mod.apiMessage.setCommunity(rsp_msg, p_mod.apiMessage.getCommunity(req_msg))
        p_mod.apiMessage.setPDU(rsp_msg, rsp_pdu)

        # ----------------------------------------------------------------
        # Dispatch by PDU type
        # ----------------------------------------------------------------
        if req_pdu_type in ("GetRequestPDU", "GetNextRequestPDU"):
            _handle_get(p_mod, req_pdu, rsp_pdu, getnext=(req_pdu_type == "GetNextRequestPDU"))
            _increment_query_counter()

        elif req_pdu_type == "GetBulkRequestPDU":
            _handle_getbulk(p_mod, req_pdu, rsp_pdu)
            _increment_query_counter()

        else:
            log.debug("Unsupported PDU type '%s'; discarding.", req_pdu_type)
            whole_msg = bytes()
            continue

        # ----------------------------------------------------------------
        # Send response
        # ----------------------------------------------------------------
        transport_dispatcher.sendMessage(
            encoder.encode(rsp_msg), transport_domain, transport_address
        )

        return whole_msg
    return whole_msg


# ---------------------------------------------------------------------------
# GET / GETNEXT handler
# ---------------------------------------------------------------------------


def _handle_get(p_mod, req_pdu, rsp_pdu, *, getnext: bool) -> None:
    """Fill *rsp_pdu* var-binds for a GET or GETNEXT request."""
    req_var_binds = p_mod.apiPDU.getVarBinds(req_pdu)
    rsp_var_binds = []
    # O(1) — pre-built in numeric order inside MibStore
    oid_pairs, oid_tuples = _store.sorted_pairs()

    for oid, _ in req_var_binds:
        oid_str = tuple_to_oid(tuple(oid))

        if getnext:
            target_oid = next_oid(oid_pairs, oid_tuples, oid_str)
        else:
            target_oid = oid_str if _store.get(oid_str) is not None else None

        if target_oid is None:
            if getnext:
                rsp_var_binds.append((oid, EndOfMibView()))
            else:
                rsp_var_binds.append((oid, NoSuchObject()))
            continue

        raw_json = _store.get(target_oid)
        if raw_json is None:
            rsp_var_binds.append((oid, NoSuchObject()))
            continue

        try:
            value, vtype = resolve_oid_value(raw_json)
            encoded = _encode_value(value, vtype)
        except Exception as exc:
            log.warning("resolve error for %s: %s", target_oid, exc)
            rsp_var_binds.append((oid, NoSuchObject()))
            continue

        rsp_var_binds.append((p_mod.ObjectIdentifier(oid_to_tuple(target_oid)), encoded))

    p_mod.apiPDU.setVarBinds(rsp_pdu, rsp_var_binds)


# ---------------------------------------------------------------------------
# GETBULK handler
# ---------------------------------------------------------------------------


def _handle_getbulk(p_mod, req_pdu, rsp_pdu) -> None:
    """
    Fill *rsp_pdu* var-binds for a GETBULK request.

    GetBulk layout:
      non-repeaters  (first N var-binds): treated as GETNEXT once
      repeaters      (remaining):         iterated up to max-repetitions times

    Two safety limits prevent oversized UDP responses:
      1. MAX_REPETITIONS hard cap (1 000) — limits loop iterations
      2. MAX_RESPONSE_BYTES soft cap (~45 KB) — stops adding var-binds once
         the estimated encoded size would exceed the UDP payload budget
    """
    non_repeaters   = int(req_pdu.getComponentByName("non-repeaters"))
    max_repetitions = min(
        int(req_pdu.getComponentByName("max-repetitions")),
        MAX_REPETITIONS,
    )

    req_var_binds = p_mod.apiPDU.getVarBinds(req_pdu)
    # O(1) — pre-built in numeric order inside MibStore
    oid_pairs, oid_tuples = _store.sorted_pairs()
    rsp_var_binds   = []
    estimated_bytes = 0

    def _resolve(oid_str):
        """Resolve one OID string to (ObjectIdentifier, encoded_value) or None."""
        raw_json = _store.get(oid_str)
        if raw_json is None:
            return None, NoSuchObject()
        try:
            v, vt = resolve_oid_value(raw_json)
            return p_mod.ObjectIdentifier(oid_to_tuple(oid_str)), _encode_value(v, vt)
        except Exception:
            return p_mod.ObjectIdentifier(oid_to_tuple(oid_str)), NoSuchObject()

    # --- Non-repeaters: one GETNEXT each ---
    for oid, _ in req_var_binds[:non_repeaters]:
        oid_str = tuple_to_oid(tuple(oid))
        target  = next_oid(oid_pairs, oid_tuples, oid_str)
        if target is None:
            rsp_var_binds.append((oid, EndOfMibView()))
        else:
            oid_obj, val = _resolve(target)
            rsp_var_binds.append((oid_obj, val))
            # Rough size estimate: OID length (bytes) + value length
            estimated_bytes += len(target) + 20

    # --- Repeaters: iterate up to max-repetitions times for each ---
    for oid, _ in req_var_binds[non_repeaters:]:
        cursor = tuple_to_oid(tuple(oid))
        for _ in range(max_repetitions):
            if estimated_bytes >= MAX_RESPONSE_BYTES:
                # Response is full — terminate this repeater column early
                log.debug("GETBULK response size limit reached (~%d bytes)", estimated_bytes)
                break
            target = next_oid(oid_pairs, oid_tuples, cursor)
            if target is None:
                rsp_var_binds.append(
                    (p_mod.ObjectIdentifier(oid_to_tuple(cursor)), EndOfMibView())
                )
                break
            oid_obj, val = _resolve(target)
            rsp_var_binds.append((oid_obj, val))
            estimated_bytes += len(target) + 20
            cursor = target

    p_mod.apiPDU.setVarBinds(rsp_pdu, rsp_var_binds)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Redis query counter (sync client — asyncore is single-threaded)
# ---------------------------------------------------------------------------

_redis_client: "_redis_sync.Redis | None" = None
_QUERY_COUNTER_KEY = f"device:{DEVICE_ID}:snmp_queries"


def _init_redis_counter() -> None:
    """Create a sync Redis client for incrementing the query counter."""
    global _redis_client
    try:
        _redis_client = _redis_sync.from_url(REDIS_URL, decode_responses=True)
        _redis_client.ping()
        log.info("Redis counter ready — key=%s", _QUERY_COUNTER_KEY)
    except Exception as exc:
        log.warning("Redis counter unavailable: %s — queries will not be tracked", exc)
        _redis_client = None


def _increment_query_counter() -> None:
    """Non-fatal INCR on the device query counter key."""
    if _redis_client is None:
        return
    try:
        _redis_client.incr(_QUERY_COUNTER_KEY)
    except Exception:
        pass  # never crash the SNMP handler


def main() -> None:
    global _store

    log.info(
        "Starting WebNetLab SNMP agent — device_id=%s  community=%s  bind=%s:%s",
        DEVICE_ID, COMMUNITY.decode(), LISTEN_IP, LISTEN_PORT,
    )

    _store = MibStore(redis_url=REDIS_URL, device_id=DEVICE_ID)
    _init_redis_counter()

    dispatcher = AsyncoreDispatcher()
    dispatcher.registerRecvCbFun(_cb_fun)

    dispatcher.registerTransport(
        udp.domainName,
        udp.UdpSocketTransport().openServerMode((LISTEN_IP, LISTEN_PORT)),
    )

    log.info("Listening on UDP %s:%d", LISTEN_IP, LISTEN_PORT)

    try:
        dispatcher.jobStarted(1)
        dispatcher.runDispatcher()
    except KeyboardInterrupt:
        log.info("Interrupted — shutting down.")
    finally:
        dispatcher.closeDispatcher()


if __name__ == "__main__":
    main()
