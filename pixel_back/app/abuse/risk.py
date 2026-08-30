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
    """Recent operations and the last 20 overwrites for one visitor.

    The two signals intentionally use separate evidence windows: broad
    overwrite ratio considers the latest 20 drawing operations, while the
    same-target pattern requires 20 actual overwrite operations.  This keeps
    a handful of normal same-colour repairs from being treated as destruction.
    """

    def __init__(self) -> None:
        self._events: deque[tuple[float, bool, str]] = deque(maxlen=20)
        self._overwrites: deque[tuple[float, str]] = deque(maxlen=20)

    def assess(self, previous_color: str, new_color: str) -> PlacementRisk:
        self._expire()
        overwrite = previous_color != '#FFFFFF' and previous_color != new_color
        if not overwrite:
            return PlacementRisk(0, self._overwrite_ratio(list(self._events)), 0.0)
        candidate_events = [*self._events, (monotonic(), True, new_color)][-20:]
        overwrite_ratio = self._overwrite_ratio(candidate_events)
        candidate_targets = [target for _, target in [*self._overwrites, (monotonic(), new_color)][-20:]]
        same_target_ratio = self._same_target_ratio(candidate_targets)
        return PlacementRisk(3 if overwrite_ratio >= 0.8 or same_target_ratio >= 0.8 else 1, overwrite_ratio, same_target_ratio)

    def record(self, previous_color: str, new_color: str) -> None:
        self._expire()
        timestamp = monotonic()
        overwrite = previous_color != '#FFFFFF' and previous_color != new_color
        self._events.append((timestamp, overwrite, new_color))
        if overwrite:
            self._overwrites.append((timestamp, new_color))

    def _expire(self) -> None:
        cutoff = monotonic() - 600
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()
        while self._overwrites and self._overwrites[0][0] < cutoff:
            self._overwrites.popleft()

    @staticmethod
    def _overwrite_ratio(events: list[tuple[float, bool, str]] | None = None) -> float:
        events = events or []
        count = len(events)
        if count < 20:
            return 0.0
        overwrites = sum(1 for _, was_overwrite, _ in events if was_overwrite)
        return overwrites / count

    @staticmethod
    def _same_target_ratio(targets: list[str]) -> float:
        if len(targets) < 20:
            return 0.0
        return max(targets.count(item) / len(targets) for item in set(targets))
