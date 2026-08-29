from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, TypeAlias


@dataclass(frozen=True)
class PixelCommitted:
    event_id: int
    x: int
    y: int
    color: str
    total_placed_pixels: int
    source: str = "user"


@dataclass(frozen=True)
class VisitCommitted:
    stats: dict[str, int]


@dataclass(frozen=True)
class ConnectionClosed:
    stats: dict[str, int]


@dataclass(frozen=True)
class CanvasRestored:
    event_id: int
    restore_operation_id: str
    affected_pixels: int


@dataclass(frozen=True)
class ReadOnlyChanged:
    draw_enabled: bool


DomainEvent: TypeAlias = PixelCommitted | VisitCommitted | ConnectionClosed | CanvasRestored | ReadOnlyChanged
EventHandler = Callable[[DomainEvent], Awaitable[None]]


class OrderedEventDispatcher:
    """Serialize post-commit side effects without holding the canvas lock."""

    def __init__(self, maxsize: int) -> None:
        self._queue: asyncio.Queue[DomainEvent | None] = asyncio.Queue(maxsize=maxsize)
        self._handlers: list[EventHandler] = []
        self._task: asyncio.Task[None] | None = None

    def subscribe(self, handler: EventHandler) -> None:
        self._handlers.append(handler)

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="ordered-event-dispatcher")

    def publish_nowait(self, event: DomainEvent) -> None:
        self._queue.put_nowait(event)

    async def stop(self) -> None:
        if self._task is None:
            return
        await self._queue.put(None)
        await self._task
        self._task = None

    async def _run(self) -> None:
        while True:
            event = await self._queue.get()
            try:
                if event is None:
                    return
                for handler in tuple(self._handlers):
                    await handler(event)
            finally:
                self._queue.task_done()
