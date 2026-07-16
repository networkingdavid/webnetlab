from datetime import datetime

from sqlalchemy import ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class OIDValue(Base):
    __tablename__ = "oid_values"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False)
    oid: Mapped[str] = mapped_column(String(256), nullable=False)
    value_mode: Mapped[str] = mapped_column(String(32), default="static")  # static|random|scripted|walk_seed
    static_value: Mapped[str | None] = mapped_column(Text)
    random_config: Mapped[dict | None] = mapped_column(JSON)
    script: Mapped[str | None] = mapped_column(Text)
    walk_seed_value: Mapped[str | None] = mapped_column(Text)
    value_type: Mapped[str] = mapped_column(String(32), default="string")  # string|integer|counter|gauge|timeticks|ipaddress
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)

    device: Mapped["Device"] = relationship(back_populates="oid_values")

    __table_args__ = (UniqueConstraint("device_id", "oid", name="uq_device_oid"),)
