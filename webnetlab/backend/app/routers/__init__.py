from fastapi import APIRouter

from app.routers.mibs import router as mibs_router
from app.routers.networks import router as networks_router
from app.routers.devices import router as devices_router
from app.routers.oids import router as oids_router
from app.routers.topology import router as topology_router

router = APIRouter()

router.include_router(mibs_router, prefix="/api/mibs", tags=["mibs"])
router.include_router(networks_router, prefix="/api/networks", tags=["networks"])
router.include_router(devices_router, prefix="/api/devices", tags=["devices"])
router.include_router(oids_router, tags=["oids"])
router.include_router(topology_router, prefix="/api/topology", tags=["topology"])
