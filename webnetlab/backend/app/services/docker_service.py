"""
docker_service.py — Docker SDK helpers for WebNetLab.

Networking modes supported
--------------------------
bridge / host-bridge  All platforms.
  Containers get IPs on an isolated Docker bridge. On macOS Docker Desktop
  the host automatically routes container subnets, so the NMS can reach
  devices directly. On Linux the bridge is also routable from the host.

macvlan               Linux only.
  Containers each get a unique MAC address and appear as real devices on the
  physical LAN. The NMS and any host on the network can reach them by IP.
  Requires: promiscuous mode on the parent NIC, a /proc/net/... capable kernel.
  NOT supported on macOS Docker Desktop (runs inside a VM).

ipvlan (L2)           Linux only.
  Like macvlan but containers share the host MAC. Works on hypervisors that
  block MAC spoofing (AWS, GCP, some VMware). Also not supported on macOS.

Device port-mapping (macOS workaround)
  When snmp_port is set on a device, the agent binds 0.0.0.0:161 and the
  host publishes snmp_port → 161/udp. The NMS queries <host-ip>:<snmp_port>.
  Not needed on Linux where macvlan gives each container a real LAN IP.
"""

import docker
import docker.errors
from docker.types import IPAMConfig, IPAMPool

from app.config import settings

AGENT_IMAGE = "webnetlab-agent:latest"

# Drivers that expose containers on the physical LAN (Linux only)
LAN_DRIVERS = {"macvlan", "ipvlan"}


def get_docker_client() -> docker.DockerClient:
    return docker.DockerClient(base_url=settings.DOCKER_SOCKET)


def create_docker_network(
    name: str,
    driver: str,
    subnet: str,
    gateway: str,
    options: dict | None = None,
) -> str:
    """Create a Docker network with IPAM config. Returns the docker network ID.
    If a network with the same name already exists, returns its ID.

    options examples:
      macvlan: {"parent": "eth0"}
      ipvlan:  {"parent": "eth0", "ipvlan_mode": "l2"}
    """
    client = get_docker_client()
    try:
        existing = client.networks.get(name)
        return existing.id
    except docker.errors.NotFound:
        pass

    ipam_pool   = IPAMPool(subnet=subnet, gateway=gateway)
    ipam_config = IPAMConfig(driver="default", pool_configs=[ipam_pool])

    network = client.networks.create(
        name=name,
        driver=driver,
        ipam=ipam_config,
        options=options or {},
        check_duplicate=True,
    )
    return network.id


def remove_docker_network(docker_network_id: str) -> None:
    """Remove a Docker network by ID. Silently ignores if not found."""
    client = get_docker_client()
    try:
        network = client.networks.get(docker_network_id)
        network.remove()
    except docker.errors.NotFound:
        pass


