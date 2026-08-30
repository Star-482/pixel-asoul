import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, patch

from app.abuse.risk import RiskWindow
from app.abuse.service import AbuseGuard
from app.abuse.token_bucket import TokenBucket
from app.core.settings import Settings
from app.db.models import ModerationState
from app.db.session import AsyncSessionFactory


class _AsyncContext:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _Session:
    def begin(self):
        return _AsyncContext(self)


class _SessionFactory:
    def __call__(self):
        return _AsyncContext(_Session())


class TokenBucketTests(unittest.TestCase):
    def test_reservation_is_refundable_without_consuming_tokens(self):
        bucket = TokenBucket(2, 1)
        self.assertTrue(bucket.reserve())
        bucket.refund()
        self.assertTrue(bucket.reserve(2))

    def test_confirm_consumes_reserved_budget(self):
        bucket = TokenBucket(2, 1)
        self.assertTrue(bucket.reserve())
        bucket.confirm()
        self.assertTrue(bucket.reserve())
        self.assertFalse(bucket.reserve())


class RiskWindowTests(unittest.TestCase):
    def test_white_fill_has_no_overwrite_cost(self):
        risk = RiskWindow().assess('#FFFFFF', '#000000')
        self.assertEqual(0, risk.overwrite_cost)

    def test_high_ratio_cost_is_three_not_six(self):
        window = RiskWindow()
        for _ in range(19):
            window.record('#111111', '#222222')
        risk = window.assess('#333333', '#222222')
        self.assertEqual(3, risk.overwrite_cost)

    def test_first_same_target_overwrite_keeps_normal_cost(self):
        risk = RiskWindow().assess('#111111', '#222222')

        self.assertEqual(1, risk.overwrite_cost)
        self.assertEqual(0.0, risk.same_target_ratio)

    def test_same_target_escalates_only_after_twenty_overwrites(self):
        window = RiskWindow()
        for _ in range(19):
            window.record('#111111', '#222222')

        risk = window.assess('#333333', '#222222')

        self.assertEqual(3, risk.overwrite_cost)
        self.assertEqual(1.0, risk.same_target_ratio)

    def test_full_window_simulates_replacement_instead_of_counting_twenty_one_events(self):
        window = RiskWindow()
        for _ in range(5):
            window.record('#FFFFFF', '#111111')
        for _ in range(15):
            window.record('#111111', '#222222')

        risk = window.assess('#333333', '#444444')

        self.assertEqual(0.8, risk.recent_overwrite_ratio)
        self.assertEqual(3, risk.overwrite_cost)


class PostVerificationRiskTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_overwrite_exhaustion_after_successful_captcha_blocks(self):
        now = datetime(2026, 8, 30, tzinfo=timezone.utc)
        state = ModerationState(
            visitor_id='visitor-1', strike_count=0, challenge_failures=0
        )
        guard = AbuseGuard(
            cast(
                Settings,
                SimpleNamespace(
                    verified_risk_window_minutes=10,
                    verified_risk_block_minutes=30,
                ),
            ),
            cast(AsyncSessionFactory, _SessionFactory()),
        )

        with (
            patch(
                'app.abuse.service.repositories.get_moderation_state',
                AsyncMock(return_value=state),
            ),
            patch('app.abuse.service.utc_now', return_value=now),
        ):
            await guard.verify_challenge('visitor-1', True)
            self.assertEqual(
                state.post_verification_watch_until,
                now + timedelta(minutes=10),
            )
            self.assertEqual(state.verified_until, now + timedelta(hours=1))
            await guard._record_overwrite_exhaustion('visitor-1')

        self.assertEqual(
            state.blocked_until,
            now + timedelta(minutes=30),
        )
        self.assertIsNone(state.post_verification_watch_until)
        self.assertIsNone(state.verified_until)
        self.assertIsNone(state.challenge_required_until)
        self.assertEqual(state.strike_count, 1)

    async def test_expired_post_verification_window_requires_a_new_challenge(self):
        now = datetime(2026, 8, 30, tzinfo=timezone.utc)
        state = ModerationState(
            visitor_id='visitor-1',
            post_verification_watch_until=now - timedelta(seconds=1),
            strike_count=0,
            challenge_failures=0,
        )
        guard = AbuseGuard(
            cast(
                Settings,
                SimpleNamespace(
                    verified_risk_window_minutes=10,
                    verified_risk_block_minutes=30,
                ),
            ),
            cast(AsyncSessionFactory, _SessionFactory()),
        )

        with (
            patch(
                'app.abuse.service.repositories.get_moderation_state',
                AsyncMock(return_value=state),
            ),
            patch('app.abuse.service.utc_now', return_value=now),
        ):
            await guard._record_overwrite_exhaustion('visitor-1')

        self.assertIsNone(state.blocked_until)
        self.assertEqual(
            state.challenge_required_until,
            now + timedelta(hours=1),
        )


class RecentSelfEditTests(unittest.IsolatedAsyncioTestCase):
    async def test_recent_self_edit_skips_only_overwrite_protection(self):
        settings = cast(
            Settings,
            SimpleNamespace(
                abuse_mode='enforce',
                ws_bucket_capacity=40,
                ws_bucket_refill_per_second=10,
                visitor_bucket_capacity=12,
                visitor_bucket_refill_per_second=3,
                ip_bucket_capacity=120,
                ip_bucket_refill_per_second=30,
                overwrite_bucket_capacity=20,
                overwrite_refill_seconds=15,
            ),
        )
        state = ModerationState(
            visitor_id='visitor-1',
            challenge_required_until=datetime.now(timezone.utc) + timedelta(hours=1),
            strike_count=0,
            challenge_failures=0,
        )
        guard = AbuseGuard(settings, cast(AsyncSessionFactory, _SessionFactory()))

        with patch(
            'app.abuse.service.repositories.get_moderation_state',
            AsyncMock(return_value=state),
        ):
            reservation = await guard.reserve_draw(
                'visitor-1',
                '203.0.113.1',
                '#111111',
                '#222222',
                is_recent_self_edit=True,
            )

        self.assertEqual(0, reservation.overwrite_cost)
        self.assertIsNone(reservation.overwrite_bucket)
        self.assertTrue(reservation.is_recent_self_edit)
        await guard.commit(reservation, '#111111', '#222222')
        risk = guard._risk_windows['visitor-1'].assess('#333333', '#222222')
        self.assertEqual(1, risk.overwrite_cost)
        self.assertEqual(0.0, risk.recent_overwrite_ratio)
