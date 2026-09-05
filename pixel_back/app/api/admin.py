from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import numpy as np
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from app.db import repositories
from app.moderation.service import ModerationError
from app.moderation.timeline import build_historical_array, event_id_at_time, modification_density


router = APIRouter(prefix='/api/v2/admin', tags=['admin'])


def _runtime(request: Request):
    return request.app.state.runtime


def _body_is_object(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail='请求体必须是对象')
    return payload


async def _json(request: Request) -> dict:
    try:
        return _body_is_object(await request.json())
    except ValueError as error:
        raise HTTPException(status_code=422, detail='请求体不是有效 JSON') from error


def _require(request: Request, mutation: bool = False) -> dict:
    return _runtime(request).admin_auth.require(request, mutation=mutation)


def _parse_datetime(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=f'{field} 必须为 ISO-8601 时间') from error
    if parsed.tzinfo is None:
        raise HTTPException(status_code=422, detail=f'{field} 必须包含时区')
    return parsed.astimezone(timezone.utc)


@router.post('/session')
async def login(request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await _json(request)
    token = payload.get('token')
    if not isinstance(token, str) or not runtime.admin_auth.verify_token(token):
        raise HTTPException(status_code=401, detail='管理员令牌无效')
    cookie, csrf = runtime.admin_auth.issue()
    await runtime.admin.audit('administrator', 'admin.login')
    response = JSONResponse({'csrf_token': csrf, 'expires_in_minutes': runtime.settings.admin_session_minutes})
    response.set_cookie(
        runtime.admin_auth.COOKIE_NAME,
        cookie,
        max_age=runtime.settings.admin_session_minutes * 60,
        httponly=True,
        secure=runtime.admin_auth.secure,
        samesite='strict',
        path='/api/v2/admin',
    )
    return response


@router.delete('/session')
async def logout(request: Request) -> Response:
    principal = _require(request, mutation=True)
    await _runtime(request).admin.audit(principal['sub'], 'admin.logout')
    response = Response(status_code=204)
    response.delete_cookie(_runtime(request).admin_auth.COOKIE_NAME, path='/api/v2/admin')
    return response


@router.get('/status')
async def status(request: Request) -> dict:
    """Return the current process-local canvas state for the admin shell."""
    _require(request)
    runtime = _runtime(request)
    return {
        'canvas': {
            'width': runtime.settings.canvas_width,
            'height': runtime.settings.canvas_height,
            'head_event_id': runtime.canvas_state.head_event_id,
            'draw_enabled': not runtime.canvas.read_only,
        },
        'stats': runtime.stats.current().as_dict(),
    }


@router.get('/timeline')
async def timeline(request: Request, start: str | None = None, end: str | None = None) -> dict:
    _require(request)
    now = datetime.now(timezone.utc)
    start_time = _parse_datetime(start, 'start') if start else now - timedelta(days=1)
    end_time = _parse_datetime(end, 'end') if end else now
    if start_time >= end_time:
        raise HTTPException(status_code=422, detail='start 必须早于 end')
    runtime = _runtime(request)
    async with runtime.session_factory() as session:
        snapshots = await repositories.list_snapshot_markers(
            session, start=start_time, end=end_time
        )
    return {
        'start': start_time,
        'end': end_time,
        'head_event_id': runtime.canvas_state.head_event_id,
        'buckets': await modification_density(runtime.session_factory, start_time, end_time),
        'snapshots': [
            {
                'id': snapshot.id,
                'event_id': snapshot.last_log_id,
                'event_time': event_time,
                'created_at': snapshot.created_at,
            }
            for snapshot, event_time in snapshots
        ],
        'timezone': 'Asia/Shanghai',
    }


@router.post('/timeline/previews')
async def create_preview(request: Request) -> dict:
    _require(request, mutation=True)
    runtime = _runtime(request)
    payload = await _json(request)
    target_id = payload.get('target_event_id')
    if target_id is None and payload.get('target_time'):
        target_id = await event_id_at_time(
            runtime.session_factory,
            _parse_datetime(str(payload['target_time']), 'target_time'),
        )
    try:
        target_event_id = int(str(target_id))
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail='target_event_id 必填') from error
    async with runtime.canvas_state.write_lock:
        head_event_id = runtime.canvas_state.head_event_id
        current = runtime.canvas_state.capture_revision().pixels
    if target_event_id < 0 or target_event_id > head_event_id:
        raise HTTPException(status_code=422, detail='目标事件不在有效范围')
    array = await build_historical_array(event_id=target_event_id, state=runtime.canvas_state, session_factory=runtime.session_factory, snapshot_store=runtime.snapshot_store)
    preview_id = str(uuid4())
    difference_mask = np.any(array != current, axis=2)
    difference = np.full_like(array, 255)
    difference[difference_mask] = (239, 68, 68)
    filename = await asyncio.to_thread(runtime.snapshot_store.write_preview, array, preview_id)
    try:
        difference_filename = await asyncio.to_thread(
            runtime.snapshot_store.write_preview, difference, preview_id, '-diff'
        )
    except Exception:
        runtime.snapshot_store.path_for(filename).unlink(missing_ok=True)
        raise
    item = runtime.admin_previews.add(
        preview_id=preview_id,
        filename=filename,
        difference_filename=difference_filename,
        target_event_id=target_event_id,
        head_event_id=head_event_id,
        difference_pixels=int(np.count_nonzero(difference_mask)),
    )
    return {
        'id': item.id,
        'target_event_id': item.target_event_id,
        'head_event_id': item.head_event_id,
        'difference_pixels': item.difference_pixels,
        'url': f'/api/v2/admin/timeline/previews/{item.id}.png',
        'difference_url': f'/api/v2/admin/timeline/previews/{item.id}/diff.png',
        'expires_in_seconds': 600,
    }


