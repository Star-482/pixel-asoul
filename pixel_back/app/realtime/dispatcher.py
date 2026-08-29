from __future__ import annotations

from app.core.events import CanvasRestored, ConnectionClosed, DomainEvent, PixelCommitted, ReadOnlyChanged, VisitCommitted
from app.realtime.hub import RealtimeHub
from app.snapshots.worker import SnapshotWorker
from app.stats.service import StatsApplication


class RealtimeEventHandler:
    def __init__(self, hub: RealtimeHub, snapshot_worker: SnapshotWorker, stats: StatsApplication) -> None:
        self._hub = hub
        self._snapshot_worker = snapshot_worker
        self._stats = stats

    async def __call__(self, event: DomainEvent) -> None:
        if isinstance(event, PixelCommitted):
            await self._stats.pixel_committed(event.total_placed_pixels)
            await self._hub.broadcast({
                'type': 'pixel.updated',
                'data': {
                    'event_id': event.event_id,
                    'x': event.x,
                    'y': event.y,
                    'color': event.color,
                    'total_placed_pixels': event.total_placed_pixels,
                },
            })
            await self._snapshot_worker.on_pixel_committed(event)
        elif isinstance(event, (VisitCommitted, ConnectionClosed)):
            await self._hub.broadcast({'type': 'stats.updated', 'data': event.stats})
        elif isinstance(event, CanvasRestored):
            await self._snapshot_worker.on_canvas_restored(event.affected_pixels)
            await self._hub.broadcast({
                'type': 'canvas.reload',
                'data': {'event_id': event.event_id, 'restore_operation_id': event.restore_operation_id},
            })
        elif isinstance(event, ReadOnlyChanged):
            await self._hub.broadcast({'type': 'canvas.read_only', 'data': {'draw_enabled': event.draw_enabled}})
