from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class PixelLog(Base):
    __tablename__ = "pixel_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # Retained for historic records. New writes use visitor_id and visit_id.
    user_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    request_id: Mapped[str | None] = mapped_column(String(36), nullable=True, unique=True)
    visitor_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    visit_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("visit_logs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    x: Mapped[int] = mapped_column(Integer, nullable=False)
    y: Mapped[int] = mapped_column(Integer, nullable=False)
    color: Mapped[str] = mapped_column(String(7), nullable=False)
    previous_color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    restore_operation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.now(),
        index=True,
    )

    __table_args__ = (
        CheckConstraint("char_length(color) = 7", name="ck_pixel_logs_color_length"),
    )


class VisitLog(Base):
    __tablename__ = "visit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ip: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    visitor_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    connection_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.now(),
    )
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CanvasSnapshot(Base):
    __tablename__ = "canvas_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.now(),
        index=True,
    )
    last_log_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    # Historic data may contain duplicate filenames.  Reconciliation marks
    # obsolete rows invalid; new snapshots still use collision-free UUID names.
    data_file_path: Mapped[str] = mapped_column(String(255), nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="valid", index=True)


class SiteCounter(Base):
    __tablename__ = "site_counters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    total_visits: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_placed_pixels: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    __table_args__ = (CheckConstraint("id = 1", name="ck_site_counters_singleton"),)


class ModerationState(Base):
    __tablename__ = "moderation_states"

    visitor_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    overwrite_cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    overwrite_watch_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    strike_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class RestorePlan(Base):
    __tablename__ = "restore_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    target_event_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    head_event_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    filters_json: Mapped[str] = mapped_column(Text, nullable=False)
    preview_file_path: Mapped[str | None] = mapped_column(String(255))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ready")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class RestoreOperation(Base):
    __tablename__ = "restore_operations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    plan_id: Mapped[str] = mapped_column(String(36), ForeignKey("restore_plans.id"), nullable=False)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    affected_pixels: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_pixels: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AdminAction(Base):
    __tablename__ = "admin_actions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    admin_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    details_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
