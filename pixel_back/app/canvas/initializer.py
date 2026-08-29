"""Startup recovery: valid snapshot first, then ordered database replay."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.canvas.state import CanvasState
from app.db import repositories
from app.db.session import AsyncSessionFactory
from app.snapshots.store import SnapshotStore


@dataclass(frozen=True, slots=True)
class CanvasInitialization:
    latest_log_id: int
    restored_snapshot_log_id: int
    snapshot_refresh_required: bool


async def initialize_canvas(
    state: CanvasState,
    session_factory: AsyncSessionFactory,
    store: SnapshotStore,
) -> CanvasInitialization:
    """Recover state without mutating or deleting historical metadata."""
    state.initialize_white()
    restored_id = 0
    found_snapshot = False
    async with session_factory() as session:
        snapshots = await repositories.list_snapshots_newest(session)

    for snapshot in snapshots:
        try:
            if snapshot.width not in (None, state.width) or snapshot.height not in (None, state.height):
                raise ValueError('snapshot metadata dimensions do not match the configured canvas')
            array = await asyncio.to_thread(
                store.load_array, snapshot.data_file_path, snapshot.sha256 or None
            )
            async with state.write_lock:
                state.replace_from_array(array, snapshot.last_log_id)
            if snapshot.width is None or snapshot.height is None or snapshot.sha256 is None:
                digest = await asyncio.to_thread(store.checksum, snapshot.data_file_path)
                async with session_factory() as session:
                    async with session.begin():
                        await repositories.update_snapshot_verification(
                            session, snapshot.id, width=state.width, height=state.height, sha256=digest
                        )
            restored_id = snapshot.last_log_id
            found_snapshot = True
            break
        except Exception:
            async with session_factory() as session:
                async with session.begin():
                    await repositories.mark_snapshot_invalid(session, snapshot.id)

    cursor = restored_id
    while True:
        async with session_factory() as session:
            logs = await repositories.get_pixels_after(session, cursor, limit=5000)
        if not logs:
            break
        async with state.write_lock:
            for log in logs:
                if 0 <= log.x < state.width and 0 <= log.y < state.height:
                    state.apply_committed_pixel(log.x, log.y, log.color, log.id)
        cursor = logs[-1].id
        if len(logs) < 5000:
            break

    async with session_factory() as session:
        latest_log_id = await repositories.get_latest_pixel_id(session)
    return CanvasInitialization(
        latest_log_id=latest_log_id,
        restored_snapshot_log_id=restored_id,
        snapshot_refresh_required=not found_snapshot,
    )
