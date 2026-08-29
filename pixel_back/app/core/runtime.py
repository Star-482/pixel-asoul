from __future__ import annotations

from time import monotonic
from sqlalchemy import text

from app.admin.auth import AdminAuth
from app.admin.service import AdminApplication
from app.abuse.challenge import Challenge, ChallengeProvider
from app.abuse.identity import VisitorIdentity
from app.abuse.service import AbuseGuard
from app.canvas.initializer import initialize_canvas
from app.canvas.service import CanvasApplication
from app.canvas.state import CanvasState
from app.core.events import OrderedEventDispatcher
from app.core.health import HealthState
from app.core.settings import Settings
from app.db import repositories
from app.db.session import create_database
from app.realtime.dispatcher import RealtimeEventHandler
from app.realtime.hub import RealtimeHub
from app.snapshots.store import SnapshotStore
from app.snapshots.worker import SnapshotWorker
from app.stats.service import StatsApplication


class ApplicationRuntime:
    """One place to construct process-scoped dependencies and background work."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.health = HealthState()
        self.engine, self.session_factory = create_database(settings.database_url, sql_echo=settings.sql_echo)
        self.canvas_state = CanvasState(settings.canvas_width, settings.canvas_height)
        self.snapshot_store = SnapshotStore(settings.snapshot_directory, settings.canvas_width, settings.canvas_height)
        self.dispatcher = OrderedEventDispatcher(settings.dispatcher_queue_size)
        self.hub = RealtimeHub(settings.ws_connection_queue_size, settings.ws_send_timeout_seconds)
        self.stats = StatsApplication(self.session_factory)
        self.identity = VisitorIdentity(settings.visitor_cookie_secret, settings.visitor_cookie_days)
        self.abuse = AbuseGuard(settings, self.session_factory)
        self.challenge_provider = ChallengeProvider(
            settings.tencent_captcha_app_id,
            settings.tencent_secret_id,
            settings.tencent_secret_key,
            settings.tencent_captcha_app_secret_key,
        )
        self.challenges: dict[str, tuple[str, str, float]] = {}

        self.snapshot_worker = SnapshotWorker(
            self.canvas_state,
            self.session_factory,
            self.snapshot_store,
            settings.snapshot_threshold,
            self.health,
        )
        self.canvas = CanvasApplication(
            self.canvas_state,
            self.session_factory,
            self.dispatcher,
            self.abuse,
            self.health,
            read_only=settings.canvas_read_only,
        )
        self.admin_auth = AdminAuth(
            settings.admin_token_hash,
            settings.admin_session_secret,
            settings.admin_session_minutes,
            secure=settings.app_env == 'production',
        )
        self.admin = AdminApplication(self)
        # Imported here to keep the composition root as the only dependency
        # assembly location and avoid a moderation -> core import cycle.
        from app.moderation.service import ModerationApplication
        self.moderation = ModerationApplication(self)
        self.dispatcher.subscribe(RealtimeEventHandler(self.hub, self.snapshot_worker, self.stats))

    def issue_challenge(self, visitor_id: str, client_ip: str) -> Challenge:
        now = monotonic()
        self.challenges = {key: value for key, value in self.challenges.items() if value[2] > now}
        challenge = self.challenge_provider.create()
        self.challenges[challenge.id] = (visitor_id, client_ip, now + 300)
        return challenge

    def consume_challenge(self, challenge_id: str, visitor_id: str, client_ip: str) -> bool:
        entry = self.challenges.pop(challenge_id, None)
        return entry is not None and entry[0] == visitor_id and entry[1] == client_ip and entry[2] > monotonic()

    async def start(self) -> None:
        self.snapshot_store.ensure_directory()
        async with self.session_factory() as session:
            await session.execute(text('SELECT 1'))
        initialization = await initialize_canvas(self.canvas_state, self.session_factory, self.snapshot_store)
        await self.stats.initialize()
        await self.abuse.restore_recent_risk_windows()
        async with self.session_factory() as session:
            pending = await repositories.get_pixel_count_after(session, initialization.restored_snapshot_log_id)
        await self.dispatcher.start()
        await self.snapshot_worker.start(
            pending,
            initialization.snapshot_refresh_required,
            base_event_id=initialization.restored_snapshot_log_id,
        )
        self.health.ready = True
        self.health.draining = False

    async def stop(self) -> None:
        self.health.ready = False
        self.health.draining = True
        await self.hub.close_all()
        # Drain post-commit events first so threshold accounting reaches the
        # snapshot worker before it is asked to finish.
        await self.dispatcher.stop()
        await self.snapshot_worker.stop()
        await self.engine.dispose()
