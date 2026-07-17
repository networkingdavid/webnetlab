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


# ---------------------------------------------------------------------------
# Interface name prefixes that are NEVER valid macvlan/ipvlan parents
# ---------------------------------------------------------------------------
_VIRTUAL_PREFIXES = (
    "lo",             # loopback
    "veth",           # Docker veth pairs
    "br-",            # Docker bridge interfaces
    "docker",         # docker0, docker_gwbridge, etc.
    "virbr",          # libvirt bridge
    "vmbr",           # Proxmox bridge
    "dummy",          # dummy interfaces
    "tunl",           # IP-in-IP tunnel
    "gre",            # GRE tunnel (gre0, gretap0)
    "erspan",         # ERSPAN
    "ip_vti",         # VTI tunnels
    "ip6_vti",
    "sit",            # SIT IPv6-in-IPv4 tunnel
    "ip6tnl",         # IPv6 tunnel
    "ip6gre",         # IPv6 GRE tunnel
    "teql",           # traffic equalizer
    "ifb",            # intermediate functional block
    "ovs-system",     # Open vSwitch internal
    "flannel",        # Kubernetes CNI
    "cali",           # Calico CNI
    "cni",            # CNI generic
    "weave",          # Weave CNI
    "kube",           # Kubernetes
    "bonding_master", # /sys/class/net/bonding_masters is a file, not an interface
)

# Additional exact-name exclusions (not prefix-matched)
_VIRTUAL_EXACT = {"bonding_masters", "lo"}


def _is_virtual_iface(name: str) -> bool:
    """Return True if this interface should be excluded from macvlan parent candidates."""
    if name in _VIRTUAL_EXACT:
        return True
    nl = name.lower()
    return any(nl.startswith(p) for p in _VIRTUAL_PREFIXES)


def list_host_interfaces() -> list[dict]:
    """Return a list of host physical network interfaces suitable for macvlan/ipvlan parents.

    Probe strategy (tried in order, first success wins):

    1. Docker exec probe  — run a tiny privileged container in the host network
       namespace. Executes `ip -j link show` + `ip -j addr show` inside the
       host's net namespace via Docker SDK.  This is the most accurate source
       and works on both native Linux and Docker Desktop (macOS/Windows).

    2. /host/proc/net/dev bind-mount  — reads the host /proc/net tree that is
       bind-mounted read-only at /host/proc/net in docker-compose.yml.
       Provides interface names and traffic counters.  Enriched with IP data
       from /host/proc/net/arp + /host/proc/net/route + /host/proc/net/fib_trie.

    3. Container /proc/net/dev fallback  — last resort, reads the container's
       own /proc/net/dev.  Heavily filtered to remove Docker veth/br-* junk.

    Each returned entry:
      {
        "name":       "eth0",
        "mac":        "52:54:00:ab:cd:ef",   # "" if unknown
        "state":      "up" | "down" | "unknown",
        "speed_mbps": 1000,                  # 0 if unknown
        "ip":         "192.168.1.5",         # primary IPv4, "" if unknown
        "rx_bytes":   12345678,
        "tx_bytes":   87654321,
      }

    Interfaces are returned sorted: UP first, then alphabetical by name.
    Virtual/tunnel/docker interfaces are always excluded.
    """
    # ── Strategy 1: Docker exec probe (most accurate) ──────────────────────────
    try:
        result = _probe_interfaces_via_docker()
        if result:
            return result
    except Exception:
        pass

    # ── Strategy 2: /host/proc/net bind-mount ─────────────────────────────────
    try:
        result = _probe_interfaces_via_proc("/host/proc")
        if result:
            return result
    except Exception:
        pass

    # ── Strategy 3: container's own /proc (filtered) ─────────────────────────
    try:
        return _probe_interfaces_via_proc("/proc")
    except Exception:
        return []


