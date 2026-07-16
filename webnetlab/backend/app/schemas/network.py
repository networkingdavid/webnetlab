from datetime import datetime

from pydantic import BaseModel


class NetworkCreate(BaseModel):
    name: str
    type: str           # bridge | host-bridge | macvlan
    subnet: str
    gateway: str
    host_interface: str | None = None  # Linux macvlan only, e.g. "eth0"


class NetworkResponse(BaseModel):
    id: int
    name: str
    type: str
    docker_network_id: str | None
    subnet: str | None
    gateway: str | None
    host_interface: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
