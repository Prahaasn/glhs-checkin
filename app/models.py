import time

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Teacher(Base):
    __tablename__ = "teachers"
    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    badge_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    inside: Mapped[bool] = mapped_column(Boolean, default=False)
    last_seen: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ScanEvent(Base):
    __tablename__ = "scan_events"
    __table_args__ = (UniqueConstraint("request_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_pk: Mapped[int] = mapped_column(ForeignKey("teachers.id"), index=True)
    request_id: Mapped[str] = mapped_column(String(36))
    direction: Mapped[str] = mapped_column(String(3))
    station: Mapped[str] = mapped_column(String(32))
    occurred_at: Mapped[int] = mapped_column(Integer, index=True)
    changed: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str | None] = mapped_column(String(240), nullable=True)


class AccessSession(Base):
    __tablename__ = "access_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    role: Mapped[str] = mapped_column(String(8))
    station: Mapped[str | None] = mapped_column(String(32), nullable=True)
    expires_at: Mapped[int] = mapped_column(Integer, index=True)
