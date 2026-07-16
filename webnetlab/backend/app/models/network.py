from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Network(Base):
    __tablename__ = "networks"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)  # bridge | host-bridge | macvlan
    docker_network_id: Mapped[str | None] = mapped_column(String(128))
    subnet: Mapped[str | None] = mapped_column(String(64))
    gateway: Mapped[str | None] = mapped_column(String(64))
    host_interface: Mapped[str | None] = mapped_column(String(64))  # e.g. "en0" — Linux macvlan only
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    devices: Mapped[list["Device"]] = relationship(back_populates="network")
