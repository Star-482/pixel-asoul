from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PublicStats:
    online_users: int
    total_visits: int
    total_placed_pixels: int

    def as_dict(self) -> dict[str, int]:
        return {
            'online_users': self.online_users,
            'total_visits': self.total_visits,
            'total_placed_pixels': self.total_placed_pixels,
        }
