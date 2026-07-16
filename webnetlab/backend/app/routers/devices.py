import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.config import settings
from app.database import get_db
from app.models.audit import AuditLog
from app.models.device import Device
from app.models.mib import DeviceMIB
from app.models.network import Network
from app.models.oid_value import OIDValue
from app.schemas.device import BulkDeviceCreate, DeviceCreate, DeviceResponse, DeviceUpdate
from app.services import docker_service
from app.services import oid_push_service

router = APIRouter()


def _generate_mac() -> str:
    """Generate a locally-administered unicast MAC address."""
    rand = secrets.token_hex(5)  # 10 hex chars = 5 bytes
    parts = [rand[i : i + 2] for i in range(0, 10, 2)]
    return "02:" + ":".join(parts)


async def _get_device_or_404(device_id: int, db: AsyncSession) -> Device:
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return device


async def _start_container(device: Device) -> None:
    """Create and start the agent container for a device. Updates device in-place."""
    container_id = docker_service.create_device_container(
        device_id=device.id,
        ip=device.ip_address,
        mac=device.mac_address,
        community=device.snmp_community,
        docker_network_id=device.network.docker_network_id,
        redis_url=settings.REDIS_URL,
        snmp_port=device.snmp_port,
    )
    device.docker_container_id = container_id
    device.status = "running"
    device.updated_at = datetime.utcnow()


# ---------------------------------------------------------------------------
# POST /api/devices — create device + start agent container
# ---------------------------------------------------------------------------

@router.post("", response_model=DeviceResponse, status_code=status.HTTP_201_CREATED)
async def create_device(payload: DeviceCreate, db: AsyncSession = Depends(get_db)):
    # Validate network exists
    network = await db.get(Network, payload.network_id)
    if not network:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Network {payload.network_id} not found",
        )

    mac = payload.mac_address or _generate_mac()

    device = Device(
        name=payload.name,
        type=payload.type,
        ip_address=payload.ip_address,
        mac_address=mac,
        network_id=payload.network_id,
        snmp_community=payload.snmp_community,
        snmp_port=payload.snmp_port,
        status="stopped",
    )
    db.add(device)
    await db.flush()  # get device.id before container creation

    # Eager-load network for docker_network_id
    await db.refresh(device, attribute_names=["network"])

    try:
        await _start_container(device)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Container creation failed: {exc}",
        )

    # Push initial (empty) OIDs
    await oid_push_service.push_device_oids(device.id, db)

    db.add(AuditLog(
        action="create",
        entity_type="device",
        entity_id=device.id,
        payload={"name": device.name, "ip": device.ip_address},
    ))

    await db.commit()
    await db.refresh(device)
    return device


# ---------------------------------------------------------------------------
# GET /api/devices — list all devices with live Docker status
# ---------------------------------------------------------------------------

@router.get("", response_model=list[DeviceResponse])
async def list_devices(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Device).order_by(Device.id))
    devices = result.scalars().all()
    # Return live status without writing back to DB
    for device in devices:
        live = docker_service.get_container_status(device.docker_container_id)
        device.status = live
    return devices


# ---------------------------------------------------------------------------
# GET /api/devices/{id}
# ---------------------------------------------------------------------------

@router.get("/{device_id}", response_model=DeviceResponse)
async def get_device(device_id: int, db: AsyncSession = Depends(get_db)):
    device = await _get_device_or_404(device_id, db)
    device.status = docker_service.get_container_status(device.docker_container_id)
    return device


# ---------------------------------------------------------------------------
# PATCH /api/devices/{id} — update metadata
# ---------------------------------------------------------------------------

@router.patch("/{device_id}", response_model=DeviceResponse)
async def update_device(
    device_id: int, payload: DeviceUpdate, db: AsyncSession = Depends(get_db)
):
    device = await _get_device_or_404(device_id, db)
    if payload.name is not None:
        device.name = payload.name
    if payload.snmp_community is not None:
        device.snmp_community = payload.snmp_community
    if payload.snmp_port is not None:
        device.snmp_port = payload.snmp_port
    device.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(device)
    device.status = docker_service.get_container_status(device.docker_container_id)
    return device


