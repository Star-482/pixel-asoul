from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from time import monotonic


@dataclass(frozen=True, slots=True)
class PlacementRisk:
    overwrite_cost: int
    recent_overwrite_ratio: float
    same_target_ratio: float


class RiskWindow:
    """The last 20 operations in the last ten minutes for one visitor."""

    def __init__(self) -> None:
        self._events: deque[tuple[float, bool, str]] = deque(maxlen=20)

    def assess(self, previous_color: str, new_color: str) -> PlacementRisk:
        self._expire()
        overwrite = previous_color != '#FFFFFF' and previous_color != new_color
        if not overwrite:
            return PlacementRisk(0, self._overwrite_ratio(), 0.0)
        overwrite_ratio = self._overwrite_ratio(include_current=True)
        targets = [target for _, was_overwrite, target in self._events if was_overwrite]
        targets.append(new_color)
        same_target_ratio = max((targets.count(item) / len(targets) for item in set(targets)), default=0.0)
        return PlacementRisk(3 if overwrite_ratio >= 0.8 or same_target_ratio >= 0.8 else 1, overwrite_ratio, same_target_ratio)

    def record(self, previous_color: str, new_color: str) -> None:
        self._expire()
        self._events.append((monotonic(), previous_color != '#FFFFFF' and previous_color != new_color, new_color))

    def _expire(self) -> None:
        cutoff = monotonic() - 600
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()

    def _overwrite_ratio(self, include_current: bool = False) -> float:
        count = len(self._events) + int(include_current)
        if count < 20:
            return 0.0
        overwrites = sum(1 for _, was_overwrite, _ in self._events if was_overwrite) + int(include_current)
        return overwrites / count
