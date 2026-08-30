from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from datetime import timedelta

from app.abuse.risk import PlacementRisk, RiskWindow
from app.abuse.token_bucket import TokenBucket
from app.db import repositories
from app.db.models import utc_now
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
        self._challenge_degraded = False

    def set_challenge_degraded(self, degraded: bool) -> None:
        self._challenge_degraded = degraded

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
        degraded_overwrite = False
        if self.settings.abuse_mode == 'enforce':
            async with self._session_factory() as session:
                state = await repositories.get_moderation_state(session, visitor_id)
                now = utc_now()
                if state.blocked_until and state.blocked_until > now:
                    raise AbuseRejected('drawing_blocked', '当前访客暂时无法绘制', int((state.blocked_until - now).total_seconds()))
                if (
                    state.challenge_required_until
                    and state.challenge_required_until > now
                    and destructive_overwrite
                ):
                    if self._challenge_degraded:
                        degraded_overwrite = True
                    else:
                        raise AbuseRejected('challenge_required', '请先完成验证码后再覆盖他人像素')
                if len(identities) > 5 and destructive_overwrite:
                    state.challenge_required_until = now + timedelta(hours=1)
                    await session.commit()
                    raise AbuseRejected('challenge_required', '该网络需要先完成验证码后再覆盖他人像素')

        visitor_bucket = self._visitor_buckets.setdefault(
            visitor_id,
            TokenBucket(self.settings.visitor_bucket_capacity, self.settings.visitor_bucket_refill_per_second),
        )
        ip_bucket = self._ip_buckets.setdefault(
            client_ip,
            TokenBucket(self.settings.ip_bucket_capacity, self.settings.ip_bucket_refill_per_second),
        )
        overwrite_bucket: TokenBucket | None = None
        overwrite_cost = (
            1 if degraded_overwrite else risk.overwrite_cost if destructive_overwrite else 0
        )
        if overwrite_cost:
            overwrite_bucket = self._overwrite_buckets.setdefault(
                f'{visitor_id}:degraded' if degraded_overwrite else visitor_id,
                TokenBucket(
                    1 if degraded_overwrite else self.settings.overwrite_bucket_capacity,
                    1 / 30 if degraded_overwrite else 1 / self.settings.overwrite_refill_seconds,
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
            await self._record_overwrite_exhaustion(visitor_id)
            raise AbuseRejected('destructive_cooldown', '覆盖操作过于频繁', overwrite_bucket.retry_after(overwrite_cost))
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

    async def verify_challenge(self, visitor_id: str, succeeded: bool | None) -> None:
        """Update only a state decision; provider failures never count as failures."""
        if succeeded is None:
            return
        async with self._session_factory() as session:
            async with session.begin():
                state = await repositories.get_moderation_state(session, visitor_id)
                if succeeded:
                    now = utc_now()
                    state.verified_until = now + timedelta(hours=1)
                    state.post_verification_watch_until = now + timedelta(
                        minutes=self.settings.verified_risk_window_minutes
                    )
                    state.challenge_required_until = None
                    state.challenge_failures = 0
                    bucket = self._overwrite_buckets.get(visitor_id)
                    if bucket is not None:
                        bucket.tokens = bucket.capacity
                else:
                    state.challenge_failures += 1
                    if state.challenge_failures >= 3:
                        state.strike_count += 1
                        state.blocked_until = utc_now() + timedelta(minutes=30)

    async def _record_overwrite_exhaustion(self, visitor_id: str) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                state = await repositories.get_moderation_state(session, visitor_id)
                now = utc_now()
                if (
                    state.post_verification_watch_until
                    and state.post_verification_watch_until > now
                ):
                    # A successful CAPTCHA proves the request is human, not that
                    # repeatedly overwriting others' pixels is acceptable. A
                    # second exhausted overwrite budget during this short window
                    # therefore becomes a temporary drawing ban instead of a
                    # CAPTCHA loop that can be solved indefinitely.
                    state.strike_count += 1
                    state.blocked_until = now + timedelta(
                        minutes=self.settings.verified_risk_block_minutes
                    )
                    state.verified_until = None
                    state.post_verification_watch_until = None
                    state.challenge_required_until = None
                elif state.challenge_required_until and state.challenge_required_until > now:
                    state.strike_count += 1
                    hours = 6 if state.strike_count > 1 else 0.5
                    state.blocked_until = now + timedelta(hours=hours)
                else:
                    state.challenge_required_until = now + timedelta(hours=1)

    def forget_connection(self, connection_id: str) -> None:
        self._message_buckets.pop(connection_id, None)

    async def restore_recent_risk_windows(self) -> None:
        """Restore only the ten-minute risk signal; buckets intentionally reset."""
        async with self._session_factory() as session:
            rows = await repositories.list_recent_risk_pixels(session, since=utc_now() - timedelta(minutes=10))
        for row in rows:
            if row.visitor_id and row.previous_color:
                self._risk_windows.setdefault(row.visitor_id, RiskWindow()).record(row.previous_color, row.color)
