from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import uuid4

from fastapi import WebSocket


@dataclass(slots=True)
class RealtimeConnection:
    id: str
    visitor_id: str
    websocket: WebSocket
    queue: asyncio.Queue[dict | None]
    writer: asyncio.Task[None]
    visit_id: int | None = None
    closed: bool = False


class RealtimeHub:
    def __init__(self, queue_size: int, send_timeout: float) -> None:
        self._queue_size = queue_size
        self._send_timeout = send_timeout
        self._connections: dict[str, RealtimeConnection] = {}
        self._lock = asyncio.Lock()

    async def register(
        self, websocket: WebSocket, visitor_id: str, first_message: dict, *, connection_id: str | None = None
    ) -> RealtimeConnection:
        await websocket.accept()
        connection_id = connection_id or str(uuid4())
        queue: asyncio.Queue[dict | None] = asyncio.Queue(self._queue_size)
        # session.ready is placed before the writer is allowed to observe its queue.
        queue.put_nowait(first_message)
        connection = RealtimeConnection(
            id=connection_id,
            visitor_id=visitor_id,
            websocket=websocket,
            queue=queue,
            writer=asyncio.create_task(self._writer(connection_id, websocket, queue), name=f'ws-writer-{connection_id}'),
        )
        async with self._lock:
            self._connections[connection_id] = connection
        return connection

    async def send(self, connection_id: str, payload: dict) -> bool:
        async with self._lock:
            connection = self._connections.get(connection_id)
            if connection is None or connection.closed:
                return False
            try:
                connection.queue.put_nowait(payload)
                return True
            except asyncio.QueueFull:
                pass
        await self.close(connection_id, 1013, 'client is too slow')
        return False

    async def broadcast(self, payload: dict) -> None:
        async with self._lock:
            connection_ids = list(self._connections)
        await asyncio.gather(*(self.send(connection_id, payload) for connection_id in connection_ids), return_exceptions=True)

    async def close(self, connection_id: str, code: int = 1000, reason: str = '') -> RealtimeConnection | None:
        async with self._lock:
            connection = self._connections.pop(connection_id, None)
        if connection is None or connection.closed:
            return connection
        connection.closed = True
        try:
            connection.queue.put_nowait(None)
        except asyncio.QueueFull:
            pass
        if connection.writer is not asyncio.current_task():
            connection.writer.cancel()
            await asyncio.gather(connection.writer, return_exceptions=True)
        try:
            await connection.websocket.close(code=code, reason=reason)
        except Exception:
            pass
        return connection

    async def close_all(self) -> list[RealtimeConnection]:
        async with self._lock:
            ids = list(self._connections)
        closed = await asyncio.gather(*(self.close(item, 1001, 'server shutting down') for item in ids))
        return [item for item in closed if item is not None]

    async def _writer(self, connection_id: str, websocket: WebSocket, queue: asyncio.Queue[dict | None]) -> None:
        try:
            while True:
                payload = await queue.get()
                try:
                    if payload is None:
                        return
                    await asyncio.wait_for(websocket.send_json(payload), timeout=self._send_timeout)
                finally:
                    queue.task_done()
        except Exception:
            # Do not await ourselves. Removing it lets the endpoint close its visit.
            async with self._lock:
                connection = self._connections.pop(connection_id, None)
                if connection is not None:
                    connection.closed = True
            try:
                await websocket.close(code=1013, reason='send timeout')
            except Exception:
                pass
