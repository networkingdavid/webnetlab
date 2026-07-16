"""
routers/topology.py — GET /api/topology, POST /api/topology/links, DELETE /api/topology/links/{id}
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.device import Device
from app.models.topology import TopologyLink
from app.schemas.topology import (
    TopologyLinkCreate,
    TopologyLinkResponse,
    TopologyNodeResponse,
    TopologyResponse,
)
from app.services import docker_service, topology_service

router = APIRouter()


# ---------------------------------------------------------------------------
# GET /api/topology
# ---------------------------------------------------------------------------

@router.get("", response_model=TopologyResponse)
async def get_topology(db: AsyncSession = Depends(get_db)):
    # Fetch all devices
    dev_result = await db.execute(select(Device).order_by(Device.id))
    devices = dev_result.scalars().all()

    nodes: list[TopologyNodeResponse] = []
    for device in devices:
        live_status = docker_service.get_container_status(device.docker_container_id)
        interfaces = await topology_service.get_device_interfaces(device.id, db)
        nodes.append(
            TopologyNodeResponse(
                id=device.id,
                name=device.name,
                type=device.type,
                ip_address=device.ip_address,
                status=live_status,
                interfaces=interfaces,
            )
        )

    # Fetch all topology links
    link_result = await db.execute(select(TopologyLink).order_by(TopologyLink.id))
    links = link_result.scalars().all()

    return TopologyResponse(
        nodes=nodes,
        links=[TopologyLinkResponse.model_validate(lnk) for lnk in links],
    )


# ---------------------------------------------------------------------------
# POST /api/topology/links
# ---------------------------------------------------------------------------

@router.post("/links", response_model=TopologyLinkResponse, status_code=status.HTTP_201_CREATED)
async def create_topology_link(
    payload: TopologyLinkCreate,
    db: AsyncSession = Depends(get_db),
):
    src_device = await db.get(Device, payload.src_device_id)
    if not src_device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source device {payload.src_device_id} not found",
        )

    dst_device = await db.get(Device, payload.dst_device_id)
    if not dst_device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Destination device {payload.dst_device_id} not found",
        )

    try:
        link = await topology_service.provision_link(
            src_device=src_device,
            src_iface=payload.src_interface,
            dst_device=dst_device,
            dst_iface=payload.dst_interface,
            db=db,
        )
    except Exception as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Link provisioning failed: {exc}",
        )

    await db.commit()
    await db.refresh(link)
    return TopologyLinkResponse.model_validate(link)


# ---------------------------------------------------------------------------
# DELETE /api/topology/links/{id}
# ---------------------------------------------------------------------------

@router.delete("/links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_topology_link(link_id: int, db: AsyncSession = Depends(get_db)):
    link = await db.get(TopologyLink, link_id)
    if not link:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Topology link {link_id} not found",
        )

    try:
        await topology_service.teardown_link(link_id, db)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Link teardown failed: {exc}",
        )

    await db.commit()