def create_device_container(
    device_id: int,
    ip: str,
    mac: str,
    community: str,
    docker_network_id: str,
    redis_url: str,
    snmp_port: int | None = None,
) -> str:
    """Start a webnetlab-agent container for the device. Returns the container ID.

    Networking behaviour
    --------------------
    macvlan / ipvlan networks (Linux LAN mode):
      The container gets a real IP on the physical LAN.  snmp_port is ignored —
      the NMS queries the container IP directly on UDP 161.
      LISTEN_IP is set to 0.0.0.0 so the agent accepts on all interfaces.

    bridge / host-bridge networks (all platforms):
      If snmp_port is set → bind 0.0.0.0:161 + publish host:snmp_port→161/udp.
      If snmp_port is None → bind the container IP directly (Linux bridge).
    """
    client = get_docker_client()
    container_name = f"webnetlab-device-{device_id}"

    # Remove existing container with the same name
    try:
        existing = client.containers.get(container_name)
        try:
            existing.stop(timeout=5)
        except Exception:
            pass
        existing.remove(force=True)
    except docker.errors.NotFound:
        pass

    # Detect whether this is a LAN-mode network (macvlan / ipvlan)
    is_lan_mode = False
    try:
        net_info = client.networks.get(docker_network_id)
        is_lan_mode = net_info.attrs.get("Driver", "") in LAN_DRIVERS
    except Exception:
        pass

    endpoint_config = client.api.create_endpoint_config(
        ipv4_address=ip,
        mac_address=mac,
    )
    networking_config = client.api.create_networking_config(
        {docker_network_id: endpoint_config}
    )

    # Port-mapping: only for bridge mode when snmp_port is specified
    port_bindings: dict = {}
    port_specs: list = []
    if snmp_port and not is_lan_mode:
        port_bindings = {"161/udp": [{"HostIp": "0.0.0.0", "HostPort": str(snmp_port)}]}
        port_specs    = ["161/udp"]

    # On LAN-mode networks the agent must listen on 0.0.0.0 (not the container IP)
    # because the macvlan/ipvlan interface has its own IP that the agent sees as
    # "any interface". The IP is already fixed at the Docker IPAM level.
    listen_ip = "0.0.0.0" if (is_lan_mode or snmp_port) else ip

    container_resp = client.api.create_container(
        image=AGENT_IMAGE,
        name=container_name,
        environment={
            "DEVICE_ID":       str(device_id),
            "SNMP_COMMUNITY":  community,
            "REDIS_URL":       redis_url,
            "LISTEN_IP":       listen_ip,
            "LISTEN_PORT":     "161",
        },
        ports=port_specs or None,
        host_config=client.api.create_host_config(
            cap_add=["NET_ADMIN"],
            network_mode=docker_network_id,
            port_bindings=port_bindings or None,
        ),
        networking_config=networking_config,
    )
    container_id = container_resp["Id"]
    client.api.start(container_id)

    # Also attach to webnetlab-internal so the agent can reach Redis and the backend.
    # LAN-mode containers still need this internal network for the Redis pubsub channel.
    # Docker Compose prefixes network names with the project folder name.
    for net_name in ("webnetlab_webnetlab-internal", "webnetlab-internal"):
        try:
            internal_net = client.networks.get(net_name)
            internal_net.connect(container_id)
            break
        except docker.errors.NotFound:
            continue

    return container_id


def stop_and_remove_container(container_id: str) -> None:
    """Stop and remove a container by ID. Silently ignores if not found."""
    client = get_docker_client()
    try:
        container = client.containers.get(container_id)
        try:
            container.stop(timeout=5)
        except Exception:
            pass
        container.remove(force=True)
    except docker.errors.NotFound:
        pass


def get_container_status(container_id: str) -> str:
    """Return normalised container status: running | stopped | error | unknown."""
    if not container_id:
        return "unknown"
    client = get_docker_client()
    try:
        container = client.containers.get(container_id)
        status = container.status
        if status == "running":
            return "running"
        elif status in ("exited", "created", "dead"):
            return "stopped"
        else:
            return "error"
    except docker.errors.NotFound:
        return "stopped"
    except Exception:
        return "error"


def attach_container_to_network(
    container_id: str, docker_network_id: str, ip: str
) -> None:
    """Attach a running container to an additional network with a static IP."""
    client = get_docker_client()
    network = client.networks.get(docker_network_id)
    network.connect(container_id, ipv4_address=ip)


def detach_container_from_network(
    container_id: str, docker_network_id: str
) -> None:
    """Detach a container from a network. Silently ignores if not attached."""
    client = get_docker_client()
    try:
        network = client.networks.get(docker_network_id)
        network.disconnect(container_id)
    except docker.errors.NotFound:
        pass
    except docker.errors.APIError:
        pass


def list_host_interfaces() -> list[dict]:
    """Return a list of host network interfaces suitable for macvlan/ipvlan parents.

    Reads /proc/net/dev (available on Linux only). Returns an empty list on macOS.
    Each entry: {"name": "eth0", "rx_bytes": 1234, "tx_bytes": 5678}
    """
    try:
        interfaces = []
        with open("/proc/net/dev") as f:
            lines = f.readlines()[2:]  # skip header rows
        for line in lines:
            parts = line.split(":")
            if len(parts) < 2:
                continue
            name   = parts[0].strip()
            fields = parts[1].split()
            if name in ("lo",):
                continue  # skip loopback
            interfaces.append({
                "name":     name,
                "rx_bytes": int(fields[0]) if fields else 0,
                "tx_bytes": int(fields[8]) if len(fields) > 8 else 0,
            })
        return interfaces
    except Exception:
        return []
