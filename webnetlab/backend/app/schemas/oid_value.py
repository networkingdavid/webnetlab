from datetime import datetime
from typing import Any

from pydantic import BaseModel


class OIDValueCreate(BaseModel):
    oid: str                          # dotted OID string e.g. "1.3.6.1.2.1.1.1.0"
    value_mode: str = "static"        # static | random | scripted | walk_seed
    static_value: str | None = None
    random_config: dict | None = None  # {"min":0,"max":100,"type":"counter|gauge|integer|timeticks"}
    script: str | None = None
    walk_seed_value: str | None = None
    value_type: str = "string"        # ASN.1 type hint: string|integer|counter|gauge|timeticks|ipaddress


class OIDValueUpdate(BaseModel):
    value_mode: str | None = None
    static_value: str | None = None
    random_config: dict | None = None
    script: str | None = None
    walk_seed_value: str | None = None


class OIDValueResponse(BaseModel):
    id: int
    device_id: int
    oid: str
    value_mode: str
    static_value: str | None
    random_config: dict | None
    script: str | None
    walk_seed_value: str | None
    updated_at: datetime

    model_config = {"from_attributes": True}


class BulkOIDUpdate(BaseModel):
    updates: list[OIDValueCreate]    # each item has oid + new config


class BulkDeviceOIDUpdate(BaseModel):
    device_ids: list[int]
    oid: str
    value_mode: str
    static_value: str | None = None
    random_config: dict | None = None
    script: str | None = None
    walk_seed_value: str | None = None
