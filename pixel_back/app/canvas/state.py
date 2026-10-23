from __future__ import annotations

import asyncio
from typing import Iterable

import numpy as np
from numpy.typing import NDArray

from app.canvas.model import WHITE, CanvasRevision, normalize_color


class CanvasState:
    """In-process authoritative canvas; all mutation is coordinated by CanvasApplication."""

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self._pixels: NDArray[np.uint8] | None = None
        self._head_event_id = 0
        self.write_lock = asyncio.Lock()

    @property
    def expected_size(self) -> int:
        return self.width * self.height

    @property
    def head_event_id(self) -> int:
        return self._head_event_id

    def initialize_white(self) -> None:
        self._pixels = np.full((self.height, self.width, 3), 255, dtype=np.uint8)
        self._head_event_id = 0

    def replace_from_colors(self, colors: Iterable[str], head_event_id: int) -> None:
        values = list(colors)
        if len(values) != self.expected_size:
            raise ValueError(
                f"Canvas contains {len(values)} pixels; expected {self.expected_size}"
            )
        array = np.empty((self.height, self.width, 3), dtype=np.uint8)
        for index, raw_color in enumerate(values):
            color = normalize_color(raw_color)
            y, x = divmod(index, self.width)
            array[y, x] = (
                int(color[1:3], 16),
                int(color[3:5], 16),
                int(color[5:7], 16),
            )
        self._pixels = array
        self._head_event_id = int(head_event_id)

    def replace_from_array(self, pixels: NDArray[np.uint8], head_event_id: int) -> None:
        expected_shape = (self.height, self.width, 3)
        if pixels.shape != expected_shape or pixels.dtype != np.uint8:
            raise ValueError(f"Canvas must be uint8 with shape {expected_shape}")
        self._pixels = np.array(pixels, copy=True)
        self._head_event_id = int(head_event_id)

    def get_pixel(self, x: int, y: int) -> str:
        self._validate_coordinates(x, y)
        rgb = self._require_pixels()[y, x]
        return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"

    def apply_committed_pixel(self, x: int, y: int, color: str, event_id: int) -> None:
        self._validate_coordinates(x, y)
        normalized = normalize_color(color)
        self._require_pixels()[y, x] = (
            int(normalized[1:3], 16),
            int(normalized[3:5], 16),
            int(normalized[5:7], 16),
        )
        self._head_event_id = int(event_id)

    def apply_committed_batch(
        self,
        updates: Iterable[tuple[int, int, str, int]],
        head_event_id: int,
    ) -> None:
        pixels = self._require_pixels()
        for x, y, color, _event_id in updates:
            self._validate_coordinates(x, y)
            normalized = normalize_color(color)
            pixels[y, x] = (
                int(normalized[1:3], 16),
                int(normalized[3:5], 16),
                int(normalized[5:7], 16),
            )
        self._head_event_id = int(head_event_id)

    def capture_revision(self) -> CanvasRevision:
        return CanvasRevision(
            pixels=np.array(self._require_pixels(), copy=True),
            event_id=self._head_event_id,
        )

    def to_colors(self) -> list[str]:
        pixels = self._require_pixels()
        flat = pixels.reshape((-1, 3))
        return [f"#{r:02X}{g:02X}{b:02X}" for r, g, b in flat]

    def is_initialized(self) -> bool:
        return self._pixels is not None

    def _require_pixels(self) -> NDArray[np.uint8]:
        if self._pixels is None:
            raise RuntimeError("Canvas state is not initialized")
        return self._pixels

    def _validate_coordinates(self, x: int, y: int) -> None:
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise ValueError("coordinates are out of bounds")
