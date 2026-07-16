from datetime import datetime

from pydantic import BaseModel


class TopologyLinkCreate(BaseModel):
    src_device_id: int
    src_interface: str      # e.g. "GigabitEthernet0/0"
    dst_device_id: int
    dst_interface: str


class TopologyLinkResponse(BaseModel):
    id: int
    src_device_id: int
    src_interface: str
    dst_device_id: int
    dst_interface: str
    docker_network_id: str | None
    created_at: datetime
    model_config = {"from_attributes": True}


class TopologyNodeResponse(BaseModel):
    id: int
    name: str
    type: str
    ip_address: str
    status: str
    interfaces: list[str]


class TopologyResponse(BaseModel):
    nodes: list[TopologyNodeResponse]
    links: list[TopologyLinkResponse]
