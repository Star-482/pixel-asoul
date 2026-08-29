from __future__ import annotations

from app.abuse.service import AbuseGuard, AbuseRejected
from app.canvas.model import AppliedPixel, PixelCommand, WHITE, normalize_color
from app.canvas.state import CanvasState
from app.core.events import OrderedEventDispatcher, PixelCommitted
from app.core.health import HealthState
from app.db import repositories
from app.db.session import AsyncSessionFactory


class CanvasRejected(Exception):
    def __init__(self, code: str, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retry_after = retry_after


class CanvasApplication:
    """The only writer of canvas state.

    The canvas lock brackets a DB-first transaction and its in-memory commit,
    preserving event order in this intentionally single-process deployment.
    """

    def __init__(
        self,
        state: CanvasState,
        session_factory: AsyncSessionFactory,
        dispatcher: OrderedEventDispatcher,
        abuse: AbuseGuard,
        health: HealthState,
        *,
        read_only: bool,
    ) -> None:
        self.state = state
        self._session_factory = session_factory
        self._dispatcher = dispatcher
        self._abuse = abuse
        self._health = health
        self._configured_read_only = read_only
        self._admin_read_only = False
        self._maintenance_read_only = False

    @property
    def read_only(self) -> bool:
        return (
            self._configured_read_only
            or self._admin_read_only
            or self._maintenance_read_only
            or self._health.draining
        )

    def set_read_only(self, enabled: bool) -> None:
        self._admin_read_only = enabled

    def set_maintenance_read_only(self, enabled: bool) -> None:
        self._maintenance_read_only = enabled

    async def place(self, command: PixelCommand) -> AppliedPixel:
        try:
            color = normalize_color(command.color)
        except ValueError as error:
            raise CanvasRejected('invalid_pixel', str(error)) from error
        if self.read_only:
            raise CanvasRejected('canvas_read_only', '当前仅允许浏览，暂不支持绘制')
        if not command.request_id:
            raise CanvasRejected('invalid_request', 'request_id is required')

        async with self.state.write_lock:
            # A maintenance operation can start while a command is waiting for
            # this lock. Check again so the queued command cannot slip through.
            if self.read_only:
                raise CanvasRejected('canvas_read_only', '当前仅允许浏览，暂不支持绘制')
            try:
                previous_color = self.state.get_pixel(command.x, command.y)
            except ValueError as error:
                raise CanvasRejected('invalid_pixel', '像素坐标超出画布范围') from error

            # Idempotency is checked before the no-op guard so ACK retries are safe.
            async with self._session_factory() as session:
                duplicate = await repositories.get_pixel_by_request_id(session, command.request_id)
                if duplicate is not None:
                    counters = await repositories.get_counters(session)
                    return AppliedPixel(
                        event_id=duplicate.id,
                        x=duplicate.x,
                        y=duplicate.y,
                        color=duplicate.color,
                        previous_color=duplicate.previous_color or WHITE,
                        total_placed_pixels=counters.total_placed_pixels,
                        duplicate=True,
                    )
            if previous_color == color:
                raise CanvasRejected('same_color', '该像素已经是该颜色')

            try:
                reservation = await self._abuse.reserve_draw(
                    command.visitor_id, command.client_ip, previous_color, color
                )
            except AbuseRejected as error:
                raise CanvasRejected(error.code, error.message, error.retry_after) from error

            try:
                async with self._session_factory() as session:
                    async with session.begin():
                        # A second lookup handles a racing retry that waited for the lock.
                        duplicate = await repositories.get_pixel_by_request_id(session, command.request_id)
                        if duplicate is not None:
                            counters = await repositories.get_counters(session)
                            self._abuse.refund(reservation)
                            return AppliedPixel(
                                duplicate.id, duplicate.x, duplicate.y, duplicate.color,
                                duplicate.previous_color or WHITE, counters.total_placed_pixels, True,
                            )
                        row = await repositories.create_pixel_log(
                            session,
                            request_id=command.request_id,
                            visitor_id=command.visitor_id,
                            visit_id=command.visit_id,
                            x=command.x,
                            y=command.y,
                            color=color,
                            previous_color=previous_color,
                        )
                        total = await repositories.increment_placed_pixels(session)
            except Exception:
                self._abuse.refund(reservation)
                raise

            self.state.apply_committed_pixel(command.x, command.y, color, row.id)
            event = PixelCommitted(row.id, command.x, command.y, color, total)
            try:
                self._dispatcher.publish_nowait(event)
            except Exception:
                # Persistence and memory remain correct. Realtime clients must reconnect
                # and catch up from the durable event log.
                self._health.details['dispatcher'] = 'event queue full; reconnect required'
            await self._abuse.commit(reservation, previous_color, color)
            return AppliedPixel(row.id, command.x, command.y, color, previous_color, total)

    async def capture_revision(self):
        async with self.state.write_lock:
            return self.state.capture_revision()
