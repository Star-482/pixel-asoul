from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class TokenBucket:
    capacity: float
    refill_per_second: float
    tokens: float | None = None
    updated_at: float | None = None
    reserved: float = 0.0

    def _refresh(self) -> None:
        now = time.monotonic()
        if self.tokens is None:
            self.tokens = self.capacity
            self.updated_at = now
            return
        elapsed = max(0.0, now - (self.updated_at or now))
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_second)
        self.updated_at = now

    def reserve(self, cost: float = 1.0) -> bool:
        self._refresh()
        if self.tokens is None or self.tokens - self.reserved < cost:
            return False
        self.reserved += cost
        return True

    def confirm(self, cost: float = 1.0) -> None:
        self._refresh()
        self.reserved = max(0.0, self.reserved - cost)
        self.tokens = max(0.0, (self.tokens or 0.0) - cost)

    def refund(self, cost: float = 1.0) -> None:
        self.reserved = max(0.0, self.reserved - cost)

    def retry_after(self, cost: float = 1.0) -> int:
        self._refresh()
        deficit = max(0.0, cost - ((self.tokens or 0.0) - self.reserved))
        return max(1, int(-(-deficit // self.refill_per_second)))
