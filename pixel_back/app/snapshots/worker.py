from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.canvas.state import CanvasState
from app.core.events import PixelCommitted
from app.core.health import HealthState
from app.db import repositories
from app.db.session import AsyncSessionFactory
from app.snapshots.store import SnapshotStore


@dataclass
class SnapshotWorker:
    state: CanvasState
    session_factory: AsyncSessionFactory
    store: SnapshotStore
    threshold: int
    health: HealthState

    def __post_init__(self) -> None:
        self._pending = 0
        self._last_captured_event_id = 0
        self._force_snapshot = False
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self._stopping = False

    async def start(
        self, pending_updates: int, ensure_initial_snapshot: bool = False, *, base_event_id: int = 0
    ) -> None:
        self._pending = pending_updates
        self._last_captured_event_id = base_event_id
        self._force_snapshot = ensure_initial_snapshot
        self._task = asyncio.create_task(self._run(), name='snapshot-worker')
        if self._pending >= self.threshold or self._force_snapshot:
            self._wake.set()

    async def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        if self._task is not None:
            await self._task

    async def on_pixel_committed(self, event: PixelCommitted) -> None:
        self._pending += 1
        if self._pending >= self.threshold:
            self._wake.set()

    async def on_canvas_restored(self, affected_pixels: int) -> None:
        self._pending += affected_pixels
        if self._pending >= self.threshold:
            self._wake.set()

    async def _run(self) -> None:
        backoffs = (5, 30, 300)
        failure_count = 0
        while not self._stopping:
            await self._wake.wait()
            self._wake.clear()
            while not self._stopping and (self._pending >= self.threshold or self._force_snapshot):
                async with self.state.write_lock:
                    revision = self.state.capture_revision()
                filename: str | None = None
                try:
                    filename, digest = await asyncio.to_thread(self.store.write_array, revision.pixels, revision.event_id)
                    async with self.session_factory() as session:
                        async with session.begin():
                            await repositories.create_snapshot(
                                session,
                                last_log_id=revision.event_id,
                                data_file_path=filename,
                                width=self.state.width,
                                height=self.state.height,
                                sha256=digest,
                            )
                    # Deduct precisely the events represented by this captured
                    # revision; concurrent events remain pending.
                    covered = max(0, revision.event_id - self._last_captured_event_id)
                    self._pending = max(0, self._pending - covered)
                    self._last_captured_event_id = revision.event_id
                    self._force_snapshot = False
                    failure_count = 0
                    self.health.snapshot_degraded = False
                except Exception:
                    if filename is not None:
                        try:
                            self.store.path_for(filename).unlink(missing_ok=True)
                        except Exception:
                            pass
                    failure_count += 1
                    self.health.snapshot_degraded = True
                    try:
                        await asyncio.wait_for(
                            self._wake.wait(),
                            timeout=backoffs[min(failure_count - 1, len(backoffs) - 1)],
                        )
                    except asyncio.TimeoutError:
                        pass
                    self._wake.clear()
                    if self._stopping:
                        break
                    self._wake.set()
                    break
