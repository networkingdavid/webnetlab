from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TopologyLink(Base):
    __tablename__ = "topology_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    src_device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False)
    src_interface: Mapped[str] = mapped_column(String(128), nullable=False)
    dst_device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False)
    dst_interface: Mapped[str] = mapped_column(String(128), nullable=False)
    docker_network_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    src_device: Mapped["Device"] = relationship(
        foreign_keys=[src_device_id], back_populates="src_links"
    )
    dst_device: Mapped["Device"] = relationship(
        foreign_keys=[dst_device_id], back_populates="dst_links"
    )
