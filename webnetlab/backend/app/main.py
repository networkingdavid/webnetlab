import os
import platform as _platform
from datetime import datetime

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from alembic.config import Config
from alembic import command
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.models.audit import AuditLog
from app.models.device import Device
from app.models.mib import MIB
from app.models.network import Network
from app.routers import router as api_router

app = FastAPI(title="WebNetLab", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.on_event("startup")
async def run_migrations():
    alembic_cfg = Config("/app/alembic.ini")
    command.upgrade(alembic_cfg, "head")


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


@app.get("/api/platform")
async def platform_info():
    """Returns host platform info so the UI can show relevant network-mode warnings.

    HOST_PLATFORM env var is set in docker-compose.yml to the actual host OS.
    Defaults to the container OS (Linux) if not set, which means macvlan is allowed
    only when explicitly running on a Linux host.
    """
    system = os.environ.get("HOST_PLATFORM", _platform.system())
    macvlan_ok = system == "Linux"
    return {
        "system": system,
        "macvlan_supported": macvlan_ok,
        "note": (
            "macvlan requires Linux with a physical NIC. "
            "On macOS use 'host-bridge' — Docker Desktop routes container subnets to the host automatically."
        ) if not macvlan_ok else None,
    }


@app.get("/api/stats")
async def stats(db: AsyncSession = Depends(get_db)):
    """Dashboard stats — device count, running count, network count, MIB count, SNMP queries."""
    import redis.asyncio as aioredis
    from app.config import settings

    device_count    = await db.scalar(select(func.count(Device.id))) or 0
    network_count   = await db.scalar(select(func.count(Network.id))) or 0
    mib_count       = await db.scalar(select(func.count(MIB.id))) or 0

    # Live running count via Docker status field
    result = await db.execute(select(Device))
    all_devices = result.scalars().all()
    from app.services import docker_service
    running = sum(
        1 for d in all_devices
        if docker_service.get_container_status(d.docker_container_id) == "running"
    )

    # SNMP query counter from Redis (written by agents via INCR device:{id}:snmp_queries)
    snmp_queries = 0
    try:
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        keys = await r.keys("device:*:snmp_queries")
        if keys:
            vals = await r.mget(*keys)
            snmp_queries = sum(int(v) for v in vals if v)
        await r.aclose()
    except Exception:
        pass

    return {
        "devices":         device_count,
        "devices_running": running,
        "networks":        network_count,
        "mibs":            mib_count,
        "snmp_queries":    snmp_queries,
    }


@app.get("/api/audit-log")
async def audit_log(limit: int = 20, db: AsyncSession = Depends(get_db)):
    """Recent audit log entries for the Dashboard activity feed."""
    result = await db.execute(
        select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    )
    entries = result.scalars().all()
    return [
        {
            "id":          e.id,
            "action":      e.action,
            "entity_type": e.entity_type,
            "entity_id":   e.entity_id,
            "payload":     e.payload,
            "created_at":  e.created_at.isoformat(),
        }
        for e in entries
    ]
