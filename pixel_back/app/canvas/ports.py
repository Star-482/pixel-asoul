from __future__ import annotations

from typing import Protocol

from app.canvas.model import CanvasRevision, PixelCommand


class PixelRepository(Protocol):
    async def find_by_request_id(self, request_id: str): ...

    async def create_pixel(self, command: PixelCommand, previous_color: str, source: str = "user"):
        ...

    async def increment_user_pixels(self) -> int: ...


class CanvasCapturePort(Protocol):
    async def capture_revision(self) -> CanvasRevision: ...
