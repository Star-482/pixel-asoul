from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from datetime import timedelta

from app.abuse.risk import PlacementRisk, RiskWindow
from app.abuse.token_bucket import TokenBucket
from app.db import repositories
from app.db.models import ModerationState, utc_now
from app.db.session import AsyncSessionFactory
from app.core.settings import Settings


class AbuseRejected(Exception):
    def __init__(self, code: str, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retry_after = retry_after


@dataclass(slots=True)
class DrawReservation:
    visitor_id: str
    visitor_bucket: TokenBucket | None
    ip_bucket: TokenBucket | None
    overwrite_bucket: TokenBucket | None
    overwrite_cost: int
    risk: PlacementRisk
    observe_only: bool
    is_recent_self_edit: bool


class AbuseGuard:
    """Process-local anti-abuse policy; persisted moderation survives restarts."""

    def __init__(self, settings: Settings, session_factory: AsyncSessionFactory) -> None:
        self.settings = settings
        self._session_factory = session_factory
        self._message_buckets: dict[str, TokenBucket] = {}
        self._visitor_buckets: dict[str, TokenBucket] = {}
        self._ip_buckets: dict[str, TokenBucket] = {}
        self._overwrite_buckets: dict[str, TokenBucket] = {}
        self._risk_windows: dict[str, RiskWindow] = {}
        self._ip_identities: dict[str, dict[str, float]] = {}

    OVERWRITE_NOTICE = '请勿覆盖他人作品，如是恢复自己的作品请联系站长'

    def allow_message(self, connection_id: str) -> None:
        bucket = self._message_buckets.setdefault(
            connection_id,
            TokenBucket(self.settings.ws_bucket_capacity, self.settings.ws_bucket_refill_per_second),
        )
        if not bucket.reserve():
            raise AbuseRejected('rate_limited', '消息发送过于频繁', bucket.retry_after())
        bucket.confirm()

    async def reserve_draw(
        self,
        visitor_id: str,
        client_ip: str,
        previous_color: str,
        new_color: str,
        *,
        is_recent_self_edit: bool = False,
    ) -> DrawReservation:
        risk = self._risk_windows.setdefault(visitor_id, RiskWindow()).assess(previous_color, new_color)
        destructive_overwrite = bool(risk.overwrite_cost and not is_recent_self_edit)
        identities = self._ip_identities.setdefault(client_ip, {})
        cutoff = monotonic() - 3600
        for known_id, seen_at in tuple(identities.items()):
            if seen_at < cutoff:
                identities.pop(known_id, None)
        identities[visitor_id] = monotonic()
        if self.settings.abuse_mode == 'enforce':
            async with self._session_factory() as session:
                state = await repositories.get_moderation_state(session, visitor_id)
                now = utc_now()
                if state.blocked_until and state.blocked_until > now:
                    raise AbuseRejected('drawing_blocked', '当前访客暂时无法绘制', int((state.blocked_until - now).total_seconds()))
                if (
                    state.overwrite_cooldown_until
                    and state.overwrite_cooldown_until > now
                    and destructive_overwrite
                ):
                    raise AbuseRejected(
                        'destructive_cooldown',
                        self.OVERWRITE_NOTICE,
                        int((state.overwrite_cooldown_until - now).total_seconds()) + 1,
                    )
                if len(identities) > 5 and destructive_overwrite:
                    cooldown = self._apply_overwrite_exhaustion(state, now)
                    await session.commit()
                    raise AbuseRejected('destructive_cooldown', self.OVERWRITE_NOTICE, int(cooldown.total_seconds()))

        visitor_bucket = self._visitor_buckets.setdefault(
            visitor_id,
            TokenBucket(self.settings.visitor_bucket_capacity, self.settings.visitor_bucket_refill_per_second),
        )
        ip_bucket = self._ip_buckets.setdefault(
            client_ip,
            TokenBucket(self.settings.ip_bucket_capacity, self.settings.ip_bucket_refill_per_second),
        )
        overwrite_bucket: TokenBucket | None = None
        overwrite_cost = risk.overwrite_cost if destructive_overwrite else 0
        if overwrite_cost:
            overwrite_bucket = self._overwrite_buckets.setdefault(
                visitor_id,
                TokenBucket(
                    self.settings.overwrite_bucket_capacity,
                    1 / self.settings.overwrite_refill_seconds,
                ),
            )

        if self.settings.abuse_mode == 'observe':
            # Keep calculating the real decision while intentionally letting it pass.
            return DrawReservation(
                visitor_id=visitor_id,
                visitor_bucket=None,
                ip_bucket=None,
                overwrite_bucket=None,
                overwrite_cost=overwrite_cost,
                risk=risk,
                observe_only=True,
                is_recent_self_edit=is_recent_self_edit,
            )

        if not visitor_bucket.reserve():
            raise AbuseRejected('rate_limited', '绘制速度过快', visitor_bucket.retry_after())
        if not ip_bucket.reserve():
            visitor_bucket.refund()
            raise AbuseRejected('rate_limited', '该网络绘制过于频繁', ip_bucket.retry_after())
        if overwrite_bucket is not None and not overwrite_bucket.reserve(overwrite_cost):
            visitor_bucket.refund()
            ip_bucket.refund()
            cooldown_seconds = await self._record_overwrite_exhaustion(visitor_id)
            raise AbuseRejected('destructive_cooldown', self.OVERWRITE_NOTICE, cooldown_seconds)
        return DrawReservation(
            visitor_id=visitor_id,
            visitor_bucket=visitor_bucket,
            ip_bucket=ip_bucket,
            overwrite_bucket=overwrite_bucket,
            overwrite_cost=overwrite_cost,
            risk=risk,
            observe_only=False,
            is_recent_self_edit=is_recent_self_edit,
        )

    async def commit(self, reservation: DrawReservation, previous_color: str, new_color: str) -> None:
        if not reservation.observe_only:
            assert reservation.visitor_bucket is not None and reservation.ip_bucket is not None
            reservation.visitor_bucket.confirm()
            reservation.ip_bucket.confirm()
            if reservation.overwrite_bucket is not None:
                reservation.overwrite_bucket.confirm(reservation.overwrite_cost)
        if not reservation.is_recent_self_edit:
            self._risk_windows.setdefault(reservation.visitor_id, RiskWindow()).record(
                previous_color, new_color
            )

    def refund(self, reservation: DrawReservation) -> None:
        if reservation.observe_only:
            return
        assert reservation.visitor_bucket is not None and reservation.ip_bucket is not None
        reservation.visitor_bucket.refund()
        reservation.ip_bucket.refund()
        if reservation.overwrite_bucket is not None:
            reservation.overwrite_bucket.refund(reservation.overwrite_cost)

    def _apply_overwrite_exhaustion(self, state: ModerationState, now) -> timedelta:
        """Escalate the persisted overwrite cooldown on a loaded state row.

        The first exhaustion starts a short cooldown followed by an
        observation window.  Another exhaustion inside that window means the
        visitor kept mass-overwriting after being warned, so the cooldown
        escalates to the configured maximum instead of repeating the short
        one indefinitely.
        """
        watching = state.overwrite_watch_until and state.overwrite_watch_until > now
        if watching:
            cooldown = timedelta(minutes=self.settings.overwrite_escalation_minutes)
            state.strike_count += 1
        else:
            cooldown = timedelta(seconds=self.settings.overwrite_cooldown_seconds)
        state.overwrite_cooldown_until = now + cooldown
        state.overwrite_watch_until = state.overwrite_cooldown_until + timedelta(
            minutes=self.settings.overwrite_watch_minutes
        )
        return cooldown

    async def _record_overwrite_exhaustion(self, visitor_id: str) -> int:
        """Persist the overwrite cooldown escalation and return its seconds."""
        async with self._session_factory() as session:
            async with session.begin():
                state = await repositories.get_moderation_state(session, visitor_id)
                cooldown = self._apply_overwrite_exhaustion(state, utc_now())
                return int(cooldown.total_seconds())

    def forget_connection(self, connection_id: str) -> None:
        self._message_buckets.pop(connection_id, None)

    async def restore_recent_risk_windows(self) -> None:
        """Restore only the ten-minute risk signal; buckets intentionally reset."""
        async with self._session_factory() as session:
            rows = await repositories.list_recent_risk_pixels(session, since=utc_now() - timedelta(minutes=10))
        for row in rows:
            if row.visitor_id and row.previous_color:
                self._risk_windows.setdefault(row.visitor_id, RiskWindow()).record(row.previous_color, row.color)
