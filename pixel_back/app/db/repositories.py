"""Database operations used by the application services.

Repository functions deliberately do not commit.  A service owns the
transaction so a pixel log, its counter update and any audit row remain
atomic.
"""

from __future__ import annotations

from datetime import datetime
from typing import Mapping, Sequence
import json

from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AdminAction,
    CanvasSnapshot,
    ModerationState,
    PixelLog,
    RestoreOperation,
    RestorePlan,
    SiteCounter,
    VisitLog,
    utc_now,
)


async def get_or_create_counters(session: AsyncSession) -> SiteCounter:
    counters = await session.get(SiteCounter, 1)
    if counters is None:
        counters = SiteCounter(id=1)
        session.add(counters)
        await session.flush()
    return counters


async def get_pixel_by_request_id(session: AsyncSession, request_id: str) -> PixelLog | None:
    return await session.scalar(select(PixelLog).where(PixelLog.request_id == request_id))


async def create_pixel_log(
    session: AsyncSession,
    *,
    request_id: str | None,
    visitor_id: str | None,
    visit_id: int | None,
    x: int,
    y: int,
    color: str,
    previous_color: str | None,
    source: str = 'user',
    restore_operation_id: str | None = None,
) -> PixelLog:
    row = PixelLog(
        request_id=request_id,
        visitor_id=visitor_id,
        visit_id=visit_id,
        x=x,
        y=y,
        color=color,
        previous_color=previous_color,
        source=source,
        restore_operation_id=restore_operation_id,
    )
    session.add(row)
    await session.flush()
    return row


async def increment_placed_pixels(session: AsyncSession, amount: int = 1) -> int:
    counters = await get_or_create_counters(session)
    counters.total_placed_pixels += amount
    counters.updated_at = utc_now()
    await session.flush()
    return counters.total_placed_pixels


async def increment_visits(session: AsyncSession) -> int:
    counters = await get_or_create_counters(session)
    counters.total_visits += 1
    counters.updated_at = utc_now()
    await session.flush()
    return counters.total_visits


async def create_visit(
    session: AsyncSession,
    *,
    visitor_id: str,
    connection_id: str,
    ip: str,
) -> VisitLog:
    row = VisitLog(visitor_id=visitor_id, connection_id=connection_id, ip=ip)
    session.add(row)
    await session.flush()
    await increment_visits(session)
    return row


async def close_visit(session: AsyncSession, visit_id: int) -> None:
    await session.execute(
        update(VisitLog).where(VisitLog.id == visit_id, VisitLog.disconnected_at.is_(None)).values(disconnected_at=utc_now())
    )


async def get_visit_id_by_connection(session: AsyncSession, connection_id: str) -> int | None:
    return await session.scalar(select(VisitLog.id).where(VisitLog.connection_id == connection_id).order_by(VisitLog.id.desc()).limit(1))


async def get_counters(session: AsyncSession) -> SiteCounter:
    return await get_or_create_counters(session)


async def list_moderation_states(session: AsyncSession, limit: int = 100) -> list[ModerationState]:
    rows = await session.scalars(
        select(ModerationState)
        .where(ModerationState.blocked_until.is_not(None) | ModerationState.challenge_required_until.is_not(None))
        .order_by(ModerationState.updated_at.desc())
        .limit(limit)
    )
    return list(rows.all())


async def get_latest_pixel_id(session: AsyncSession) -> int:
    return int(await session.scalar(select(func.coalesce(func.max(PixelLog.id), 0))) or 0)


async def get_pixel_count_after(session: AsyncSession, event_id: int) -> int:
    return int(await session.scalar(select(func.count(PixelLog.id)).where(PixelLog.id > event_id)) or 0)


async def get_pixels_after(
    session: AsyncSession,
    event_id: int,
    *,
    through: int | None = None,
    limit: int = 5000,
) -> list[PixelLog]:
    statement: Select[tuple[PixelLog]] = select(PixelLog).where(PixelLog.id > event_id)
    if through is not None:
        statement = statement.where(PixelLog.id <= through)
    statement = statement.order_by(PixelLog.id).limit(limit)
    return list((await session.scalars(statement)).all())


async def list_snapshots_newest(session: AsyncSession) -> list[CanvasSnapshot]:
    rows = await session.scalars(
        select(CanvasSnapshot).where(CanvasSnapshot.status == 'valid').order_by(CanvasSnapshot.last_log_id.desc(), CanvasSnapshot.id.desc())
    )
    return list(rows.all())


async def get_snapshot(session: AsyncSession, snapshot_id: int) -> CanvasSnapshot | None:
    return await session.get(CanvasSnapshot, snapshot_id)


async def get_snapshot_at_or_before(session: AsyncSession, event_id: int) -> CanvasSnapshot | None:
    return await session.scalar(
        select(CanvasSnapshot)
        .where(CanvasSnapshot.status == 'valid', CanvasSnapshot.last_log_id <= event_id)
        .order_by(CanvasSnapshot.last_log_id.desc(), CanvasSnapshot.id.desc())
        .limit(1)
    )


