from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from typing import TYPE_CHECKING, TypedDict, cast
from uuid import uuid4

from typing_extensions import NotRequired

from app.core.events import CanvasRestored, ReadOnlyChanged
from app.db import repositories
from app.db.models import PixelLog, RestorePlan, utc_now
from app.moderation.timeline import build_historical_array

if TYPE_CHECKING:
    from app.core.runtime import ApplicationRuntime


class RestoreCoordinate(TypedDict):
    x: int
    y: int
    color: str


class RestoreBounds(TypedDict):
    x_min: int
    x_max: int
    y_min: int
    y_max: int


class RestoreFilters(RestoreBounds):
    visitor_id: NotRequired[str]
    visit_id: NotRequired[int]
    connection_id: NotRequired[str]
    event_to_id: int
    coordinates: NotRequired[list[RestoreCoordinate]]


class ModerationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


INTERACTIVE_RESTORE_LIMIT = 250_000


class ModerationApplication:
    def __init__(self, runtime: ApplicationRuntime) -> None:
        self._runtime = runtime
        self._background_tasks: set[asyncio.Task[None]] = set()

    async def make_restore_plan(self, admin_id: str, payload: dict[str, object]) -> dict[str, object]:
        mode_value = payload.get('mode', 'selective')
        mode = mode_value if isinstance(mode_value, str) else ''
        target_event_id = _integer_value(payload.get('target_event_id'), default=0)
        if mode not in {'selective', 'exact'}:
            raise ModerationError('invalid_mode', '恢复模式无效')
        async with self._runtime.canvas_state.write_lock:
            head = self._runtime.canvas_state.head_event_id
            if target_event_id < 0 or target_event_id > head:
                raise ModerationError('invalid_target', '目标时间点不在当前历史范围内')
            filters = self._normalize_filters(payload.get('filters', {}), head)
            if mode == 'selective' and filters['event_to_id'] < target_event_id:
                raise ModerationError('invalid_range', '撤销范围结束事件不能早于起始事件')
            coordinates = await self._plan_coordinates(mode, target_event_id, head, filters)
            plan_id = str(uuid4())
            filters['coordinates'] = coordinates
            expires_at = utc_now() + timedelta(minutes=10)
            async with self._runtime.session_factory() as session:
                async with session.begin():
                    await repositories.create_restore_plan(
                        session,
                        plan_id=plan_id,
                        created_by=admin_id,
                        mode=mode,
                        target_event_id=target_event_id,
                        current_head_event_id=head,
                        filters=filters,
                        expires_at=expires_at,
                    )
                    await repositories.add_admin_action(session, admin_id=admin_id, action='restore.preview', details={'plan_id': plan_id, 'pixels': len(coordinates)})
            return {
                'id': plan_id,
                'head_event_id': head,
                'affected_pixels': len(coordinates),
                'requires_background': len(coordinates) > INTERACTIVE_RESTORE_LIMIT,
                'expires_at': expires_at.isoformat(),
            }

    async def execute_restore_plan(
        self, admin_id: str, plan_id: str, confirmation_text: str | None = None
    ) -> dict[str, object]:
        async with self._runtime.canvas_state.write_lock:
            queued: tuple[str, list[object]] | None = None
            updates: list[tuple[int, int, str, int]] = []
            async with self._runtime.session_factory() as session:
                async with session.begin():
                    plan = await session.get(RestorePlan, plan_id)
                    if plan is None:
                        raise ModerationError('not_found', '恢复计划不存在')
                    if plan.expires_at < utc_now() or plan.status != 'ready':
                        raise ModerationError('plan_expired', '恢复计划已失效')
                    if plan.head_event_id != self._runtime.canvas_state.head_event_id:
                        raise ModerationError('preview_stale', '预览生成后画布已变化，请重新预览')
                    details = json.loads(plan.filters_json)
                    if not isinstance(details, dict):
                        raise ModerationError('invalid_plan', '恢复计划数据无效')
                    if self._requires_full_canvas_confirmation(plan.mode, details):
                        if confirmation_text != '恢复整图':
                            raise ModerationError(
                                'confirmation_required',
                                '整图精确恢复前请输入“恢复整图”确认',
                            )
                    raw_coordinates = details.get('coordinates', [])
                    if not isinstance(raw_coordinates, list):
                        raise ModerationError('invalid_plan', '恢复计划坐标无效')
                    operation_id = str(uuid4())
                    if len(raw_coordinates) > INTERACTIVE_RESTORE_LIMIT:
                        await repositories.create_restore_operation(
                            session,
                            operation_id=operation_id,
                            plan_id=plan.id,
                            created_by=admin_id,
                            affected_pixels=0,
                            status='queued',
                        )
                        await repositories.add_admin_action(
                            session,
                            admin_id=admin_id,
                            action='restore.queued',
                            details={'plan_id': plan.id, 'operation_id': operation_id, 'pixels': len(raw_coordinates)},
                        )
                        plan.status = 'executing'
                        queued = (operation_id, raw_coordinates)
                    else:
                        changes = self._collect_changes(raw_coordinates)
                        updates = await repositories.create_restore_pixel_logs_bulk(
                            session,
                            operation_id=operation_id,
                            changes=changes,
                        )
                        await repositories.create_restore_operation(
                            session,
                            operation_id=operation_id,
                            plan_id=plan.id,
                            created_by=admin_id,
                            affected_pixels=len(updates),
                            skipped_pixels=len(raw_coordinates) - len(updates),
                        )
                        await repositories.add_admin_action(session, admin_id=admin_id, action='restore.execute', details={'plan_id': plan.id, 'operation_id': operation_id, 'pixels': len(updates)})
                        plan.status = 'executed'
            if queued is not None:
                operation_id, raw_coordinates = queued
                self._set_maintenance(True)
                task = asyncio.create_task(
                    self._execute_queued_restore(admin_id, plan_id, operation_id, raw_coordinates),
                    name=f'admin-restore-{operation_id}',
                )
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)
                return {
                    'id': operation_id,
                    'status': 'queued',
                    'affected_pixels': len(raw_coordinates),
                }
            if updates:
                event_id = max(item[3] for item in updates)
                self._runtime.canvas_state.apply_committed_batch(updates, event_id)
                try:
                    self._runtime.dispatcher.publish_nowait(CanvasRestored(event_id, operation_id, len(updates)))
                except Exception:
                    self._runtime.health.details['dispatcher'] = 'canvas restore committed; clients must reconnect'
            return {'id': operation_id, 'status': 'completed', 'affected_pixels': len(updates)}

    def _collect_changes(
        self, raw_coordinates: list[object]
    ) -> list[tuple[int, int, str, str]]:
        changes: list[tuple[int, int, str, str]] = []
        for item in raw_coordinates:
            if not isinstance(item, dict):
                raise ModerationError('invalid_plan', '恢复计划坐标无效')
            x = _integer_value(item.get('x'))
            y = _integer_value(item.get('y'))
            color = item.get('color')
            if not isinstance(color, str):
                raise ModerationError('invalid_plan', '恢复计划颜色无效')
            old = self._runtime.canvas_state.get_pixel(x, y)
            if old != color:
                changes.append((x, y, color, old))
        return changes

    async def _execute_queued_restore(
        self,
        admin_id: str,
        plan_id: str,
        operation_id: str,
        raw_coordinates: list[object],
    ) -> None:
        """Run a large exact/selective restore without holding an HTTP request."""
        try:
            async with self._runtime.canvas_state.write_lock:
                async with self._runtime.session_factory() as session:
                    async with session.begin():
                        plan = await session.get(RestorePlan, plan_id)
                        if plan is None or plan.status != 'executing':
                            raise ModerationError('not_found', '恢复计划不存在或已取消')
                        if plan.head_event_id != self._runtime.canvas_state.head_event_id:
                            raise ModerationError('preview_stale', '维护开始前画布已变化，请重新预览')
                        changes = self._collect_changes(raw_coordinates)
                        updates = await repositories.create_restore_pixel_logs_bulk(
                            session,
                            operation_id=operation_id,
                            changes=changes,
                        )
                        await repositories.finish_restore_operation(
                            session,
                            operation_id=operation_id,
                            status='completed',
                            affected_pixels=len(updates),
                            skipped_pixels=len(raw_coordinates) - len(updates),
                        )
                        await repositories.add_admin_action(
                            session,
                            admin_id=admin_id,
                            action='restore.execute',
                            details={'plan_id': plan_id, 'operation_id': operation_id, 'pixels': len(updates)},
                        )
                        plan.status = 'executed'
                if updates:
                    event_id = max(item[3] for item in updates)
                    self._runtime.canvas_state.apply_committed_batch(updates, event_id)
                    self._publish_canvas_restored(event_id, operation_id, len(updates))
        except Exception as error:
            async with self._runtime.session_factory() as session:
                async with session.begin():
                    await repositories.finish_restore_operation(
                        session,
                        operation_id=operation_id,
                        status='failed',
                        affected_pixels=0,
                        skipped_pixels=0,
                    )
                    await repositories.add_admin_action(
                        session,
                        admin_id=admin_id,
                        action='restore.failed',
                        details={'plan_id': plan_id, 'operation_id': operation_id, 'error': type(error).__name__},
                    )
        finally:
            self._set_maintenance(False)

    def _set_maintenance(self, enabled: bool) -> None:
        self._runtime.canvas.set_maintenance_read_only(enabled)
        try:
            self._runtime.dispatcher.publish_nowait(
                ReadOnlyChanged(draw_enabled=not self._runtime.canvas.read_only)
            )
        except Exception:
            self._runtime.health.details['dispatcher'] = 'maintenance status changed; clients must reconnect'

    def _publish_canvas_restored(
        self, event_id: int, operation_id: str, affected_pixels: int
    ) -> None:
        try:
            self._runtime.dispatcher.publish_nowait(
                CanvasRestored(event_id, operation_id, affected_pixels)
            )
        except Exception:
            self._runtime.health.details['dispatcher'] = 'canvas restore committed; clients must reconnect'

    async def _plan_coordinates(
        self, mode: str, target_id: int, head: int, filters: RestoreFilters
    ) -> list[RestoreCoordinate]:
        if mode == 'exact':
            target = await build_historical_array(
                event_id=target_id,
                state=self._runtime.canvas_state,
                session_factory=self._runtime.session_factory,
                snapshot_store=self._runtime.snapshot_store,
            )
            current = self._runtime.canvas_state.capture_revision().pixels
            result: list[RestoreCoordinate] = []
            for y in range(filters['y_min'], filters['y_max'] + 1):
                for x in range(filters['x_min'], filters['x_max'] + 1):
                    if not (target[y, x] == current[y, x]).all():
                        rgb = target[y, x]
                        result.append({'x': x, 'y': y, 'color': f'#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}'})
            return result

        # For selective undo, only touch pixels whose current final event is in
        # the chosen range. The replacement color comes from the state just
        # before that range, which correctly handles several destructive edits
        # to the same coordinate in one incident.
        async with self._runtime.session_factory() as session:
            visit_id = filters.get('visit_id')
            connection_id = filters.get('connection_id')
            if connection_id:
                visit_id = await repositories.get_visit_id_by_connection(session, connection_id)
                if visit_id is None:
                    return []
            selected = await repositories.list_pixels_between(
                session, after_id=target_id, through_id=filters['event_to_id'],
                x_min=filters['x_min'], x_max=filters['x_max'], y_min=filters['y_min'], y_max=filters['y_max'],
                visitor_id=filters.get('visitor_id'), visit_id=visit_id,
            )
            latest: dict[tuple[int, int], PixelLog] = {}
            for row in selected:
                latest[(row.x, row.y)] = row
            current_ids = await repositories.list_latest_pixel_ids_in_bounds(
                session,
                x_min=filters['x_min'],
                x_max=filters['x_max'],
                y_min=filters['y_min'],
                y_max=filters['y_max'],
            )
        before_range = await build_historical_array(
            event_id=target_id,
            state=self._runtime.canvas_state,
            session_factory=self._runtime.session_factory,
            snapshot_store=self._runtime.snapshot_store,
        )
        result: list[RestoreCoordinate] = []
        for (x, y), row in latest.items():
            if row.id not in current_ids:
                continue
            rgb = before_range[y, x]
            color = f'#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}'
            if self._runtime.canvas_state.get_pixel(x, y) != color:
                result.append({'x': x, 'y': y, 'color': color})
        return result

    def _normalize_filters(self, raw: object, head_event_id: int) -> RestoreFilters:
        if not isinstance(raw, dict):
            raise ModerationError('invalid_filters', '筛选条件无效')
        values = cast(dict[str, object], raw)
        width, height = self._runtime.settings.canvas_width, self._runtime.settings.canvas_height
        result: RestoreFilters = {
            'x_min': max(0, _integer_value(values.get('x_min'), default=0)),
            'x_max': min(width - 1, _integer_value(values.get('x_max'), default=width - 1)),
            'y_min': max(0, _integer_value(values.get('y_min'), default=0)),
            'y_max': min(height - 1, _integer_value(values.get('y_max'), default=height - 1)),
            'event_to_id': min(
                head_event_id,
                _integer_value(values.get('event_to_id'), default=head_event_id),
            ),
        }
        if result['x_min'] > result['x_max'] or result['y_min'] > result['y_max']:
            raise ModerationError('invalid_filters', '区域范围无效')
        if result['event_to_id'] < 0:
            raise ModerationError('invalid_range', '撤销范围结束事件无效')
        if values.get('visitor_id'):
            result['visitor_id'] = str(values['visitor_id'])
        if values.get('visit_id'):
            result['visit_id'] = _integer_value(values['visit_id'])
        if values.get('connection_id'):
            result['connection_id'] = str(values['connection_id'])
        return result

    def _requires_full_canvas_confirmation(self, mode: str, filters: dict[str, object]) -> bool:
        return (
            mode == 'exact'
            and _integer_value(filters.get('x_min'), default=-1) == 0
            and _integer_value(filters.get('y_min'), default=-1) == 0
            and _integer_value(filters.get('x_max'), default=-1) == self._runtime.settings.canvas_width - 1
            and _integer_value(filters.get('y_max'), default=-1) == self._runtime.settings.canvas_height - 1
        )


def _integer_value(value: object, *, default: int | None = None) -> int:
    if value is None and default is not None:
        return default
    if isinstance(value, bool):
        raise ModerationError('invalid_value', '数值参数无效')
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError as error:
            raise ModerationError('invalid_value', '数值参数无效') from error
    raise ModerationError('invalid_value', '数值参数无效')