# ---------------------------------------------------------------------------
# DELETE /api/devices/{id}
# ---------------------------------------------------------------------------

@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device(device_id: int, db: AsyncSession = Depends(get_db)):
    device = await _get_device_or_404(device_id, db)

    if device.docker_container_id:
        docker_service.stop_and_remove_container(device.docker_container_id)

    # Delete dependent records
    await db.execute(delete(OIDValue).where(OIDValue.device_id == device_id))
    await db.execute(delete(DeviceMIB).where(DeviceMIB.device_id == device_id))

    db.add(AuditLog(
        action="delete",
        entity_type="device",
        entity_id=device_id,
        payload={"name": device.name},
    ))

    await db.delete(device)
    await db.commit()


# ---------------------------------------------------------------------------
# POST /api/devices/{id}/start
# ---------------------------------------------------------------------------

@router.post("/{device_id}/start", response_model=DeviceResponse)
async def start_device(device_id: int, db: AsyncSession = Depends(get_db)):
    device = await _get_device_or_404(device_id, db)
    await db.refresh(device, attribute_names=["network"])

    try:
        await _start_container(device)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Container start failed: {exc}",
        )

    await oid_push_service.push_device_oids(device.id, db)
    await db.commit()
    await db.refresh(device)
    return device


# ---------------------------------------------------------------------------
# POST /api/devices/{id}/stop
# ---------------------------------------------------------------------------

@router.post("/{device_id}/stop", response_model=DeviceResponse)
async def stop_device(device_id: int, db: AsyncSession = Depends(get_db)):
    device = await _get_device_or_404(device_id, db)

    if device.docker_container_id:
        docker_service.stop_and_remove_container(device.docker_container_id)

    device.status = "stopped"
    device.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(device)
    return device


# ---------------------------------------------------------------------------
# POST /api/devices/{id}/restart
# ---------------------------------------------------------------------------

@router.post("/{device_id}/restart", response_model=DeviceResponse)
async def restart_device(device_id: int, db: AsyncSession = Depends(get_db)):
    device = await _get_device_or_404(device_id, db)
    await db.refresh(device, attribute_names=["network"])

    if device.docker_container_id:
        docker_service.stop_and_remove_container(device.docker_container_id)

    try:
        await _start_container(device)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Container restart failed: {exc}",
        )

    await oid_push_service.push_device_oids(device.id, db)
    await db.commit()
    await db.refresh(device)
    return device


# ---------------------------------------------------------------------------
# POST /api/devices/bulk — bulk create
# ---------------------------------------------------------------------------

@router.post("/bulk", response_model=list[DeviceResponse], status_code=status.HTTP_201_CREATED)
async def bulk_create_devices(payload: BulkDeviceCreate, db: AsyncSession = Depends(get_db)):
    created = []
    for device_payload in payload.devices:
        # Validate network
        network = await db.get(Network, device_payload.network_id)
        if not network:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Network {device_payload.network_id} not found",
            )

        mac = device_payload.mac_address or _generate_mac()
        device = Device(
            name=device_payload.name,
            type=device_payload.type,
            ip_address=device_payload.ip_address,
            mac_address=mac,
            network_id=device_payload.network_id,
            snmp_community=device_payload.snmp_community,
            snmp_port=device_payload.snmp_port,
            status="stopped",
        )
        db.add(device)
        await db.flush()
        await db.refresh(device, attribute_names=["network"])

        try:
            await _start_container(device)
        except Exception as exc:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Container creation failed for '{device_payload.name}': {exc}",
            )

        await oid_push_service.push_device_oids(device.id, db)

        db.add(AuditLog(
            action="create",
            entity_type="device",
            entity_id=device.id,
            payload={"name": device.name, "ip": device.ip_address},
        ))
        created.append(device)

    await db.commit()
    for device in created:
        await db.refresh(device)
    return created
