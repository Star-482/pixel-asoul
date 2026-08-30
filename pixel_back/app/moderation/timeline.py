from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import numpy as np
from numpy.typing import NDArray
from sqlalchemy import Select, func, literal_column, select

from app.canvas.state import CanvasState
from app.db.models import PixelLog
from app.db.session import AsyncSessionFactory
from app.snapshots.store import SnapshotStore


async def event_id_at_time(session_factory: AsyncSessionFactory, target: datetime) -> int:
    async with session_factory() as session:
        value = await session.scalar(select(func.coalesce(func.max(PixelLog.id), 0)).where(PixelLog.created_at <= target))
        return value if isinstance(value, int) else 0


async def modification_density(
    session_factory: AsyncSessionFactory, start: datetime, end: datetime
) -> list[dict[str, str | int]]:
    """Return contiguous, time-proportional density buckets for the timeline.

    Empty intervals are intentionally retained.  The client positions bars and
    snapshot markers using the same ``start``/``end`` values, so omitting a
    quiet interval would visually compress time and misalign the markers.
    """
    interval = _density_interval(start, end)
    async with session_factory() as session:
        rows = await session.execute(_modification_density_statement(start, end))
    hourly_counts = {
        _as_utc(bucket): int(count)
        for bucket, count in rows
        if isinstance(bucket, datetime)
    }
    return _continuous_density_buckets(start, end, interval, hourly_counts)


def _density_interval(start: datetime, end: datetime) -> timedelta:
    duration = end - start
    if duration <= timedelta(days=3):
        return timedelta(hours=1)
    if duration <= timedelta(days=21):
        return timedelta(hours=6)
    if duration <= timedelta(days=180):
        return timedelta(days=1)
    return timedelta(days=7)


def _continuous_density_buckets(
    start: datetime,
    end: datetime,
    interval: timedelta,
    hourly_counts: dict[datetime, int],
) -> list[dict[str, str | int]]:
    """Fill quiet intervals while preserving the exact selected time range."""
    if end <= start:
        return []
    ranges: list[tuple[datetime, datetime]] = []
    cursor = start
    boundary = _next_interval_boundary(start, interval)
    while cursor < end:
        bucket_end = min(boundary, end)
        ranges.append((cursor, bucket_end))
        cursor = bucket_end
        boundary = cursor + interval

    counts = [0] * len(ranges)
    for hour, count in hourly_counts.items():
        hour_end = hour + timedelta(hours=1)
        for index, (bucket_start, bucket_end) in enumerate(ranges):
            if hour < bucket_end and hour_end > bucket_start:
                counts[index] += count
                break
    return [
        {
            'start': bucket_start.isoformat(),
            'end': bucket_end.isoformat(),
            'count': counts[index],
        }
        for index, (bucket_start, bucket_end) in enumerate(ranges)
    ]


def _next_interval_boundary(value: datetime, interval: timedelta) -> datetime:
    """Return the next UTC-aligned hour, six-hour, day, or week boundary."""
    value = _as_utc(value)
    if interval == timedelta(hours=1):
        floor = value.replace(minute=0, second=0, microsecond=0)
    elif interval == timedelta(hours=6):
        floor = value.replace(
            hour=value.hour - value.hour % 6,
            minute=0,
            second=0,
            microsecond=0,
        )
    elif interval == timedelta(days=1):
        floor = value.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        day_floor = value.replace(hour=0, minute=0, second=0, microsecond=0)
        floor = day_floor - timedelta(days=day_floor.weekday())
    return floor + interval


def _as_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _modification_density_statement(start: datetime, end: datetime) -> Select:
    """Build one stable PostgreSQL expression for SELECT/GROUP BY/ORDER BY.

    Passing ``'hour'`` to three separate ``func.date_trunc`` calls produces
    three bind parameters. PostgreSQL cannot prove those parameters equal when
    validating the GROUP BY clause, even though each has the value ``hour``.
    The SQL literal and shared expression avoid that mismatch.
    """
    bucket = func.date_trunc(literal_column("'hour'"), PixelLog.created_at).label('bucket')
    return (
        select(bucket, func.count(PixelLog.id))
        .where(PixelLog.created_at >= start, PixelLog.created_at < end)
        .group_by(bucket)
        .order_by(bucket)
    )


async def build_historical_array(
    *,
    event_id: int,
    state: CanvasState,
    session_factory: AsyncSessionFactory,
    snapshot_store: SnapshotStore,
) -> NDArray[np.uint8]:
    """Reconstruct a point-in-time state from the closest valid snapshot."""
    from app.db import repositories

    base_event_id = 0
    array = np.full((state.height, state.width, 3), 255, dtype=np.uint8)
    async with session_factory() as session:
        snapshot = await repositories.get_snapshot_at_or_before(session, event_id)
    if snapshot is not None:
        array = await asyncio.to_thread(snapshot_store.load_array, snapshot.data_file_path, snapshot.sha256 or None)
        base_event_id = snapshot.last_log_id

    cursor = base_event_id
    while cursor < event_id:
        async with session_factory() as session:
            logs = await repositories.get_pixels_after(session, cursor, through=event_id, limit=5000)
        if not logs:
            break
        for row in logs:
            if 0 <= row.x < state.width and 0 <= row.y < state.height:
                array[row.y, row.x] = tuple(int(row.color[index:index + 2], 16) for index in (1, 3, 5))
        cursor = logs[-1].id
        if len(logs) < 5000:
            break
    return array
