from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from app.db import repositories
from app.db.models import utc_now
from app.core.events import ReadOnlyChanged

if TYPE_CHECKING:
    from app.core.runtime import ApplicationRuntime


class AdminApplication:
    def __init__(self, runtime: ApplicationRuntime) -> None:
        self._runtime = runtime

    async def block_visitor(self, admin_id: str, visitor_id: str, minutes: int) -> None:
        async with self._runtime.session_factory() as session:
            async with session.begin():
                state = await repositories.get_moderation_state(session, visitor_id)
                state.blocked_until = utc_now() + timedelta(minutes=max(1, min(minutes, 24 * 60)))
                await repositories.add_admin_action(session, admin_id=admin_id, action='moderation.block', details={'visitor_id': visitor_id, 'minutes': minutes})

    async def audit(self, admin_id: str, action: str, details: dict[str, object] | None = None) -> None:
        """Record an administrator action without storing credentials or IPs."""
        async with self._runtime.session_factory() as session:
            async with session.begin():
                await repositories.add_admin_action(
                    session,
                    admin_id=admin_id,
                    action=action,
                    details=details or {},
                )

    async def unblock_visitor(self, admin_id: str, visitor_id: str) -> None:
        async with self._runtime.session_factory() as session:
            async with session.begin():
                state = await repositories.get_moderation_state(session, visitor_id)
                state.blocked_until = None
                state.challenge_required_until = None
                state.post_verification_watch_until = None
                state.verified_until = None
                await repositories.add_admin_action(session, admin_id=admin_id, action='moderation.unblock', details={'visitor_id': visitor_id})

    async def set_read_only(self, admin_id: str, enabled: bool) -> None:
        async with self._runtime.session_factory() as session:
            async with session.begin():
                await repositories.add_admin_action(session, admin_id=admin_id, action='canvas.read_only', details={'enabled': enabled})
        self._runtime.canvas.set_read_only(enabled)
        self._runtime.dispatcher.publish_nowait(ReadOnlyChanged(draw_enabled=not self._runtime.canvas.read_only))
