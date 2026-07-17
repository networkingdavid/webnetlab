# WebNetLab — Architecture & Implementation Plan

## Overview

**WebNetLab** is a web-based network device simulator. It presents itself to any third-party SNMPv2c Network Management System (NMS) as if it were a fleet of real network devices — each with its own IP address, MAC address, MIB tree, and Docker-networked interfaces.

### Core Principles
- **SNMPv2c only** — V1 and V3 are explicitly out of scope for V1.
- **Docker-native** — each simulated device runs as its own container with a real IP on a user-defined Docker network (bridge or NAT).
- **MIB-driven** — device behavior is defined by importing a MIB file and optionally seeding values from a real `snmpwalk` capture.
- **Runtime-configurable** — OID values can be changed live (individually or in bulk) without restarting containers.
- **Topology-aware** — a visual canvas wires device interfaces together, and those links are provisioned as real Docker network connections.

### Tech Stack
| Layer | Choice |
|---|---|
| Backend API | Python + FastAPI |
| SNMP Engine | pysnmp (SNMPv2c agent per container) |
| MIB Compiler | pysmi (MIB → Python object model) |
| Database | PostgreSQL (device config, OID values, topology) |
| Message Bus | Redis (runtime OID updates pushed to containers) |
| Frontend | React + TypeScript |
| Topology Canvas | React Flow |
| Container Orchestration | Docker SDK for Python (docker-py) |
| Networking | Docker bridge / macvlan networks via Docker SDK |

### Existing Reference Data
The workspace contains real Cisco device topology data (`topology_raw.json`, `sacramento_network_topology.md`) that can be used as seed/test data during development.

---

## Sub-Tasks

---

### Sub-Task 1 — Project Scaffolding & Monorepo Setup

**Intent**
Establish the repository structure, Docker Compose baseline, and shared configuration so every subsequent sub-task has a consistent place to land code.

**Expected Outcomes**
- Monorepo with `backend/`, `frontend/`, `agent/`, and `infra/` directories.
- `docker-compose.yml` that brings up PostgreSQL, Redis, the FastAPI backend, and the React frontend in development mode.
- Backend and frontend both start without errors.
- Environment variable strategy documented (`.env.example`).

**Todo List**
1. Create monorepo directory layout:
   ```
   webnetlab/
   ├── backend/          # FastAPI app
   ├── agent/            # SNMP agent process (runs inside device containers)
   ├── frontend/         # React + TypeScript app
   ├── infra/
   │   ├── docker/       # Dockerfiles for backend, agent, frontend
   │   └── compose/      # docker-compose files
   ├── mibs/             # Uploaded MIB file storage
   ├── seeds/            # Optional snmpwalk seed files
   └── .env.example
   ```
2. Write `backend/pyproject.toml` (or `requirements.txt`) with: fastapi, uvicorn, sqlalchemy, alembic, asyncpg, redis, docker, pysmi, pysnmp, python-multipart.
3. Write `agent/requirements.txt` with: pysnmp, redis.
4. Bootstrap React app in `frontend/` with Vite + TypeScript template.
5. Write `infra/docker/Dockerfile.backend`, `Dockerfile.agent`, `Dockerfile.frontend`.
6. Write `docker-compose.yml` with services: `db` (postgres:16), `redis` (redis:7-alpine), `backend`, `frontend`.
7. Write `.env.example` covering DB URL, Redis URL, secret key, SNMP community string default.
8. Write `backend/app/main.py` with FastAPI app skeleton and a `/health` endpoint.
9. Confirm `docker compose up` starts all four services cleanly.

**Relevant Context**
- No existing scaffolding. Pure greenfield.
- Status: `[ ] pending`

---

### Sub-Task 2 — Database Schema & Migrations

**Intent**
Define the data model that backs every feature: devices, networks, MIBs, OID value overrides, topology links, and audit log.

**Expected Outcomes**
- Alembic migrations produce a clean schema on first run.
- All core entities are representable in the DB.
- SQLAlchemy ORM models exist for each table.

