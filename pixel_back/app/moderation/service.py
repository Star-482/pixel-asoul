from __future__ import annotations

import json
from datetime import timedelta
from typing import TYPE_CHECKING, TypedDict, cast
from uuid import uuid4

from typing_extensions import NotRequired

from sqlalchemy import select

from app.canvas.model import WHITE
from app.core.events import CanvasRestored
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
    coordinates: NotRequired[list[RestoreCoordinate]]


class ModerationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ModerationApplication:
    def __init__(self, runtime: ApplicationRuntime) -> None:
        self._runtime = runtime

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
            filters = self._normalize_filters(payload.get('filters', {}))
            coordinates = await self._plan_coordinates(mode, target_event_id, head, filters)
            if len(coordinates) > 250000:
                raise ModerationError('restore_too_large', '该恢复超过交互式恢复上限，请缩小区域')
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
            return {'id': plan_id, 'head_event_id': head, 'affected_pixels': len(coordinates), 'expires_at': expires_at.isoformat()}

    async def execute_restore_plan(self, admin_id: str, plan_id: str) -> dict[str, object]:
        async with self._runtime.canvas_state.write_lock:
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
                    raw_coordinates = details.get('coordinates', [])
                    if not isinstance(raw_coordinates, list):
                        raise ModerationError('invalid_plan', '恢复计划坐标无效')
                    operation_id = str(uuid4())
                    updates: list[tuple[int, int, str, int]] = []
                    for item in raw_coordinates:
                        if not isinstance(item, dict):
                            raise ModerationError('invalid_plan', '恢复计划坐标无效')
                        x = _integer_value(item.get('x'))
                        y = _integer_value(item.get('y'))
                        color = item.get('color')
                        if not isinstance(color, str):
                            raise ModerationError('invalid_plan', '恢复计划颜色无效')
                        old = self._runtime.canvas_state.get_pixel(x, y)
                        if old == color:
                            continue
                        row = await repositories.create_pixel_log(
                            session,
                            request_id=None,
                            visitor_id=None,
                            visit_id=None,
                            x=x,
                            y=y,
                            color=color,
                            previous_color=old,
                            source='admin_timeline_restore',
                            restore_operation_id=operation_id,
                        )
                        updates.append((x, y, color, row.id))
                    await repositories.create_restore_operation(
                        session,
                        operation_id=operation_id,
                        plan_id=plan.id,
                        created_by=admin_id,
                        affected_pixels=len(updates),
                    )
                    await repositories.add_admin_action(session, admin_id=admin_id, action='restore.execute', details={'plan_id': plan.id, 'operation_id': operation_id, 'pixels': len(updates)})
                    plan.status = 'executed'
            if updates:
                self._runtime.canvas_state.apply_committed_batch(updates, updates[-1][3])
                try:
                    self._runtime.dispatcher.publish_nowait(CanvasRestored(updates[-1][3], operation_id, len(updates)))
                except Exception:
                    self._runtime.health.details['dispatcher'] = 'canvas restore committed; clients must reconnect'
            return {'id': operation_id, 'status': 'completed', 'affected_pixels': len(updates)}

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

        # For selective undo, only touch pixels whose current final event is selected.
        async with self._runtime.session_factory() as session:
            visit_id = filters.get('visit_id')
            connection_id = filters.get('connection_id')
            if connection_id:
                visit_id = await repositories.get_visit_id_by_connection(session, connection_id)
                if visit_id is None:
                    return []
            selected = await repositories.list_pixels_between(
                session, after_id=target_id, through_id=head,
                x_min=filters['x_min'], x_max=filters['x_max'], y_min=filters['y_min'], y_max=filters['y_max'],
                visitor_id=filters.get('visitor_id'), visit_id=visit_id,
            )
            latest: dict[tuple[int, int], PixelLog] = {}
            for row in selected:
                latest[(row.x, row.y)] = row
            result: list[RestoreCoordinate] = []
            for (x, y), row in latest.items():
                # If another event was written after the selected one, it belongs to a
                # normal later edit and must not be overwritten.
                current_event = await session.scalar(
                    select(PixelLog).where(PixelLog.x == x, PixelLog.y == y).order_by(PixelLog.id.desc()).limit(1)
                )
                if current_event is not None and current_event.id == row.id and row.previous_color:
                    result.append({'x': x, 'y': y, 'color': row.previous_color})
            return result

    def _normalize_filters(self, raw: object) -> RestoreFilters:
        if not isinstance(raw, dict):
            raise ModerationError('invalid_filters', '筛选条件无效')
        values = cast(dict[str, object], raw)
        width, height = self._runtime.settings.canvas_width, self._runtime.settings.canvas_height
        result: RestoreFilters = {
            'x_min': max(0, _integer_value(values.get('x_min'), default=0)),
            'x_max': min(width - 1, _integer_value(values.get('x_max'), default=width - 1)),
            'y_min': max(0, _integer_value(values.get('y_min'), default=0)),
            'y_max': min(height - 1, _integer_value(values.get('y_max'), default=height - 1)),
        }
        if result['x_min'] > result['x_max'] or result['y_min'] > result['y_max']:
            raise ModerationError('invalid_filters', '区域范围无效')
        if values.get('visitor_id'):
            result['visitor_id'] = str(values['visitor_id'])
        if values.get('visit_id'):
            result['visit_id'] = _integer_value(values['visit_id'])
        if values.get('connection_id'):
            result['connection_id'] = str(values['connection_id'])
        return result


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
