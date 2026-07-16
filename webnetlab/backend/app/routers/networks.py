"""
routers/networks.py — Network management API.

Network types
-------------
bridge       Docker bridge, all platforms. Isolated from physical LAN.
host-bridge  Same Docker bridge driver; signals NMS-accessible intent.
             macOS Docker Desktop auto-routes container subnets to the host.
macvlan      Linux only. Containers get unique MACs / IPs on the physical LAN.
             Requires: Linux host, promiscuous mode on parent NIC.
ipvlan       Linux only. Containers share host MAC, unique IPs on physical LAN.
             Works on hypervisors that block MAC spoofing.
"""

import platform

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.database import get_db
from app.models.network import Network
from app.schemas.network import NetworkCreate, NetworkResponse
from app.services import docker_service

router = APIRouter()

# ─── Driver mapping ───────────────────────────────────────────────────────────

_DRIVER_MAP: dict[str, str] = {
    "bridge":      "bridge",
    "host-bridge": "bridge",
    "macvlan":     "macvlan",
    "ipvlan":      "ipvlan",
}

_LAN_TYPES = {"macvlan", "ipvlan"}

_LAN_REQUIRES_LINUX = (
    "{type} networks require a Linux host with a physical NIC (e.g. eth0). "
    "Docker Desktop on macOS runs containers inside a VM and cannot bridge "
    "to the physical network. Use 'host-bridge' instead — Docker Desktop "
    "automatically routes container subnets to your Mac so your NMS can "
    "reach simulated devices directly."
)


def _is_linux() -> bool:
    """Return True when running on a real Linux host (not macOS Docker Desktop).
    Checks HOST_PLATFORM env var first (set in docker-compose), then os.uname."""
    host_platform = settings.HOST_PLATFORM
    if host_platform:
        return host_platform.lower() == "linux"
    return platform.system() == "Linux"


@router.post("", response_model=NetworkResponse, status_code=status.HTTP_201_CREATED)
async def create_network(
    payload: NetworkCreate, db: AsyncSession = Depends(get_db)
):
    # LAN modes (macvlan, ipvlan) require Linux
    if payload.type in _LAN_TYPES and not _is_linux():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_LAN_REQUIRES_LINUX.format(type=payload.type),
        )

    driver = _DRIVER_MAP.get(payload.type)
    if driver is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown network type '{payload.type}'. Valid: bridge, host-bridge, macvlan, ipvlan",
        )

    # LAN modes require a parent host interface
    options: dict = {}
    if payload.type in _LAN_TYPES:
        if not payload.host_interface:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{payload.type} networks require host_interface (e.g. 'eth0', 'ens3')",
            )
        options = {"parent": payload.host_interface}
        if payload.type == "ipvlan":
            options["ipvlan_mode"] = "l2"

    try:
        docker_network_id = docker_service.create_docker_network(
            name=payload.name,
            driver=driver,
            subnet=payload.subnet,
            gateway=payload.gateway,
            options=options,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Docker network creation failed: {exc}",
        )

    network = Network(
        name=payload.name,
        type=payload.type,
        docker_network_id=docker_network_id,
        subnet=payload.subnet,
        gateway=payload.gateway,
        host_interface=payload.host_interface,
    )
    db.add(network)
    await db.commit()
    await db.refresh(network)
    return network


@router.get("", response_model=list[NetworkResponse])
async def list_networks(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Network).order_by(Network.id))
    return result.scalars().all()


@router.get("/interfaces")
async def list_host_interfaces():
    """Return physical network interfaces available for macvlan/ipvlan parent.

    Linux only — returns empty list on macOS/Windows.
    Used by the frontend to populate the parent NIC dropdown.
    """
    return {"interfaces": docker_service.list_host_interfaces()}


@router.get("/{network_id}", response_model=NetworkResponse)
async def get_network(network_id: int, db: AsyncSession = Depends(get_db)):
    network = await db.get(Network, network_id)
    if not network:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Network not found")
    return network


@router.delete("/{network_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_network(network_id: int, db: AsyncSession = Depends(get_db)):
    network = await db.get(Network, network_id)
    if not network:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Network not found")

    from app.models.device import Device
    devices_result = await db.execute(
        select(Device).where(Device.network_id == network_id)
    )
    if devices_result.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete network: devices are still attached",
        )

    if network.docker_network_id:
        docker_service.remove_docker_network(network.docker_network_id)

    await db.delete(network)
    await db.commit()