async def create_snapshot(
    session: AsyncSession,
    *,
    last_log_id: int,
    data_file_path: str,
    width: int,
    height: int,
    sha256: str,
) -> CanvasSnapshot:
    row = CanvasSnapshot(
        last_log_id=last_log_id,
        data_file_path=data_file_path,
        width=width,
        height=height,
        sha256=sha256,
        status='valid',
    )
    session.add(row)
    await session.flush()
    return row


async def mark_snapshot_invalid(session: AsyncSession, snapshot_id: int) -> None:
    await session.execute(update(CanvasSnapshot).where(CanvasSnapshot.id == snapshot_id).values(status='invalid'))


async def update_snapshot_verification(
    session: AsyncSession, snapshot_id: int, *, width: int, height: int, sha256: str
) -> None:
    await session.execute(
        update(CanvasSnapshot)
        .where(CanvasSnapshot.id == snapshot_id)
        .values(width=width, height=height, sha256=sha256, status='valid')
    )


async def get_moderation_state(session: AsyncSession, visitor_id: str) -> ModerationState:
    row = await session.get(ModerationState, visitor_id)
    if row is None:
        row = ModerationState(visitor_id=visitor_id)
        session.add(row)
        await session.flush()
    return row


async def create_restore_plan(
    session: AsyncSession,
    *,
    plan_id: str,
    created_by: str,
    mode: str,
    target_event_id: int,
    current_head_event_id: int,
    filters: Mapping[str, object],
    expires_at: datetime,
) -> RestorePlan:
    row = RestorePlan(
        id=plan_id,
        created_by=created_by,
        mode=mode,
        target_event_id=target_event_id,
        head_event_id=current_head_event_id,
        filters_json=json.dumps(filters),
        expires_at=expires_at,
    )
    session.add(row)
    await session.flush()
    return row


async def create_restore_operation(
    session: AsyncSession,
    *,
    operation_id: str,
    plan_id: str,
    created_by: str,
    affected_pixels: int,
    status: str = 'completed',
) -> RestoreOperation:
    row = RestoreOperation(
        id=operation_id,
        plan_id=plan_id,
        created_by=created_by,
        affected_pixels=affected_pixels,
        status=status,
        completed_at=utc_now() if status == 'completed' else None,
    )
    session.add(row)
    await session.flush()
    return row


async def add_admin_action(
    session: AsyncSession,
    *,
    admin_id: str,
    action: str,
    details: dict | None = None,
) -> AdminAction:
    row = AdminAction(
        admin_id=admin_id,
        action=action,
        details_json=json.dumps(details or {}),
    )
    session.add(row)
    await session.flush()
    return row


async def list_pixels_between(
    session: AsyncSession,
    *,
    after_id: int,
    through_id: int,
    x_min: int | None = None,
    x_max: int | None = None,
    y_min: int | None = None,
    y_max: int | None = None,
    visitor_id: str | None = None,
    visit_id: int | None = None,
) -> list[PixelLog]:
    statement = select(PixelLog).where(PixelLog.id > after_id, PixelLog.id <= through_id)
    if x_min is not None:
        statement = statement.where(PixelLog.x >= x_min)
    if x_max is not None:
        statement = statement.where(PixelLog.x <= x_max)
    if y_min is not None:
        statement = statement.where(PixelLog.y >= y_min)
    if y_max is not None:
        statement = statement.where(PixelLog.y <= y_max)
    if visitor_id is not None:
        statement = statement.where(PixelLog.visitor_id == visitor_id)
    if visit_id is not None:
        statement = statement.where(PixelLog.visit_id == visit_id)
    return list((await session.scalars(statement.order_by(PixelLog.id))).all())


async def list_recent_visitor_pixels(
    session: AsyncSession, visitor_id: str, *, since: datetime, limit: int = 50
) -> list[PixelLog]:
    statement = (
        select(PixelLog)
        .where(PixelLog.visitor_id == visitor_id, PixelLog.created_at >= since)
        .order_by(PixelLog.id.desc())
        .limit(limit)
    )
    return list(reversed((await session.scalars(statement)).all()))


async def list_recent_risk_pixels(session: AsyncSession, *, since: datetime, limit: int = 10000) -> list[PixelLog]:
    rows = await session.scalars(
        select(PixelLog)
        .where(PixelLog.visitor_id.is_not(None), PixelLog.created_at >= since)
        .order_by(PixelLog.id.desc())
        .limit(limit)
    )
    return list(reversed(rows.all()))


async def list_admin_actions(session: AsyncSession, limit: int = 100) -> Sequence[AdminAction]:
    return (await session.scalars(select(AdminAction).order_by(AdminAction.id.desc()).limit(limit))).all()
