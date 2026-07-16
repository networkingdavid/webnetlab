"""
MIB management router.

Endpoints
---------
POST   /api/mibs/upload                  — upload & compile a MIB file
GET    /api/mibs                          — list all MIBs
GET    /api/mibs/{mib_id}                 — get single MIB metadata
GET    /api/mibs/{mib_id}/oids            — return full OID tree
POST   /api/mibs/{mib_id}/assign/{device_id}  — assign MIB to a device
DELETE /api/mibs/{mib_id}/assign/{device_id}  — unassign MIB from a device
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.mib import MIB, DeviceMIB
from app.models.device import Device
from app.services import mib_service

router = APIRouter()

MIB_STORE = Path(os.environ.get("MIB_STORE", "/app/mibs"))


# ---------------------------------------------------------------------------
# POST /upload
# ---------------------------------------------------------------------------

@router.post("/upload")
async def upload_mib(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Upload a MIB file, compile it, persist metadata + OID sidecar."""

    MIB_STORE.mkdir(parents=True, exist_ok=True)
    filename = Path(file.filename or "unknown.mib").name
    mib_name = Path(filename).stem
    dest = MIB_STORE / filename

    raw_bytes = await file.read()
    raw_text = raw_bytes.decode("utf-8", errors="replace")
    dest.write_bytes(raw_bytes)

    # Compile
    oids = mib_service.parse_mib_file(str(dest))

    # Check for error sentinel
    if oids and "error" in oids[0]:
        err = oids[0]
        error_msg = err.get("error", "compilation_failed")
        details = err.get("details", "")

        # Distinguish missing-dependency errors
        if "missing" in error_msg.lower() or "status=missing" in details.lower():
            missing = _extract_missing(details)
            raise HTTPException(
                status_code=422,
                detail={"error": "missing_dependency", "missing": missing},
            )
        raise HTTPException(
            status_code=422,
            detail={"error": error_msg, "details": details},
        )

    # Save OID sidecar JSON
    sidecar_path = mib_service.save_oid_tree(mib_name, oids)

    # Persist / update DB record
    result = await db.execute(select(MIB).where(MIB.name == mib_name))
    mib_row = result.scalars().first()

    if mib_row is None:
        mib_row = MIB(
            name=mib_name,
            filename=filename,
            raw_content=raw_text,
            parsed_at=datetime.utcnow(),
            oid_tree_path=sidecar_path,
        )
        db.add(mib_row)
    else:
        mib_row.filename = filename
        mib_row.raw_content = raw_text
        mib_row.parsed_at = datetime.utcnow()
        mib_row.oid_tree_path = sidecar_path

    await db.commit()
    await db.refresh(mib_row)

    return {
        "id": mib_row.id,
        "name": mib_row.name,
        "oid_count": len(oids),
        "oids": oids,
    }


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------

@router.get("")
async def list_mibs(db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    """Return summary list of all uploaded MIBs."""
    result = await db.execute(select(MIB).order_by(MIB.created_at.desc()))
    mibs = result.scalars().all()
    return [
        {
            "id": m.id,
            "name": m.name,
            "filename": m.filename,
            "oid_count": _count_oids(m.oid_tree_path),
            "parsed_at": m.parsed_at.isoformat() if m.parsed_at else None,
            "created_at": m.created_at.isoformat(),
        }
        for m in mibs
    ]


# ---------------------------------------------------------------------------
# GET /{mib_id}
# ---------------------------------------------------------------------------

@router.get("/{mib_id}")
async def get_mib(mib_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Return metadata for a single MIB."""
    mib_row = await _get_or_404(mib_id, db)
    return {
        "id": mib_row.id,
        "name": mib_row.name,
        "filename": mib_row.filename,
        "oid_count": _count_oids(mib_row.oid_tree_path),
        "parsed_at": mib_row.parsed_at.isoformat() if mib_row.parsed_at else None,
        "created_at": mib_row.created_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# GET /{mib_id}/oids
# ---------------------------------------------------------------------------

@router.get("/{mib_id}/oids")
async def get_mib_oids(
    mib_id: int, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Return the full OID tree stored in the JSON sidecar file."""
    mib_row = await _get_or_404(mib_id, db)
    if not mib_row.oid_tree_path or not Path(mib_row.oid_tree_path).exists():
        raise HTTPException(status_code=404, detail="OID tree not found. Re-upload the MIB.")
    oids = mib_service.load_oid_tree(mib_row.oid_tree_path)
    return {"id": mib_id, "name": mib_row.name, "oid_count": len(oids), "oids": oids}


# ---------------------------------------------------------------------------
# POST /{mib_id}/assign/{device_id}
# ---------------------------------------------------------------------------

@router.post("/{mib_id}/assign/{device_id}")
async def assign_mib(
    mib_id: int, device_id: int, db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    """Assign a MIB to a device (creates device_mibs junction record)."""
    await _get_or_404(mib_id, db)

    # Verify device exists
    dev_result = await db.execute(select(Device).where(Device.id == device_id))
    if dev_result.scalars().first() is None:
        raise HTTPException(status_code=404, detail=f"Device {device_id} not found")

    # Check for existing assignment
    existing = await db.execute(
        select(DeviceMIB).where(
            DeviceMIB.mib_id == mib_id, DeviceMIB.device_id == device_id
        )
    )
    if existing.scalars().first() is not None:
        raise HTTPException(status_code=409, detail="MIB already assigned to this device")

    db.add(DeviceMIB(device_id=device_id, mib_id=mib_id))
    await db.commit()
    return {"status": "assigned"}


# ---------------------------------------------------------------------------
# DELETE /{mib_id}/assign/{device_id}
# ---------------------------------------------------------------------------

@router.delete("/{mib_id}/assign/{device_id}")
async def unassign_mib(
    mib_id: int, device_id: int, db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    """Remove a MIB ↔ device assignment."""
    await db.execute(
        delete(DeviceMIB).where(
            DeviceMIB.mib_id == mib_id, DeviceMIB.device_id == device_id
        )
    )
    await db.commit()
    return {"status": "unassigned"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_or_404(mib_id: int, db: AsyncSession) -> MIB:
    result = await db.execute(select(MIB).where(MIB.id == mib_id))
    mib_row = result.scalars().first()
    if mib_row is None:
        raise HTTPException(status_code=404, detail=f"MIB {mib_id} not found")
    return mib_row


def _count_oids(sidecar_path: str | None) -> int:
    if not sidecar_path:
        return 0
    p = Path(sidecar_path)
    if not p.exists():
        return 0
    try:
        import json
        data = json.loads(p.read_text())
        return len(data)
    except Exception:
        return 0


def _extract_missing(error_detail: str) -> list[str]:
    """Pull MIB names from a 'status=missing' error string."""
    import re
    return re.findall(r"'([A-Z][A-Z0-9\-]+)'", error_detail)