# Shell script run inside a host-network container to gather interface data.
# Reads /proc/net/dev, /proc/net/arp, /proc/net/fib_trie, /proc/net/route, and
# /sys/class/net/{iface}/address + operstate — all available from a host-network container.
_PROBE_SCRIPT = r"""
import sys, os, re, struct, socket

def read(path):
    try:
        return open(path).read()
    except:
        return ""

# ── /proc/net/dev  ─────────────────────────────────────────────────────────────
dev_raw = {}
for line in read("/proc/net/dev").splitlines()[2:]:
    parts = line.split(":")
    if len(parts) < 2:
        continue
    name = parts[0].strip()
    fields = parts[1].split()
    dev_raw[name] = (int(fields[0]) if fields else 0,
                     int(fields[8]) if len(fields) > 8 else 0)

# ── /sys/class/net/{iface}/{attr}  ─────────────────────────────────────────────
def sysattr(iface, attr):
    return read(f"/sys/class/net/{iface}/{attr}").strip()

# ── /proc/net/arp  ─────────────────────────────────────────────────────────────
arp_map = {}  # iface -> ip
for line in read("/proc/net/arp").splitlines()[1:]:
    p = line.split()
    if len(p) >= 6 and p[2] not in ("0x0","0x00"):
        arp_map.setdefault(p[5], p[0])

# ── /proc/net/route → iface subnets  ──────────────────────────────────────────
iface_nets = {}  # iface -> [(net_int, mask_int)]
for line in read("/proc/net/route").splitlines()[1:]:
    p = line.split()
    if len(p) < 8:
        continue
    try:
        dest = struct.unpack("<I", bytes.fromhex(p[1]))[0]
        mask = struct.unpack("<I", bytes.fromhex(p[7]))[0]
        iface_nets.setdefault(p[0], []).append((dest & mask, mask))
    except:
        pass

# ── /proc/net/fib_trie LOCAL /32 addresses  ──────────────────────────────────
ip_candidates = []
lines = read("/proc/net/fib_trie").splitlines()
for i, line in enumerate(lines):
    m = re.search(r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b', line.strip())
    if not m:
        continue
    window = "\n".join(lines[i+1:i+5])
    if "/32 host LOCAL" in window:
        ip_candidates.append(m.group(1))

def find_ip(iface):
    if iface in arp_map:
        return arp_map[iface]
    nets = iface_nets.get(iface, [])
    if not nets:
        return ""
    for ip_str in ip_candidates:
        try:
            ip_int = struct.unpack(">I", socket.inet_aton(ip_str))[0]
        except:
            continue
        if (ip_int >> 24) in (127, 169):
            continue
        for net, mask in nets:
            if (ip_int & mask) == net:
                return ip_str
    return ""

# ── Output  ───────────────────────────────────────────────────────────────────
import json

VIRTUAL = ("lo","veth","br-","docker","virbr","vmbr","dummy","tunl","gre","gretap",
           "erspan","ip_vti","ip6_vti","sit","ip6tnl","ip6gre","teql","ifb",
           "ovs-system","flannel","cali","cni","weave","kube","bonding_master",
           "services")
EXACT   = {"bonding_masters", "lo"}

def is_virtual(name):
    if name in EXACT:
        return True
    nl = name.lower()
    return any(nl.startswith(p) for p in VIRTUAL)

results = []
for name, (rx, tx) in dev_raw.items():
    if is_virtual(name):
        continue
    mac   = sysattr(name, "address")
    state = sysattr(name, "operstate") or "unknown"
    try:
        speed_v = int(sysattr(name, "speed"))
        speed   = speed_v if speed_v > 0 else 0
    except:
        speed = 0
    ip = find_ip(name)
    results.append({"name":name,"mac":mac,"state":state,"speed_mbps":speed,
                    "ip":ip,"rx_bytes":rx,"tx_bytes":tx})

results.sort(key=lambda x:(0 if x["state"]=="up" else 1, x["name"]))
print(json.dumps(results))
"""


def _probe_interfaces_via_docker() -> list[dict]:
    """Run a tiny host-network container that reads the host's /proc and /sys directly.

    The container uses --network=host which places it in the host's network
    namespace — so /proc/net/dev, /sys/class/net/* etc. all show real host NICs.
    Uses webnetlab-agent (always present locally) which has Python 3.11.

    Returns [] on any error so the caller falls back to the /host/proc mount.
    """
    import json as _json

    client = get_docker_client()

    # Prefer our own agent image (always present); fall back to python:3.11-slim
    for image in (AGENT_IMAGE, "python:3.11-slim"):
        try:
            output = client.containers.run(
                image=image,
                command=["python3", "-c", _PROBE_SCRIPT],
                network_mode="host",
                remove=True,
                detach=False,
                stdout=True,
                stderr=False,
            )
            if not output:
                continue
            data = _json.loads(output.decode("utf-8", errors="replace").strip())
            if isinstance(data, list) and data:
                return data
        except Exception:
            continue

    return []