@router.get('/timeline/previews/{preview_id}.png')
async def get_preview(preview_id: str, request: Request) -> FileResponse:
    _require(request)
    if len(preview_id) != 36:
        raise HTTPException(status_code=404, detail='预览不存在')
    runtime = _runtime(request)
    preview = runtime.admin_previews.get(preview_id)
    if preview is None:
        raise HTTPException(status_code=404, detail='预览已过期，请重新生成')
    path = runtime.snapshot_store.path_for(preview.filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail='预览不存在')
    return FileResponse(path, media_type='image/png', headers={'Cache-Control': 'private, max-age=600'})


@router.get('/timeline/previews/{preview_id}/diff.png')
async def get_preview_difference(preview_id: str, request: Request) -> FileResponse:
    _require(request)
    if len(preview_id) != 36:
        raise HTTPException(status_code=404, detail='预览不存在')
    runtime = _runtime(request)
    preview = runtime.admin_previews.get(preview_id)
    if preview is None:
        raise HTTPException(status_code=404, detail='预览已过期，请重新生成')
    path = runtime.snapshot_store.path_for(preview.difference_filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail='预览不存在')
    return FileResponse(path, media_type='image/png', headers={'Cache-Control': 'private, max-age=600'})


@router.post('/restore-plans')
async def restore_plan(request: Request) -> dict:
    principal = _require(request, mutation=True)
    try:
        return await _runtime(request).moderation.make_restore_plan(principal['sub'], await _json(request))
    except ModerationError as error:
        raise HTTPException(status_code=409 if error.code == 'restore_too_large' else 422, detail={'code': error.code, 'message': error.message}) from error


@router.post('/restore-plans/{plan_id}/execute')
async def execute_restore_plan(plan_id: str, request: Request) -> dict:
    principal = _require(request, mutation=True)
    try:
        payload = await _json(request)
        confirmation = payload.get('confirmation_text')
        return await _runtime(request).moderation.execute_restore_plan(
            principal['sub'],
            plan_id,
            confirmation if isinstance(confirmation, str) else None,
        )
    except ModerationError as error:
        status = 409 if error.code == 'preview_stale' else 404 if error.code == 'not_found' else 422
        raise HTTPException(status_code=status, detail={'code': error.code, 'message': error.message}) from error


