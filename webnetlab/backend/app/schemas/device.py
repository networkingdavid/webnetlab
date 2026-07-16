from datetime import datetime

from pydantic import BaseModel


class DeviceCreate(BaseModel):
    name: str
    type: str = "generic"  # router|switch|server|generic
    ip_address: str
    mac_address: str | None = None
    network_id: int
    snmp_community: str = "public"
    snmp_port: int | None = None  # host UDP port for port-forward mode (macOS/NAT)


class DeviceUpdate(BaseModel):
    name: str | None = None
    snmp_community: str | None = None
    snmp_port: int | None = None


class DeviceResponse(BaseModel):
    id: int
    name: str
    type: str
    ip_address: str
    mac_address: str | None
    network_id: int | None
    docker_container_id: str | None
    status: str
    snmp_community: str
    snmp_port: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BulkDeviceCreate(BaseModel):
    devices: list[DeviceCreate]
