from __future__ import annotations

import asyncio

from app.db import repositories
from app.db.session import AsyncSessionFactory
from app.stats.model import PublicStats


class StatsApplication:
    def __init__(self, session_factory: AsyncSessionFactory) -> None:
        self._session_factory = session_factory
        self._online_users = 0
        self._lock = asyncio.Lock()
        self._total_visits = 0
        self._total_placed_pixels = 0

    async def initialize(self) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                counters = await repositories.get_counters(session)
                self._total_visits = counters.total_visits
                self._total_placed_pixels = counters.total_placed_pixels

    async def connection_opened(self) -> PublicStats:
        async with self._lock:
            self._online_users += 1
            return self.current()

    def visit_committed(self, total_visits: int) -> PublicStats:
        self._total_visits = total_visits
        return self.current()

    async def connection_closed(self) -> PublicStats:
        async with self._lock:
            self._online_users = max(0, self._online_users - 1)
            return self.current()

    async def pixel_committed(self, total_placed_pixels: int) -> PublicStats:
        self._total_placed_pixels = total_placed_pixels
        return self.current()

    def current(self) -> PublicStats:
        return PublicStats(
            online_users=self._online_users,
            total_visits=self._total_visits,
            total_placed_pixels=self._total_placed_pixels,
        )