**Todo List**
1. Design and create Alembic migration for the following tables:
   - `networks` — id, name, type (bridge|macvlan|nat), docker_network_id, subnet, gateway, created_at
   - `devices` — id, name, type (router|switch|server|generic), ip_address, mac_address, network_id (FK), docker_container_id, status (stopped|running|error), snmp_community, created_at, updated_at
   - `mibs` — id, name, filename, parsed_at, raw_content (text), created_at
   - `device_mibs` — device_id (FK), mib_id (FK), loaded_at  _(junction table)_
   - `oid_values` — id, device_id (FK), oid (string), value_mode (static|random|scripted|walk_seed), static_value (text), random_config (jsonb), script (text), walk_seed_value (text), updated_at
   - `topology_links` — id, src_device_id (FK), src_interface, dst_device_id (FK), dst_interface, docker_network_id, created_at
   - `audit_log` — id, action, entity_type, entity_id, payload (jsonb), created_at
2. Write SQLAlchemy ORM models in `backend/app/models/`.
3. Write Alembic `env.py` to pick up models automatically.
4. Run migration against the dev DB and verify schema.

**Relevant Context**
- `oid_values.random_config` stores JSON like `{"min": 0, "max": 100, "type": "integer"}`.
- `oid_values.script` stores a Python expression string evaluated at query time.
- Status: `[ ] pending`

---

### Sub-Task 3 — MIB Import & OID Tree Service

**Intent**
Allow users to upload a MIB file, compile it with pysmi, and store the resulting OID tree so the frontend can browse and configure individual OIDs.

**Expected Outcomes**
- `POST /api/mibs/upload` accepts a `.mib` file, compiles it, and stores the OID tree.
- `GET /api/mibs/{mib_id}/oids` returns the full OID tree with name, OID string, type, access, description.
- Compilation errors are returned as structured API errors.
- The compiled MIB is stored persistently so re-upload is not required on restart.

**Todo List**
1. Write `backend/app/services/mib_service.py`:
   - `compile_mib(filepath) -> dict` — uses pysmi `MibCompiler` to parse the MIB into a Python-readable structure.
   - `extract_oid_tree(compiled_mib) -> list[OIDNode]` — walks the compiled output and returns a flat list of `{name, oid, syntax, access, description}`.
2. Write `POST /api/mibs/upload` endpoint: save file to `mibs/` volume, call `compile_mib`, persist to `mibs` table, return OID tree.
3. Write `GET /api/mibs/{mib_id}/oids` endpoint: return stored OID tree.
4. Write `POST /api/mibs/{mib_id}/assign/{device_id}` endpoint: assign a MIB to a device (inserts into `device_mibs`).
5. Write unit tests for `mib_service.py` using a known-good MIB file (e.g., RFC1213-MIB / IF-MIB).

**Relevant Context**
- pysmi can compile standard IETF MIBs and vendor MIBs.
- The workspace's `topology_raw.json` contains real Cisco interface data that can be used to manually craft a seed walk file for IF-MIB testing.
- Status: `[ ] pending`

---

### Sub-Task 4 — SNMP Agent Process (Device Container)

**Intent**
Build the lightweight SNMP agent that runs inside each device container. It listens on UDP 161, answers SNMPv2c GET/GETNEXT/GETBULK queries using pysnmp, and fetches live OID values from Redis (which the backend pushes to).

**Expected Outcomes**
- Agent process starts, binds to the container's IP on UDP 161, and answers SNMP queries.
- OID values are read from Redis key `device:{device_id}:oids` (a hash of oid → value).
- Value modes are applied at query time: static returns stored value, random generates on each query, scripted evaluates the expression.
- SNMPv1 and SNMPv3 queries are silently dropped.
- Agent reconnects to Redis on connection loss.

**Todo List**
1. Write `agent/agent.py` — main entrypoint:
   - Read env vars: `DEVICE_ID`, `SNMP_COMMUNITY`, `REDIS_URL`, `LISTEN_IP`.
   - Build pysnmp `AsyncioDispatcher` bound to `LISTEN_IP:161`.
   - Register a SNMPv2c community and a custom `MibInstrumController` that looks up OID values from Redis.
