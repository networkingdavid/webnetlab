# WebNetLab

**WebNetLab** is a web-based SNMPv2c network device simulator. It lets you build a virtual network of routers and switches that respond to real SNMP queries — exactly as a live device would — without touching any physical hardware.

Any third-party NMS (SolarWinds, PRTG, LibreNMS, Zabbix, Nagios, custom scripts) sees each simulated device as a genuine network element.

---

## Key features

| Feature | Description |
|---|---|
| **SNMPv2c agent** | GET, GETNEXT, GETBULK — V1 and V3 silently dropped |
| **MIB import** | Upload any MIB file; the OID tree is immediately queryable |
| **snmpwalk seed** | Paste or upload snmpwalk output to populate a device in seconds |
| **OID value modes** | Static, Random (min/max), Scripted (Python eval), Walk-seed |
| **Topology canvas** | Drag-and-drop interface-level links wired as real Docker networks |
| **3 000+ OIDs** | Numerically-sorted MIB store; full walk in < 2 ms |
| **macOS** | Host-accessible bridge — Docker Desktop routes subnets to your Mac |
| **Linux LAN** | macvlan / ipvlan — containers appear on physical LAN with real IPs |

---

## Quick start

### Prerequisites

| | macOS | Linux |
|---|---|---|
| Docker Desktop / Engine | [Download](https://www.docker.com/products/docker-desktop/) | `apt install docker.io docker-compose-plugin` |
| Minimum Docker version | 4.x (Desktop) | 20.10+ (Engine) |
| Ports needed | 5173, 8000, 5432, 6379 | same |

### 1 — Clone

```bash
git clone https://github.com/your-org/webnetlab.git
cd webnetlab
```

### 2 — Configure environment

```bash
# macOS
cp webnetlab/.env.example webnetlab/.env
# .env already has HOST_PLATFORM=Darwin — no change needed

# Linux
cp webnetlab/.env.example webnetlab/.env
sed -i 's/HOST_PLATFORM=Darwin/HOST_PLATFORM=Linux/' webnetlab/.env
```

### 3 — Build and start

```bash
cd webnetlab

# Build the SNMP agent image (required before first run)
docker compose --profile build-only build agent-builder

# Build and start everything
docker compose build
docker compose up -d
```

First startup takes ~2 minutes (downloading base images, installing dependencies).

### 4 — Apply database migrations

```bash
docker compose exec backend alembic upgrade head
```

### 5 — Open the UI

```
http://localhost:5173
```

API docs (OpenAPI): `http://localhost:8000/docs`

---

## Load the Sacramento demo lab

A pre-built fixture seeds 5 Cisco devices with real snmpwalk data and 6 CDP-verified topology links:

```bash
docker compose exec backend python seeds/sacramento_import.py
```

Devices appear at `192.168.200.10–14` on the `sac-lab` Docker network.

Test from any container on that network:
```bash
docker run --rm --network sac-lab alpine sh -c \
  "apk add -q net-snmp-tools && snmpget -v2c -c public 192.168.200.10 1.3.6.1.2.1.1.5.0"
# SNMPv2-MIB::sysName.0 = STRING: Sac-WAN-1
```

---

## Networking modes

### macOS — Host-accessible Bridge (recommended)

Create networks with type **Host-accessible Bridge** in the UI.
Docker Desktop automatically routes the container subnet to your Mac, so your NMS can query devices by container IP (e.g. `192.168.x.x`) without any port mapping.

### macOS — Port mapping (alternative)

Set an `snmp_port` on a device (e.g. `10161`). Your NMS queries `localhost:10161`, which maps to the container's UDP 161.

### Linux — macvlan LAN mode

Containers appear on your **physical LAN** with unique MAC + IP addresses. Any device on the network can reach them.

```bash
# One-time setup (enables promiscuous mode + host shim)
sudo bash webnetlab/infra/linux-macvlan-setup.sh

# Then in the UI: Networks → New → Macvlan — LAN (Linux)
# Specify your parent NIC (e.g. eth0) and your LAN subnet
```

See [`docs/linux-lan-mode.md`](webnetlab/docs/linux-lan-mode.md) for full details including ipvlan (for cloud VMs) and persistence configuration.

---

## Seeding a device from snmpwalk output

1. Run snmpwalk on a real (or GNS3/EVE-NG) device:
   ```bash
   snmpwalk -v2c -c public 192.168.1.1 1.3.6.1 > router1.txt
   ```
2. In WebNetLab: **Devices** → select device → **Seed Import** tab → upload `router1.txt`
3. Click **Preview** to verify, then **Import**

WebNetLab resolves 250+ standard MIB names (IF-MIB, IP-MIB, ENTITY-MIB, CISCO-PROCESS-MIB, etc.) to numeric OIDs automatically.

---

## Updating after code changes

```bash
cd webnetlab
docker compose build backend frontend
docker compose up -d backend frontend
```

For agent changes:
```bash
docker build -t webnetlab-agent:latest ./agent
# Restart devices via the UI or:
curl -X POST http://localhost:8000/api/devices/{id}/start
```

---

## Stopping and cleaning up

```bash
# Stop containers (preserve data)
docker compose down

# Stop and delete all data (DB, Redis)
docker compose down -v
```

---

## Troubleshooting

### Containers won't start

```bash
docker compose logs backend
docker compose logs frontend
```

### Device container crashed

```bash
docker logs webnetlab-device-{id}
```

Common causes:
- Non-numeric OID key in Redis (filtered automatically since v1.0)
- Port conflict: another process using the device's `snmp_port`

### snmpwalk returns too few OIDs

Verify the agent loaded OIDs:
```bash
docker logs webnetlab-device-{id} | grep "loaded"
# device 1: loaded 3057 OIDs.
```

If it shows 0, push OIDs manually:
```bash
curl -X POST http://localhost:8000/api/devices/{id}/start
```

### macvlan fails on Linux

```bash
# Check promiscuous mode
ip link show eth0 | grep PROMISC

# Re-run setup
sudo bash webnetlab/infra/linux-macvlan-setup.sh eth0
```

See [`docs/linux-lan-mode.md`](webnetlab/docs/linux-lan-mode.md#troubleshooting) for a full troubleshooting table.

---

## Project structure

```
webnetlab/
├── backend/      FastAPI + SQLAlchemy (Python 3.11)
├── agent/        SNMP agent container (pysnmp 4.4.12)
├── frontend/     React + TypeScript + React Flow
├── infra/        linux-macvlan-setup.sh
├── seeds/        Sacramento demo fixture
├── mibs/         MIB file volume (user uploads)
└── docs/         Extended guides
    └── linux-lan-mode.md

README.md         This file
CHANGELOG.md      Version history
CONTRIBUTING.md   Development guide
```

---

## Version

**v1.0.0** — see [CHANGELOG.md](CHANGELOG.md) for full release notes.

---

## License

MIT