def _probe_interfaces_via_proc(proc_root: str) -> list[dict]:
    """Read interface data from /proc/net/dev (and enrich with ARP/route/fib_trie).

    Works for both /host/proc (bind-mounted host) and /proc (container's own).
    """
    import os

    dev_path = f"{proc_root}/net/dev"
    raw: dict[str, dict] = {}

    try:
        with open(dev_path) as f:
            lines = f.readlines()[2:]  # skip 2 header lines
        for line in lines:
            parts = line.split(":")
            if len(parts) < 2:
                continue
            name = parts[0].strip()
            fields = parts[1].split()
            raw[name] = {
                "rx_bytes": int(fields[0]) if fields else 0,
                "tx_bytes": int(fields[8]) if len(fields) > 8 else 0,
            }
    except Exception:
        return []

    interfaces = []
    for name, counters in sorted(raw.items()):
        if _is_virtual_iface(name):
            continue

        ip = _get_interface_ip_proc(proc_root, name)

        interfaces.append({
            "name":       name,
            "mac":        "",        # not available from /proc/net/dev
            "state":      "unknown", # not available from /proc/net/dev
            "speed_mbps": 0,
            "ip":         ip,
            "rx_bytes":   counters["rx_bytes"],
            "tx_bytes":   counters["tx_bytes"],
        })

    interfaces.sort(key=lambda x: (0 if x["state"] == "up" else 1, x["name"]))
    return interfaces


def _get_interface_ip_proc(proc_root: str, iface: str) -> str:
    """Return the primary IPv4 address of *iface* by reading /proc files under *proc_root*.

    Uses /proc/net/arp (fast path) and /proc/net/route + /proc/net/fib_trie (reliable path).
    """
    return _parse_ifaddr(proc_root, iface)


def _parse_ifaddr(proc_root: str, iface: str) -> str:
    """Parse /proc/net files to find the primary IPv4 address for *iface*.

    Two methods, tried in order:
      1. /proc/net/arp       — fast, works when the interface has active ARP entries
      2. /proc/net/route     — find subnets for iface, then cross-reference
                               /proc/net/fib_trie LOCAL /32 entries
    """
    import os, struct, socket as _socket

    fib_path   = f"{proc_root}/net/fib_trie"
    route_path = f"{proc_root}/net/route"
    arp_path   = f"{proc_root}/net/arp"

    # ── Method 1: /proc/net/arp (fast, works when there's been any traffic) ────
    try:
        with open(arp_path) as f:
            for line in f.readlines()[1:]:
                parts = line.split()
                # IP  HW_type  Flags  HW_addr  Mask  Device
                if len(parts) >= 6 and parts[5] == iface and parts[2] not in ("0x0", "0x00"):
                    return parts[0]
    except Exception:
        pass

    # ── Method 2: /proc/net/route → derive interface subnet → fib_trie LOCAL ──
    # Step 2a: find subnets assigned to this interface from the routing table
    iface_subnets: list[tuple[int, int]] = []  # (network_int, mask_int)
    try:
        with open(route_path) as f:
            for line in f.readlines()[1:]:
                parts = line.split()
                # Iface Destination Gateway Flags RefCnt Use Metric Mask ...
                if len(parts) < 8 or parts[0] != iface:
                    continue
                dest_hex = parts[1]
                mask_hex = parts[7]
                # These are little-endian hex — e.g. "0101A8C0" = 192.168.1.1
                dest = struct.unpack("<I", bytes.fromhex(dest_hex))[0]
                mask = struct.unpack("<I", bytes.fromhex(mask_hex))[0]
                iface_subnets.append((dest & mask, mask))
    except Exception:
        pass

    if not iface_subnets:
        return ""

    # Step 2b: parse fib_trie to find LOCAL /32 host addresses
    try:
        with open(fib_path) as f:
            content = f.read()
    except Exception:
        return ""

    # Find all LOCAL /32 addresses: look for pattern:
    #   |-- X.X.X.X
    # followed (within a few lines) by:   /32 host LOCAL
    import re
    # Split into blocks per IP address entry
    # Regex: capture IP address, then check if subsequent lines contain "/32 host LOCAL"
    ip_candidates: list[str] = []
    lines = content.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        # IP address lines look like:   |-- 192.168.1.10   or   +-- 192.168.1.10/32
        m = re.search(r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b', stripped)
        if not m:
            continue
        candidate_ip = m.group(1)
        # Look ahead up to 4 lines for "/32 host LOCAL"
        window = "\n".join(lines[i+1 : i+5])
        if "/32 host LOCAL" in window:
            ip_candidates.append(candidate_ip)

    # Step 2c: match candidates against interface subnets
    for ip_str in ip_candidates:
        try:
            ip_int = struct.unpack(">I", _socket.inet_aton(ip_str))[0]
        except Exception:
            continue
        # Skip link-local (169.254.x.x) and loopback (127.x.x.x)
        if (ip_int >> 24) in (127, 169):
            continue
        for net, mask in iface_subnets:
            if (ip_int & mask) == net:
                return ip_str

    return ""