2. Write `agent/oid_resolver.py`:
   - `resolve(oid, device_id, redis_client) -> value` — reads from Redis hash, applies value mode logic.
   - For `random` mode, reads config from a separate Redis key `device:{device_id}:oid_config:{oid}`.
3. Write `agent/redis_listener.py` — subscribes to Redis channel `device:{device_id}:updates` to invalidate in-process OID cache (optional local cache for performance).
4. Write `infra/docker/Dockerfile.agent` — minimal Python image, copies agent code, runs `python agent.py`.
5. Write integration test: spin up agent container, run `snmpget` CLI against it, verify correct value is returned.

**Relevant Context**
- pysnmp's `AsyncioDispatcher` supports async operation for handling concurrent queries.
- The agent is intentionally stateless — all state lives in Redis so the container can be killed and restarted without data loss.
- Status: `[ ] pending`

---

### Sub-Task 5 — Device & Network Management API

**Intent**
Provide the REST API for creating/updating/deleting simulated devices and Docker networks, and for orchestrating the lifecycle of device containers.

**Expected Outcomes**
- `POST /api/networks` creates a Docker network (bridge or NAT/macvlan) and persists it.
- `POST /api/devices` creates a device record, provisions a Docker container using `Dockerfile.agent`, assigns IP/MAC on the chosen network.
- `DELETE /api/devices/{id}` stops and removes the container.
- `PATCH /api/devices/{id}` supports runtime updates (IP change triggers container recreation).
- `GET /api/devices` returns all devices with current status.
- `POST /api/devices/bulk` creates multiple devices at once.

**Todo List**
1. Write `backend/app/services/docker_service.py`:
   - `create_network(name, type, subnet, gateway) -> docker_network_id`
   - `create_device_container(device, network) -> container_id` — uses docker-py to run the agent image with correct env vars and network assignment.
   - `set_container_mac(container_id, network_id, mac)` — sets MAC via Docker endpoint config.
   - `stop_and_remove(container_id)`
   - `get_container_status(container_id) -> str`
2. Write `backend/app/routers/networks.py` — CRUD for networks.
3. Write `backend/app/routers/devices.py` — CRUD + lifecycle endpoints for devices.
4. On device creation, after container starts: push initial OID values from `oid_values` table into Redis.
5. Write `backend/app/services/oid_push_service.py` — `push_device_oids(device_id)` loads all OID config from DB and sets Redis keys.
6. Write tests covering network creation and device container lifecycle.

**Relevant Context**
- Docker bridge networks allow custom IP/MAC assignment per container endpoint.
- macvlan networks give containers a presence on the physical LAN — useful for bridge mode where external NMS can reach them directly.
- Status: `[ ] pending`

---

### Sub-Task 6 — OID Value Configuration API

**Intent**
Let users configure how each OID on each device responds: static value, random range, scripted expression, or seeded from a real snmpwalk capture.

**Expected Outcomes**
- `GET /api/devices/{id}/oids` returns all OID configs for a device.
- `PUT /api/devices/{id}/oids/{oid}` updates a single OID config and immediately pushes the update to Redis (live, no restart needed).
- `POST /api/devices/{id}/oids/bulk` updates multiple OIDs at once.
- `POST /api/devices/{id}/seed` accepts a `snmpwalk` output file and bulk-imports all OID values as `walk_seed` mode.
- `POST /api/devices/bulk-oids` applies the same OID config change to a set of device IDs (collective update).

**Todo List**
1. Write `backend/app/routers/oids.py` with all endpoints above.
2. Write `backend/app/services/walk_parser.py`:
   - `parse_snmpwalk(file_content) -> list[{oid, value}]` — parses standard `snmpwalk -v2c -c public host` text output format.
3. On every `PUT`/bulk update, call `oid_push_service.push_device_oids(device_id)` to sync Redis.
4. Publish update notification to `device:{device_id}:updates` Redis channel so the running agent invalidates its cache.
5. Write tests for the walk parser using a real snmpwalk snippet from `topology_raw.json` data.

**Relevant Context**
- `topology_raw.json` in the workspace contains `show interfaces` and `show ip interface brief` outputs that mirror what a real snmpwalk of IF-MIB would contain — useful for crafting test fixtures.
- Status: `[ ] pending`

