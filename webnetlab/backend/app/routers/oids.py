"""OID Value Configuration API.

All paths are fully-qualified here because this router has two distinct
path prefixes (/api/devices/{device_id}/oids and /api/devices/bulk-oids).
It is registered on the root api_router without a prefix.
"""

import json
from datetime import datetime
from urllib.parse import unquote

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.config import settings
from app.database import get_db
from app.models.device import Device
from app.models.oid_value import OIDValue
from app.schemas.oid_value import (
    BulkDeviceOIDUpdate,
    BulkOIDUpdate,
    OIDValueCreate,
    OIDValueResponse,
    OIDValueUpdate,
)
from app.services.oid_push_service import notify_device_update, push_device_oids, is_numeric_oid
from app.services.walk_parser import parse_snmpwalk

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_device_or_404(device_id: int, db: AsyncSession) -> Device:
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return device


async def _get_oid_record(device_id: int, oid: str, db: AsyncSession) -> OIDValue | None:
    result = await db.execute(
        select(OIDValue)
        .where(OIDValue.device_id == device_id, OIDValue.oid == oid)
    )
    return result.scalar_one_or_none()


def _apply_fields(record: OIDValue, payload: OIDValueCreate | OIDValueUpdate) -> None:
    """Write non-None payload fields onto the ORM record in-place."""
    if hasattr(payload, "oid") and payload.oid is not None:
        record.oid = payload.oid
    if payload.value_mode is not None:
        record.value_mode = payload.value_mode
    if payload.static_value is not None:
        record.static_value = payload.static_value
    if payload.random_config is not None:
        record.random_config = payload.random_config
    if payload.script is not None:
        record.script = payload.script
    if payload.walk_seed_value is not None:
        record.walk_seed_value = payload.walk_seed_value
    if hasattr(payload, "value_type") and payload.value_type is not None:
        record.value_type = payload.value_type
    record.updated_at = datetime.utcnow()


# ---------------------------------------------------------------------------
# GET /api/devices/{device_id}/oids
# ---------------------------------------------------------------------------

@router.get(
    "/api/devices/{device_id}/oids",
    response_model=list[OIDValueResponse],
    tags=["oids"],
)
async def list_device_oids(
    device_id: int,
    mode: str | None = Query(default=None, description="Filter by value_mode (static|random|scripted|walk_seed)"),
    db: AsyncSession = Depends(get_db),
):
    await _get_device_or_404(device_id, db)
    stmt = select(OIDValue).where(OIDValue.device_id == device_id)
    if mode:
        stmt = stmt.where(OIDValue.value_mode == mode)
    result = await db.execute(stmt.order_by(OIDValue.oid))
    return result.scalars().all()


# ---------------------------------------------------------------------------
# GET /api/devices/{device_id}/oids/export — download seed JSON
# ---------------------------------------------------------------------------

