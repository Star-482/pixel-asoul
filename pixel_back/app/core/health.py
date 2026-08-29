from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class HealthState:
    ready: bool = False
    draining: bool = False
    snapshot_degraded: bool = False
    details: dict[str, str] = field(default_factory=dict)

    def snapshot(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "draining": self.draining,
            "snapshot_degraded": self.snapshot_degraded,
            "details": dict(self.details),
        }
