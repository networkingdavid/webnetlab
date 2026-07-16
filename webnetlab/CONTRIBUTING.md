# Contributing to WebNetLab

Thank you for your interest in contributing! This guide covers how to set up a development environment, project structure, and how to submit changes.

---

## Development setup

### Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Docker Engine | 20.10+ | Not Docker Desktop on Linux |
| Docker Compose | v2.x | `docker compose` (not `docker-compose`) |
| Python | 3.11+ | Backend / agent |
| Node.js | 20+ | Frontend |
| Git | any | |

### Clone and start

```bash
git clone https://github.com/your-org/webnetlab.git
cd webnetlab

# macOS
echo "HOST_PLATFORM=Darwin" > webnetlab/.env

# Linux
echo "HOST_PLATFORM=Linux" > webnetlab/.env

cd webnetlab
docker compose --profile build-only build agent-builder
docker compose build
docker compose up -d
```

The first start runs Alembic migrations automatically. Open `http://localhost:5173`.

### Hot reload

Both backend and frontend support hot reload in development:
- **Backend**: uvicorn `--reload` watches `app/` for changes
- **Frontend**: Vite HMR updates the browser instantly on file save

No rebuild needed for Python or TypeScript changes during development.

---

## Project structure

```
webnetlab/
├── backend/            FastAPI application
│   ├── app/
│   │   ├── main.py     App entry point, router registration
│   │   ├── config.py   Settings (pydantic-settings)
│   │   ├── models/     SQLAlchemy ORM models
│   │   ├── schemas/    Pydantic request/response schemas
│   │   ├── routers/    FastAPI route handlers
│   │   └── services/   Business logic (Docker, SNMP, OID push)
│   ├── alembic/        DB migrations
│   └── pyproject.toml  Python deps
│
├── agent/              SNMP agent (runs inside each device container)
│   ├── agent.py        UDP listener, GET/GETNEXT/GETBULK dispatch
│   ├── mib_store.py    Redis OID cache, numerically sorted
│   ├── oid_resolver.py Value mode evaluator (static/random/scripted)
│   └── requirements.txt pysnmp 4.4.12 pinned
│
├── frontend/           React + TypeScript SPA
│   └── src/
│       ├── App.tsx     Router
│       ├── api/        API client functions (one file per resource)
│       ├── components/ Shared UI components
│       ├── pages/      Route-level page components
│       └── types/      Shared TypeScript interfaces
│
├── infra/              Host setup scripts
│   └── linux-macvlan-setup.sh
│
├── seeds/              Seed scripts and fixture data
│   └── sacramento_import.py
│
├── mibs/               MIB file storage (Docker volume)
├── docs/               Extended documentation
│   └── linux-lan-mode.md
│
├── docker-compose.yml
├── docker-compose.override.yml   Dev mounts (auto-applied)
└── .env.example
```

---

## Making changes

### Backend changes

Edit files in `webnetlab/backend/app/`. Uvicorn auto-reloads.

Run type checks:
```bash
docker compose exec backend python -m mypy app/ --ignore-missing-imports
```

### Agent changes

The agent runs in separate `webnetlab-device-*` containers, not the compose stack.
After changing `agent/`, rebuild the image and restart devices:

```bash
docker build -t webnetlab-agent:latest ./webnetlab/agent
# Then restart affected devices via the UI or:
curl -X POST http://localhost:8000/api/devices/{id}/start
```

### Frontend changes

Edit files in `webnetlab/frontend/src/`. Vite HMR applies instantly.

TypeScript check:
```bash
docker compose exec frontend sh -c "cd /app && npx tsc --noEmit"
```

### Database migrations

```bash
# Generate a new migration after changing models:
docker compose exec backend alembic revision --autogenerate -m "describe_change"

# Apply:
docker compose exec backend alembic upgrade head
```

---

## Submitting changes

1. **Fork** the repo and create a branch: `git checkout -b feature/my-feature`
2. Make your changes, following the patterns in existing code
3. Run a TypeScript check and confirm the backend reloads cleanly
4. **Commit** with a clear message: `git commit -m "feat: add scheduled OID changes"`
5. **Push** and open a Pull Request against `main`

### Commit message convention

```
type: short description

Types: feat, fix, perf, refactor, docs, test, chore
```

---

## Reporting issues

Please include:
- Host OS (macOS version / Linux distro + kernel version)
- Docker version (`docker --version`)
- Steps to reproduce
- Relevant container logs (`docker compose logs backend`, `docker logs webnetlab-device-N`)
