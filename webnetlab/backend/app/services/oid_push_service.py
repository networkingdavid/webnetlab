import json
import logging
import re

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.models.oid_value import OIDValue

log = logging.getLogger(__name__)

_NUMERIC_OID_RE = re.compile(r"^\d+(\.\d+)*$")


def is_numeric_oid(oid: str) -> bool:
    """Return True only if *oid* is a pure dotted-numeric OID string."""
    return bool(oid and _NUMERIC_OID_RE.match(oid.strip(".")))


async def push_device_oids(device_id: int, db: AsyncSession) -> int:
    """Load all OIDValue records for device_id from DB and write them to Redis.
    Returns count of OIDs pushed."""
    r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        result = await db.execute(
            select(OIDValue).where(OIDValue.device_id == device_id)
        )
        oid_values = result.scalars().all()

        key = f"device:{device_id}:oids"
        pipe = r.pipeline()
        pipe.delete(key)  # clear existing

        for ov in oid_values:
            vtype = getattr(ov, "value_type", "string") or "string"
            if ov.value_mode == "static":
                payload = {"mode": "static", "value": ov.static_value or "", "type": vtype}
            elif ov.value_mode == "walk_seed":
                payload = {"mode": "walk_seed", "value": ov.walk_seed_value or "", "type": vtype}
            elif ov.value_mode == "random":
                payload = {"mode": "random", "config": ov.random_config or {}}
            elif ov.value_mode == "scripted":
                payload = {"mode": "scripted", "script": ov.script or "0", "type": vtype}
            else:
                payload = {"mode": "static", "value": "", "type": "string"}
            if not is_numeric_oid(ov.oid):
                log.warning("push_device_oids: skipping non-numeric OID %r for device %s", ov.oid, device_id)
                continue
            pipe.hset(key, ov.oid, json.dumps(payload))

        await pipe.execute()
        return len(oid_values)
    finally:
        await r.aclose()


async def notify_device_update(device_id: int) -> None:
    """Publish update notification so running agent invalidates its cache."""
    r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        await r.publish(f"device:{device_id}:updates", "reload")
    finally:
        await r.aclose()
