"""Verify and reconcile legacy snapshot filename collisions.

The pre-V2 backend named PNG files to the second.  Two snapshots created in
the same second could therefore create two database rows for one file, while
the later write replaced the file.  This tool never guesses which row is
correct: it rebuilds the canvas at every candidate high-water mark and
compares that array with the file on disk.

Run after ``alembic upgrade head`` with ``--apply``.  Without that flag the
tool is read-only and reports the changes it would make.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sqlalchemy import func, select, update

# Support both `python scripts/...` in Docker and local runs.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.canvas.model import normalize_color
from app.core.settings import Settings
from app.db import repositories
from app.db.models import CanvasSnapshot
from app.db.session import AsyncSessionFactory, create_database
from app.snapshots.store import SnapshotStore


@dataclass(frozen=True, slots=True)
class Reconciliation:
    path: str
    keep_id: int | None
    invalidate_ids: tuple[int, ...]
    width: int | None = None
    height: int | None = None
    sha256: str | None = None


async def _rebuild_to(
    session_factory: AsyncSessionFactory,
    *,
    width: int,
    height: int,
    event_id: int,
) -> np.ndarray:
    """Rebuild a legacy canvas deterministically from the immutable log."""
    canvas = np.full((height, width, 3), 255, dtype=np.uint8)
    cursor = 0
    while True:
        async with session_factory() as session:
            logs = await repositories.get_pixels_after(
                session, cursor, through=event_id, limit=5000
            )
        if not logs:
            return canvas
        for log in logs:
            color = normalize_color(log.color)
            canvas[log.y, log.x] = (
                int(color[1:3], 16),
                int(color[3:5], 16),
                int(color[5:7], 16),
            )
        cursor = logs[-1].id
        if len(logs) < 5000:
            return canvas


async def _duplicate_groups(session_factory: AsyncSessionFactory) -> list[tuple[str, list[CanvasSnapshot]]]:
    async with session_factory() as session:
        duplicate_paths = (
            select(CanvasSnapshot.data_file_path)
            .where(CanvasSnapshot.status == 'valid')
            .group_by(CanvasSnapshot.data_file_path)
            .having(func.count(CanvasSnapshot.id) > 1)
        )
        paths = list((await session.scalars(duplicate_paths)).all())
        groups: list[tuple[str, list[CanvasSnapshot]]] = []
        for path in paths:
            snapshots = list(
                (
                    await session.scalars(
                        select(CanvasSnapshot)
                        .where(
                            CanvasSnapshot.status == 'valid',
                            CanvasSnapshot.data_file_path == path,
                        )
                        .order_by(CanvasSnapshot.last_log_id, CanvasSnapshot.id)
                    )
                ).all()
            )
            groups.append((path, snapshots))
    return groups


async def _plan_group(
    path: str,
    snapshots: Sequence[CanvasSnapshot],
    *,
    settings: Settings,
    store: SnapshotStore,
    session_factory: AsyncSessionFactory,
) -> Reconciliation | None:
    """Return a proved metadata update, or ``None`` when the file is ambiguous."""
    try:
        disk_path = store.path_for(path)
    except Exception as error:
        print(f'{path}: unsafe metadata path ({error}); no rows were changed')
        return None
    if not disk_path.is_file():
        print(f'{path}: file is missing; all {len(snapshots)} metadata rows will be invalidated')
        return Reconciliation(path=path, keep_id=None, invalidate_ids=tuple(row.id for row in snapshots))
    try:
        actual = await asyncio.to_thread(store.load_array, path)
        checksum = await asyncio.to_thread(store.checksum, path)
    except Exception as error:
        print(f'{path}: file cannot be verified ({error}); no rows were changed')
        return None

    matches: list[CanvasSnapshot] = []
    for snapshot in snapshots:
        expected = await _rebuild_to(
            session_factory,
            width=settings.canvas_width,
            height=settings.canvas_height,
            event_id=snapshot.last_log_id,
        )
        if np.array_equal(actual, expected):
            matches.append(snapshot)

    if not matches:
        ids = ', '.join(str(row.id) for row in snapshots)
        heads = ', '.join(str(row.last_log_id) for row in snapshots)
        print(f'{path}: no candidate matches file (rows {ids}; event IDs {heads})')
        return None

    # Multiple matching high-water marks are semantically equivalent (the log
    # segment made no visible change).  Retaining the newest one maximises the
    # replay starting point without inventing state.
    keep = max(matches, key=lambda row: (row.last_log_id, row.id))
    invalid = tuple(row.id for row in snapshots if row.id != keep.id)
    print(
        f'{path}: verified row {keep.id} at event {keep.last_log_id}; '
        f'invalidate {list(invalid)}'
    )
    return Reconciliation(
        path=path,
        keep_id=keep.id,
        invalidate_ids=invalid,
        width=settings.canvas_width,
        height=settings.canvas_height,
        sha256=checksum,
    )


async def _apply(session_factory: AsyncSessionFactory, changes: Sequence[Reconciliation]) -> None:
    async with session_factory() as session:
        async with session.begin():
            for change in changes:
                if change.keep_id is not None:
                    await session.execute(
                        update(CanvasSnapshot)
                        .where(CanvasSnapshot.id == change.keep_id)
                        .values(
                            status='valid',
                            width=change.width,
                            height=change.height,
                            sha256=change.sha256,
                        )
                    )
                if change.invalidate_ids:
                    await session.execute(
                        update(CanvasSnapshot)
                        .where(CanvasSnapshot.id.in_(change.invalidate_ids))
                        .values(status='invalid')
                    )


async def main(apply: bool) -> int:
    settings = Settings.from_environment()
    engine, session_factory = create_database(settings.database_url)
    store = SnapshotStore(
        settings.snapshot_directory, settings.canvas_width, settings.canvas_height
    )
    try:
        groups = await _duplicate_groups(session_factory)
        if not groups:
            print('No valid duplicate snapshot paths found.')
            return 0

        changes: list[Reconciliation] = []
        unresolved = False
        for path, snapshots in groups:
            change = await _plan_group(
                path,
                snapshots,
                settings=settings,
                store=store,
                session_factory=session_factory,
            )
            if change is None:
                unresolved = True
            else:
                changes.append(change)
        if unresolved:
            print('No database metadata was changed. Restore the affected snapshot file from backup and retry.')
            return 1
        if not apply:
            print('Read-only check passed. Re-run with --apply to persist the verified changes.')
            return 0
        await _apply(session_factory, changes)
        print(f'Reconciled {len(changes)} duplicate snapshot file group(s).')
        return 0
    finally:
        await engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='write verified metadata changes')
    arguments = parser.parse_args()
    raise SystemExit(asyncio.run(main(arguments.apply)))
