from datetime import datetime

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class MIB(Base):
    __tablename__ = "mibs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    filename: Mapped[str] = mapped_column(String(256), nullable=False)
    parsed_at: Mapped[datetime | None]
    raw_content: Mapped[str | None] = mapped_column(Text)
    oid_tree_path: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    devices: Mapped[list["Device"]] = relationship(secondary="device_mibs", back_populates="mibs")


class DeviceMIB(Base):
    __tablename__ = "device_mibs"

    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), primary_key=True)
    mib_id: Mapped[int] = mapped_column(ForeignKey("mibs.id"), primary_key=True)
    loaded_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
