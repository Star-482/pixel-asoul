from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


COLOR_PATTERN = re.compile(r"#[0-9A-F]{6}")
WHITE = "#FFFFFF"


def normalize_color(value: str) -> str:
    color = (value or "").strip().upper()
    if not COLOR_PATTERN.fullmatch(color):
        raise ValueError("color must use #RRGGBB format")
    return color


@dataclass(frozen=True)
class PixelCommand:
    request_id: str
    x: int
    y: int
    color: str
    visitor_id: str
    visit_id: int
    client_ip: str


@dataclass(frozen=True)
class AppliedPixel:
    event_id: int
    x: int
    y: int
    color: str
    previous_color: str
    total_placed_pixels: int
    duplicate: bool = False


@dataclass(frozen=True)
class CanvasRevision:
    pixels: NDArray[np.uint8]
    event_id: int
