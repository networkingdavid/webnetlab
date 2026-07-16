"""
topology_service.py — Docker network wiring and interface OID sync for topology links.
"""

import json

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.models.device import Device
from app.models.topology import TopologyLink
from app.services import docker_service


# ---------------------------------------------------------------------------
# Subnet allocation
# ---------------------------------------------------------------------------

def _allocate_link_subnet(link_index: int) -> tuple[str, str, str, str]:
    """Return (subnet_cidr, gateway, ip1, ip2) for a /30 drawn from 172.20.0.0/16.

    Each /30 block: .0=network, .1=gateway, .2=container1, .3=container2
      index 0 → 172.20.0.0/30  gw=172.20.0.1  ip1=172.20.0.2  ip2=172.20.0.3 (broadcast .3 unused but /30 is fine)
    Use a /29 spacing (8 addresses) to leave room and avoid Docker IPAM conflicts.
      index 0 → 172.20.0.0/29   gw=172.20.0.1  ip1=172.20.0.2  ip2=172.20.0.3
      index 1 → 172.20.0.8/29   gw=172.20.0.9  ip1=172.20.0.10 ip2=172.20.0.11
    """
    base = link_index * 8
    third = (base >> 8) & 0xFF
    fourth = base & 0xFF
    subnet = f"172.20.{third}.{fourth}/29"
    gateway = f"172.20.{third}.{fourth + 1}"
    ip1 = f"172.20.{third}.{fourth + 2}"
    ip2 = f"172.20.{third}.{fourth + 3}"
    return subnet, gateway, ip1, ip2


# ---------------------------------------------------------------------------
# Default interface list for devices with no ifDescr OIDs
# ---------------------------------------------------------------------------

_DEFAULT_INTERFACES = ["eth0", "eth1", "eth2"]


async def get_device_interfaces(device_id: int, db: AsyncSession) -> list[str]:
    """Return interface names for a device.

    Looks for OIDValue records whose OID matches the ifDescr table prefix
    (1.3.6.1.2.1.2.2.1.2.*). Falls back to _DEFAULT_INTERFACES if none found.
    """
    from app.models.oid_value import OIDValue

    IFDESCR_PREFIX = "1.3.6.1.2.1.2.2.1.2."
    result = await db.execute(
        select(OIDValue)
        .where(OIDValue.device_id == device_id)
        .where(OIDValue.oid.like(f"{IFDESCR_PREFIX}%"))
        .order_by(OIDValue.oid)
    )
    oid_values = result.scalars().all()
    if not oid_values:
        return list(_DEFAULT_INTERFACES)

    interfaces = []
    for ov in oid_values:
        # Prefer walk_seed_value then static_value as the interface name
        name = ov.walk_seed_value or ov.static_value or ov.oid.split(".")[-1]
        interfaces.append(name)
    return interfaces


# ---------------------------------------------------------------------------
# provision_link
# ---------------------------------------------------------------------------

async def provision_link(
    src_device: Device,
    src_iface: str,
    dst_device: Device,
    dst_iface: str,
    db: AsyncSession,
) -> TopologyLink:
    """Create a Docker bridge network for the link, attach both containers,
    persist the TopologyLink record, and sync interface OIDs."""

    # Count existing links to allocate next /30 subnet
    existing_count_result = await db.execute(select(TopologyLink))
    link_index = len(existing_count_result.scalars().all())

    subnet, gateway, ip1, ip2 = _allocate_link_subnet(link_index)
    network_name = f"wnetlab-link-{src_device.id}-{dst_device.id}"

    docker_network_id = docker_service.create_docker_network(
        name=network_name,
        driver="bridge",
        subnet=subnet,
        gateway=gateway,
    )

    # Attach containers if they exist
    if src_device.docker_container_id:
        docker_service.attach_container_to_network(
            container_id=src_device.docker_container_id,
            docker_network_id=docker_network_id,
            ip=ip1,
        )
    if dst_device.docker_container_id:
        docker_service.attach_container_to_network(
            container_id=dst_device.docker_container_id,
            docker_network_id=docker_network_id,
            ip=ip2,
        )

    link = TopologyLink(
        src_device_id=src_device.id,
        src_interface=src_iface,
        dst_device_id=dst_device.id,
        dst_interface=dst_iface,
        docker_network_id=docker_network_id,
    )
    db.add(link)
    await db.flush()  # populate link.id

    await sync_interface_oids(src_device.id, db)
    await sync_interface_oids(dst_device.id, db)

    return link


# ---------------------------------------------------------------------------
# teardown_link
# ---------------------------------------------------------------------------

async def teardown_link(link_id: int, db: AsyncSession) -> None:
    """Detach containers, remove Docker network, delete the DB record."""
    link = await db.get(TopologyLink, link_id)
    if not link:
        return

    src_device = await db.get(Device, link.src_device_id)
    dst_device = await db.get(Device, link.dst_device_id)

    if link.docker_network_id:
        if src_device and src_device.docker_container_id:
            docker_service.detach_container_from_network(
                container_id=src_device.docker_container_id,
                docker_network_id=link.docker_network_id,
            )
        if dst_device and dst_device.docker_container_id:
            docker_service.detach_container_from_network(
                container_id=dst_device.docker_container_id,
                docker_network_id=link.docker_network_id,
            )
        docker_service.remove_docker_network(link.docker_network_id)

    await db.delete(link)
    await db.flush()

    if src_device:
        await sync_interface_oids(src_device.id, db)
    if dst_device:
        await sync_interface_oids(dst_device.id, db)


# ---------------------------------------------------------------------------
# sync_interface_oids
# ---------------------------------------------------------------------------

async def sync_interface_oids(device_id: int, db: AsyncSession) -> None:
    """Update ifAdminStatus and ifOperStatus OIDs in Redis for a device.

    For each interface that has an active link: status = 1 (up).
    For interfaces with no link: status = 2 (down).
    Interface index N is 1-based position in the device's interface list.
    """
    interfaces = await get_device_interfaces(device_id, db)

    # Collect all interfaces that are currently linked for this device
    result = await db.execute(
        select(TopologyLink).where(
            (TopologyLink.src_device_id == device_id) |
            (TopologyLink.dst_device_id == device_id)
        )
    )
    links = result.scalars().all()

    linked_ifaces: set[str] = set()
    for lnk in links:
        if lnk.src_device_id == device_id:
            linked_ifaces.add(lnk.src_interface)
        else:
            linked_ifaces.add(lnk.dst_interface)

    r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        oid_hash_key = f"device:{device_id}:oids"
        pipe = r.pipeline()
        for idx, iface in enumerate(interfaces, start=1):
            status = 1 if iface in linked_ifaces else 2
            # ifAdminStatus: 1.3.6.1.2.1.2.2.1.7.N
            admin_oid = f"1.3.6.1.2.1.2.2.1.7.{idx}"
            # ifOperStatus:  1.3.6.1.2.1.2.2.1.8.N
            oper_oid = f"1.3.6.1.2.1.2.2.1.8.{idx}"
            payload = json.dumps({"mode": "static", "value": str(status)})
            pipe.hset(oid_hash_key, admin_oid, payload)
            pipe.hset(oid_hash_key, oper_oid, payload)
        await pipe.execute()
    finally:
        await r.aclose()