---

### Sub-Task 7 — Topology Canvas & Docker Network Wiring

**Intent**
Provide a visual drag-and-drop canvas where users define connections between device interfaces. Each drawn link provisions a real Docker network between the two device containers so ARP, ping, and topology-related OIDs (ifTable neighbors) work correctly.

**Expected Outcomes**
- Frontend renders a canvas with device nodes and their interfaces.
- Drawing a link between two interfaces: (a) saves a `topology_links` record, (b) creates a Docker network for the link if one doesn't exist, (c) attaches both containers to that network.
- Removing a link detaches containers from the link network and deletes the Docker network.
- Interface OIDs (ifAdminStatus, ifOperStatus) on each device reflect link state.
- `GET /api/topology` returns all devices and links in a React Flow-compatible JSON structure.

**Todo List**
1. Write `backend/app/routers/topology.py`:
   - `GET /api/topology` — return nodes and edges.
   - `POST /api/topology/links` — create a link, provision Docker network, attach containers.
   - `DELETE /api/topology/links/{id}` — remove link, detach containers, remove Docker network.
2. Write `backend/app/services/topology_service.py`:
   - `provision_link(src_device, src_iface, dst_device, dst_iface)` — orchestrates Docker network creation and container attachment.
   - `teardown_link(link_id)` — reverses provisioning.
   - `sync_interface_oids(device_id)` — updates ifAdminStatus/ifOperStatus in Redis based on current link state.
3. Write frontend `TopologyCanvas` React component using React Flow:
   - Fetch `/api/topology` on load.
   - Render device nodes with expandable interface ports.
   - On edge connect: call `POST /api/topology/links`.
   - On edge delete: call `DELETE /api/topology/links/{id}`.
4. Import the Sacramento topology (`sacramento_network_topology.md`) as a fixture to validate the canvas renders a real multi-device topology.

**Relevant Context**
- React Flow supports custom node types — device nodes should show device name, IP, and a list of interfaces as connection handles.
- Each Docker network between two devices should use a /30 or /31 subnet drawn from a management pool.
- Status: `[ ] pending`

---

### Sub-Task 8 — Frontend: Core UI Screens

**Intent**
Build the main web interface screens that tie together all backend capabilities into a usable product.

**UI Design Decisions (confirmed)**
- **Navigation**: Left sidebar (persistent, collapsible) — similar to Grafana/Proxmox style.
- **OID tree**: Collapsed to top-level MIB modules by default; user expands nodes on demand.
- **Topology Canvas**: Embedded as a tab/panel within a split layout — devices list panel on the left, canvas fills the right. Clicking a device in the list highlights its node on the canvas.

**Expected Outcomes**
- **App Shell** — left sidebar with nav links, top bar with app name and global status indicator.
- **Dashboard** — summary of running devices, networks, active SNMP queries (counter from Redis).
- **Devices List** — table of devices with status badges, quick-edit, start/stop controls.
- **Device Detail** — OID tree browser (collapsed by default, virtual scrolling) with inline value editing per OID (mode selector + value field).
- **MIB Manager** — upload MIB, view compiled OID tree collapsed by default, assign to device.
- **Network Manager** — create/delete Docker networks (bridge / NAT), view assigned devices.
- **Topology Page** — split layout: devices panel (left) + embedded React Flow canvas (right).

**Todo List**
1. Set up React Router with routes for each screen.
2. Set up Tanstack Query for API data fetching and cache invalidation.
3. Build `AppShell` — left sidebar with collapsible nav links (Dashboard, Networks, Devices, MIBs, Topology), top bar.
4. Build shared components: `StatusBadge`, `DeviceCard`, `OIDTable` (virtual scroll, collapsed by default), `ValueModeEditor`.
5. Build `DevicesPage` — list + create form (name, type, IP, MAC, network, community string).
6. Build `DeviceDetailPage` — OID tree collapsed to module level on load; expand on click; inline mode editor per OID.
7. Build `MIBManagerPage` — file upload + OID tree viewer (collapsed by default) + device assignment.
8. Build `NetworkManagerPage` — create network form (name, type, subnet, gateway).
9. Build `DashboardPage` — aggregate stats from `/api/stats` endpoint.
10. Build `TopologyPage` — split layout: left panel = devices list with search/filter; right panel = embedded React Flow canvas. Selecting a device in the list highlights its node on the canvas.