@router.get('/restore-operations/{operation_id}')
async def restore_operation(operation_id: str, request: Request) -> dict:
    _require(request)
    runtime = _runtime(request)
    async with runtime.session_factory() as session:
        from app.db.models import RestoreOperation
        item = await session.get(RestoreOperation, operation_id)
    if item is None:
        raise HTTPException(status_code=404, detail='恢复操作不存在')
    return {'id': item.id, 'status': item.status, 'affected_pixels': item.affected_pixels, 'skipped_pixels': item.skipped_pixels}


@router.get('/moderation')
async def moderation(request: Request) -> dict:
    _require(request)
    runtime = _runtime(request)
    async with runtime.session_factory() as session:
        rows = await repositories.list_moderation_states(session)
    now = datetime.now(timezone.utc)
    return {
        'items': [
            {
                'visitor_id': row.visitor_id,
                'display_visitor_id': f'{row.visitor_id[:8]}…',
                'blocked_until': row.blocked_until,
                'overwrite_cooldown_until': row.overwrite_cooldown_until,
                'overwrite_watch_until': row.overwrite_watch_until,
                'strike_count': row.strike_count,
                'status': _moderation_status(row, now),
            }
            for row in rows
        ],
    }


@router.post('/moderation/{visitor_id}/block')
async def block(visitor_id: str, request: Request) -> Response:
    principal = _require(request, mutation=True)
    _parse_visitor_id(visitor_id)
    payload = await _json(request)
    minutes = _parse_minutes(payload.get('minutes', 30))
    await _runtime(request).admin.block_visitor(principal['sub'], visitor_id, minutes)
    return Response(status_code=204)


@router.post('/moderation/{visitor_id}/unblock')
async def unblock(visitor_id: str, request: Request) -> Response:
    principal = _require(request, mutation=True)
    _parse_visitor_id(visitor_id)
    await _runtime(request).admin.unblock_visitor(principal['sub'], visitor_id)
    return Response(status_code=204)


@router.get('/actions')
async def actions(request: Request) -> dict:
    _require(request)
    runtime = _runtime(request)
    async with runtime.session_factory() as session:
        rows = await repositories.list_admin_actions(session)
    return {'items': [
        {'id': row.id, 'admin_id': row.admin_id, 'action': row.action, 'details': json.loads(row.details_json), 'created_at': row.created_at}
        for row in rows
    ]}


@router.put('/canvas/read-only')
async def read_only(request: Request) -> dict:
    principal = _require(request, mutation=True)
    payload = await _json(request)
    enabled = payload.get('enabled')
    if not isinstance(enabled, bool):
        raise HTTPException(status_code=422, detail='enabled 必须是布尔值')
    await _runtime(request).admin.set_read_only(principal['sub'], enabled)
    return {'draw_enabled': not _runtime(request).canvas.read_only}


def _parse_minutes(value: object) -> int:
    if isinstance(value, bool):
        raise HTTPException(status_code=422, detail='minutes 必须是整数')
    try:
        return int(str(value))
    except ValueError as error:
        raise HTTPException(status_code=422, detail='minutes 必须是整数') from error


def _parse_visitor_id(value: str) -> None:
    try:
        UUID(value)
    except ValueError as error:
        raise HTTPException(status_code=422, detail='visitor_id 必须是 UUID') from error


def _moderation_status(row: object, now: datetime) -> str:
    blocked_until = getattr(row, 'blocked_until', None)
    cooldown_until = getattr(row, 'overwrite_cooldown_until', None)
    watch_until = getattr(row, 'overwrite_watch_until', None)
    if blocked_until and blocked_until > now:
        return 'blocked'
    if cooldown_until and cooldown_until > now:
        return 'overwrite_cooldown'
    if watch_until and watch_until > now:
        return 'observing'
    return 'normal'
