from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[str] = mapped_column(String(64), default="generic")  # router|switch|server|generic
    ip_address: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    mac_address: Mapped[str | None] = mapped_column(String(32))
    network_id: Mapped[int | None] = mapped_column(ForeignKey("networks.id"))
    docker_container_id: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="stopped")  # stopped|running|error
    snmp_community: Mapped[str] = mapped_column(String(64), default="public")
    snmp_port: Mapped[int | None] = mapped_column(default=None)  # host UDP port for port-forward mode (macOS)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)

    network: Mapped["Network"] = relationship(back_populates="devices")
    mibs: Mapped[list["MIB"]] = relationship(secondary="device_mibs", back_populates="devices")
    oid_values: Mapped[list["OIDValue"]] = relationship(back_populates="device")
    src_links: Mapped[list["TopologyLink"]] = relationship(
        foreign_keys="TopologyLink.src_device_id", back_populates="src_device"
    )
    dst_links: Mapped[list["TopologyLink"]] = relationship(
        foreign_keys="TopologyLink.dst_device_id", back_populates="dst_device"
    )
