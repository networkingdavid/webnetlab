import platform as _platform

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from alembic.config import Config
from alembic import command
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.models.device import Device
from app.models.network import Network
from app.routers import router as api_router

app = FastAPI(title="WebNetLab", version="0.1.0")

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
    return {"status": "ok", "version": "0.1.0"}


@app.get("/api/platform")
async def platform_info():
    """Returns host platform info so the UI can show relevant network-mode warnings.

    HOST_PLATFORM env var is set in docker-compose.yml to the actual host OS.
    Defaults to the container OS (Linux) if not set, which means macvlan is allowed
    only when explicitly running on a Linux host.
    """
    import os
    # HOST_PLATFORM is injected by docker-compose from the host shell ($HOST_PLATFORM or uname)
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
    device_count = await db.scalar(select(func.count(Device.id)))
    network_count = await db.scalar(select(func.count(Network.id)))
    return {"devices": device_count or 0, "networks": network_count or 0, "snmp_queries": 0}