@router.get(
    "/api/devices/{device_id}/oids/export",
    tags=["oids"],
    summary="Export all OID values as a seed JSON file",
)
async def export_device_oids(
    device_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Returns a JSON file containing all OID configs for this device in the exact
    format accepted by POST /api/devices/{id}/oids/bulk (BulkOIDUpdate).

    The downloaded file can be:
      - Imported directly via the Seed Import tab on any device.
      - Used with the bulk OID endpoint to clone one device's config onto others.

    File format:
    {
      "device_id": <int>,
      "device_name": "<str>",
      "exported_at": "<ISO datetime>",
      "updates": [
        {"oid": "...", "value_mode": "static", "static_value": "...", "value_type": "..."},
        {"oid": "...", "value_mode": "random", "random_config": {...}},
        ...
      ]
    }
    """
    device = await _get_device_or_404(device_id, db)
    result = await db.execute(
        select(OIDValue)
        .where(OIDValue.device_id == device_id)
        .order_by(OIDValue.oid)
    )
    oid_values = result.scalars().all()

    updates = []
    for ov in oid_values:
        entry: dict = {
            "oid": ov.oid,
            "value_mode": ov.value_mode,
            "value_type": getattr(ov, "value_type", "string") or "string",
        }
        if ov.value_mode in ("static", "walk_seed"):
            entry["static_value"] = ov.static_value or ov.walk_seed_value or ""
        if ov.value_mode == "random" and ov.random_config:
            entry["random_config"] = ov.random_config
        if ov.value_mode == "scripted" and ov.script:
            entry["script"] = ov.script
        updates.append(entry)

    payload = {
        "device_id": device_id,
        "device_name": device.name,
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "updates": updates,
    }

    filename = f"{device.name.replace(' ', '_')}_oids.json"
    return Response(
        content=json.dumps(payload, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# PUT /api/devices/{device_id}/oids/{oid} — upsert single OID
# ---------------------------------------------------------------------------

@router.put(
    "/api/devices/{device_id}/oids/{oid:path}",
    response_model=OIDValueResponse,
    tags=["oids"],
)
async def upsert_oid(
    device_id: int,
    oid: str,
    payload: OIDValueCreate,
    db: AsyncSession = Depends(get_db),
):
    # URL-decode the OID path segment (dots are safe in URLs but be defensive)
    oid = unquote(oid)

    if not is_numeric_oid(oid):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"OID must be a dotted-numeric string (e.g. 1.3.6.1.2.1.1.1.0). Got: {oid!r}",
        )

    await _get_device_or_404(device_id, db)

    record = await _get_oid_record(device_id, oid, db)
    if record is None:
        record = OIDValue(device_id=device_id, oid=oid)
        db.add(record)

    _apply_fields(record, payload)
    await db.commit()
    await db.refresh(record)

    await push_device_oids(device_id, db)
    await notify_device_update(device_id)

    return record


# ---------------------------------------------------------------------------
# POST /api/devices/{device_id}/oids/bulk — bulk upsert
# ---------------------------------------------------------------------------

@router.post(
    "/api/devices/{device_id}/oids/bulk",
    tags=["oids"],
)
async def bulk_upsert_oids(
    device_id: int,
    payload: BulkOIDUpdate,
    db: AsyncSession = Depends(get_db),
):
    await _get_device_or_404(device_id, db)

    skipped = []
    for item in payload.updates:
        if not is_numeric_oid(item.oid):
            skipped.append(item.oid)
            continue
        record = await _get_oid_record(device_id, item.oid, db)
        if record is None:
            record = OIDValue(device_id=device_id, oid=item.oid)
            db.add(record)
        _apply_fields(record, item)

    await db.commit()

    await push_device_oids(device_id, db)
    await notify_device_update(device_id)

    result: dict = {"updated": len(payload.updates) - len(skipped)}
    if skipped:
        result["skipped_non_numeric"] = skipped
    return result


# ---------------------------------------------------------------------------
# DELETE /api/devices/{device_id}/oids/{oid}
# ---------------------------------------------------------------------------

@router.delete(
    "/api/devices/{device_id}/oids/{oid:path}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["oids"],
)
async def delete_oid(
    device_id: int,
    oid: str,
    db: AsyncSession = Depends(get_db),
):
    oid = unquote(oid)
    await _get_device_or_404(device_id, db)

    record = await _get_oid_record(device_id, oid, db)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OID not found")

    await db.delete(record)
    await db.commit()

    # Remove just this OID key from the Redis hash
    r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        await r.hdel(f"device:{device_id}:oids", oid)
    finally:
        await r.aclose()

    await notify_device_update(device_id)


# ---------------------------------------------------------------------------
# POST /api/devices/{device_id}/seed — seed OIDs from snmpwalk text OR exported JSON
# ---------------------------------------------------------------------------

@router.post(
    "/api/devices/{device_id}/seed",
    tags=["oids"],
)
async def seed_from_walk(
    device_id: int,
    file: UploadFile = File(...),
    preview: bool = Query(default=False, description="Return a preview without persisting"),
    db: AsyncSession = Depends(get_db),
):
    """Accept either:
    - A plain snmpwalk text file (standard format)
    - A WebNetLab seed JSON export (produced by GET /api/devices/{id}/oids/export)

    The two formats are auto-detected by attempting JSON parse first.
    """
    await _get_device_or_404(device_id, db)

    raw = await file.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    # ── Auto-detect: try JSON seed export first ───────────────────────────────
    try:
        import json as _json
        parsed_json = _json.loads(text)
        if isinstance(parsed_json, dict) and "updates" in parsed_json:
            updates = parsed_json["updates"]
            if not isinstance(updates, list):
                raise HTTPException(status_code=400, detail="Invalid seed JSON: 'updates' must be a list")

            if preview:
                return {
                    "parsed": len(updates),
                    "preview": [
                        {"oid": u.get("oid", ""), "value": u.get("static_value") or str(u.get("random_config", ""))}
                        for u in updates[:10]
                    ],
                    "format": "json",
                }

            # Upsert each entry preserving all fields (value_mode, value_type, etc.)
            for u in updates:
                oid = u.get("oid")
                if not oid:
                    continue
                record = await _get_oid_record(device_id, oid, db)
                if record is None:
                    record = OIDValue(device_id=device_id, oid=oid)
                    db.add(record)
                record.value_mode = u.get("value_mode", "static")
                record.static_value = u.get("static_value")
                record.walk_seed_value = u.get("walk_seed_value") or u.get("static_value")
                record.random_config = u.get("random_config")
                record.script = u.get("script")
                record.value_type = u.get("value_type", "string")
                record.updated_at = datetime.utcnow()

            await db.commit()
            await push_device_oids(device_id, db)
            await notify_device_update(device_id)
            return {"seeded": len(updates), "format": "json"}
    except (ValueError, KeyError):
        pass  # not valid JSON — fall through to snmpwalk text parser

    # ── snmpwalk text format ──────────────────────────────────────────────────
    entries = parse_snmpwalk(text)

    if preview:
        return {
            "parsed": len(entries),
            "preview": [{"oid": e.oid, "value": e.value} for e in entries[:10]],
            "format": "snmpwalk",
        }

    for entry in entries:
        record = await _get_oid_record(device_id, entry.oid, db)
        if record is None:
            record = OIDValue(device_id=device_id, oid=entry.oid)
            db.add(record)
        record.value_mode = "walk_seed"
        record.walk_seed_value = entry.value
        record.updated_at = datetime.utcnow()

    await db.commit()
    await push_device_oids(device_id, db)
    await notify_device_update(device_id)
    return {"seeded": len(entries), "format": "snmpwalk"}


# ---------------------------------------------------------------------------
# POST /api/devices/bulk-oids — apply same OID config to multiple devices
# ---------------------------------------------------------------------------

@router.post(
    "/api/devices/bulk-oids",
    tags=["oids"],
)
async def bulk_device_oids(
    payload: BulkDeviceOIDUpdate,
    db: AsyncSession = Depends(get_db),
):
    updated_devices = 0

    for device_id in payload.device_ids:
        # Skip devices that don't exist rather than hard-failing the whole batch
        device = await db.get(Device, device_id)
        if not device:
            continue

        record = await _get_oid_record(device_id, payload.oid, db)
        if record is None:
            record = OIDValue(device_id=device_id, oid=payload.oid)
            db.add(record)

        record.value_mode = payload.value_mode
        record.static_value = payload.static_value
        record.random_config = payload.random_config
        record.script = payload.script
        record.walk_seed_value = payload.walk_seed_value
        record.updated_at = datetime.utcnow()
        updated_devices += 1

    await db.commit()

    # Push and notify each updated device
    for device_id in payload.device_ids:
        device = await db.get(Device, device_id)
        if not device:
            continue
        await push_device_oids(device_id, db)
        await notify_device_update(device_id)

    return {"updated_devices": updated_devices, "oid": payload.oid}
