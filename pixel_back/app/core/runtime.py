from __future__ import annotations

from sqlalchemy import text

from app.admin.auth import AdminAuth
from app.admin.previews import AdminPreviewCache
from app.admin.service import AdminApplication
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
            self_edit_grace_seconds=settings.self_edit_grace_seconds,
        )
        self.admin_auth = AdminAuth(
            settings.admin_token_hash,
            settings.admin_session_secret,
            settings.admin_session_minutes,
            secure=settings.app_env == 'production',
        )
        self.admin = AdminApplication(self)
        self.admin_previews = AdminPreviewCache(self.snapshot_store)
        # Imported here to keep the composition root as the only dependency
        # assembly location and avoid a moderation -> core import cycle.
        from app.moderation.service import ModerationApplication
        self.moderation = ModerationApplication(self)
        self.dispatcher.subscribe(RealtimeEventHandler(self.hub, self.snapshot_worker, self.stats))

    async def start(self) -> None:
        self.snapshot_store.ensure_directory()
        self.admin_previews.cleanup()
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
        await self.moderation.stop()
        # Drain post-commit events first so threshold accounting reaches the
        # snapshot worker before it is asked to finish.
        await self.dispatcher.stop()
        await self.snapshot_worker.stop()
        await self.engine.dispose()