**Relevant Context**
- The OID tree for a full device MIB can have thousands of entries — virtual scrolling is required for `DeviceDetailPage` and `MIBManagerPage`.
- React Flow's `fitView` and `setCenter` APIs can be used to highlight/pan to a node when selected from the devices panel.
- Status: `[ ] pending`

---

### Sub-Task 9 — snmpwalk Seed Import & Sacramento Fixture

**Intent**
Validate the full simulation pipeline end-to-end using the real Cisco device data already in the workspace.

**Expected Outcomes**
- A fixture script imports the Sacramento topology (5 devices, their interfaces, and CDP links) into WebNetLab.
- Each device is seeded from its `show interfaces` output converted to an IF-MIB snmpwalk format.
- An external `snmpwalk` against any of the 5 simulated IPs returns realistic interface data.
- The topology canvas renders the full Sacramento network diagram.

**Todo List**
1. Write `seeds/sacramento_import.py`:
   - Reads `topology_raw.json`.
   - Creates 5 devices via the REST API with IPs matching the real devices.
   - Assigns IF-MIB to each device.
   - Converts `show interfaces` output to snmpwalk format and seeds OID values via `POST /api/devices/{id}/seed`.
   - Creates topology links matching CDP-discovered neighbors.
2. Run `snmpwalk -v2c -c public <simulated_ip> 1.3.6.1.2.1.2` (IF-MIB ifTable) against each device and verify output.
3. Verify topology canvas renders 5 nodes and 4+ links correctly.
4. Document the import procedure in `seeds/README.md`.

**Relevant Context**
- `topology_raw.json` contains `show interfaces description` and `show ip interface brief` for all 5 devices.
- `sacramento_network_topology.md` documents CDP-verified links that should map to `topology_links` DB records.
- Status: `[x] done`

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        NMS / SNMP Manager                        │
│              (Zabbix, PRTG, LibreNMS, snmpwalk CLI)              │
└───────────────────────────┬─────────────────────────────────────┘
                            │  SNMPv2c UDP :161
              ┌─────────────▼──────────────┐
              │    Docker Network(s)        │
              │  bridge / macvlan / NAT     │
              │                            │
       ┌──────┴──────┐            ┌────────┴──────┐
       │  Device A   │            │  Device B     │
       │  Container  │◄──────────►│  Container    │
       │  agent.py   │  link net  │  agent.py     │
       │  :161 UDP   │            │  :161 UDP     │
       └──────┬──────┘            └────────┬──────┘
              │  Redis get oid values       │
              └──────────┬─────────────────┘
                         │
          ┌──────────────▼──────────────────┐
          │            Redis                 │
          │   device:{id}:oids (hash)        │
          │   device:{id}:updates (pubsub)   │
          └──────────────┬───────────────────┘
                         │
          ┌──────────────▼──────────────────┐
          │         FastAPI Backend          │
          │  /api/devices  /api/mibs         │
          │  /api/topology /api/oids         │
          │  docker_service  mib_service     │
          │  oid_push_service                │
          └──────────────┬───────────────────┘
                         │
          ┌──────────────▼──────────────────┐
          │          PostgreSQL              │
          │  devices, networks, mibs,        │
          │  oid_values, topology_links      │
          └──────────────┬───────────────────┘
                         │
          ┌──────────────▼──────────────────┐
          │       React Frontend             │
          │  Dashboard, Devices, MIBs,       │
          │  Topology Canvas (React Flow)    │
          └──────────────────────────────────┘
```

---

## Non-Goals for V1
- SNMPv1 and SNMPv3 support
- SNMP TRAP / INFORM generation (NMS-initiated only)
- NETCONF / gNMI protocols
- User authentication / multi-tenancy
- High-availability of the backend itself
