# Changelog

All notable changes to WebNetLab are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
WebNetLab uses [Semantic Versioning](https://semver.org/).

---

## [1.0.0] — 2024-07-17

First public release of WebNetLab — a web-based SNMPv2c network device simulator.

### Added

#### Core simulator
- **SNMP agent** (pysnmp 4.4.12, SNMPv2c only) — GET, GETNEXT, GETBULK support
- Each simulated device runs in its own Docker container with a static IP and MAC
- **MIB import** — upload any MIB file to populate the OID tree for a device
- **snmpwalk seed import** — paste or upload snmpwalk text to seed a device's OIDs instantly; auto-detects symbolic names for 250+ IETF/Cisco MIB objects
- **JSON export/import** — export all OID configs from one device and import to another
- OID value modes: `static`, `random` (with min/max/type config), `scripted` (eval), `walk_seed`
- Per-OID value type: `string`, `integer`, `counter`, `gauge`, `timeticks`, `ipaddress`
- Bulk OID update endpoint (`POST /api/devices/{id}/oids/bulk`)

#### Networking
- **Docker bridge** — isolated per-device networks on all platforms
- **Host-accessible bridge** — macOS Docker Desktop auto-routes container subnets
- **macvlan (Linux)** — containers appear on physical LAN with unique MACs
- **ipvlan L2 (Linux)** — containers on physical LAN sharing host MAC (cloud-VM friendly)
- **Port mapping** — macOS workaround: NMS queries `<host>:<snmp_port>` instead of container IP
- `infra/linux-macvlan-setup.sh` — one-script setup for promiscuous mode + host shim

#### Topology
- Visual drag-and-drop topology canvas (React Flow)
- Interface-level connections — links stored in DB, wired as Docker bridge networks
- `ifOperStatus` auto-synced in Redis when a link is created or removed
- Sacramento fixture — 5 Cisco devices seeded with real walk data, 6 CDP-verified links

#### Web UI
- Dashboard — live device/network/query stats
- Devices — create, start, stop, restart, delete; seed import; export OIDs; MIB assign
- MIBs — upload MIB files, OID tree browser
- Networks — create/delete Docker networks; LAN-mode NIC picker on Linux
- Topology — canvas with interface handles, LinkDialog, left-panel link list
- Device Detail — per-OID editor with mode/type picker, bulk apply

#### API
- REST API at `http://localhost:8000` (FastAPI + OpenAPI docs at `/docs`)
- `GET /api/platform` — OS detection for UI feature gating
- `GET /api/networks/interfaces` — list host NICs for macvlan parent picker
- `GET /api/topology` — nodes + links with live container status
- `POST /api/topology/links` — provision link + Docker network
- All endpoints documented at `/docs`

#### Performance (3 000+ OIDs)
- MibStore sorts OIDs **numerically** at load time (fixes broken GETNEXT traversal)
- `sorted_pairs()` returns pre-built `(tuple, oid_str)` list — O(1) per request
- GETBULK cap raised to 1 000 repetitions; 45 KB soft response-size guard
- Agent process protected: all packet handler exceptions caught, never kill process
- Non-numeric OID keys (symbolic MIB names) filtered at load time and at API write time

### Technical stack
- **Backend**: Python 3.11, FastAPI, SQLAlchemy 2, Alembic, asyncpg (PostgreSQL 16)
- **Agent**: Python 3.11, pysnmp 4.4.12, Redis pub/sub for live OID reload
- **Frontend**: React 18, TypeScript, Vite, React Flow v12, TanStack Query
- **Infrastructure**: Docker Engine, Docker Compose, Redis 7, PostgreSQL 16

---

## [Unreleased]

- [ ] SNMPv2c TRAP generation (outbound traps to NMS)
- [ ] Device template library (pre-configured Cisco, Juniper, HP profiles)
- [ ] Scheduled OID value changes (cron-style simulation of events)
- [ ] SNMP SET support (write back to Redis)
- [ ] Multi-user support with device ownership
- [ ] REST API authentication (API keys)
