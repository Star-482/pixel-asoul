from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

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


@router.post('/session')
async def login(request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await _json(request)
    token = payload.get('token')
    if not isinstance(token, str) or not runtime.admin_auth.verify_token(token):
        raise HTTPException(status_code=401, detail='管理员令牌无效')
    cookie, csrf = runtime.admin_auth.issue()
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
    _require(request, mutation=True)
    response = Response(status_code=204)
    response.delete_cookie(_runtime(request).admin_auth.COOKIE_NAME, path='/api/v2/admin')
    return response


@router.get('/timeline')
async def timeline(request: Request, start: str | None = None, end: str | None = None) -> dict:
    _require(request)
    now = datetime.now(timezone.utc)
    try:
        start_time = datetime.fromisoformat(start.replace('Z', '+00:00')) if start else now - timedelta(days=1)
        end_time = datetime.fromisoformat(end.replace('Z', '+00:00')) if end else now
    except ValueError as error:
        raise HTTPException(status_code=422, detail='时间必须为 ISO-8601') from error
    runtime = _runtime(request)
    return {'buckets': await modification_density(runtime.session_factory, start_time, end_time), 'timezone': 'Asia/Shanghai'}


@router.post('/timeline/previews')
async def create_preview(request: Request) -> dict:
    _require(request, mutation=True)
    runtime = _runtime(request)
    payload = await _json(request)
    target_id = payload.get('target_event_id')
    if target_id is None and payload.get('target_time'):
        try:
            target_id = await event_id_at_time(runtime.session_factory, datetime.fromisoformat(str(payload['target_time']).replace('Z', '+00:00')))
        except ValueError as error:
            raise HTTPException(status_code=422, detail='target_time 无效') from error
    try:
        target_event_id = int(str(target_id))
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail='target_event_id 必填') from error
    if target_event_id < 0 or target_event_id > runtime.canvas_state.head_event_id:
        raise HTTPException(status_code=422, detail='目标事件不在有效范围')
    array = await build_historical_array(event_id=target_event_id, state=runtime.canvas_state, session_factory=runtime.session_factory, snapshot_store=runtime.snapshot_store)
    preview_id = str(uuid4())
    filename = await asyncio.to_thread(runtime.snapshot_store.write_preview, array, preview_id)
    return {'id': preview_id, 'target_event_id': target_event_id, 'url': f'/api/v2/admin/timeline/previews/{preview_id}.png', 'file': filename}


@router.get('/timeline/previews/{preview_id}.png')
async def get_preview(preview_id: str, request: Request) -> FileResponse:
    _require(request)
    if len(preview_id) != 36:
        raise HTTPException(status_code=404, detail='预览不存在')
    path = _runtime(request).snapshot_store.path_for(f'preview-{preview_id}.png')
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
        return await _runtime(request).moderation.execute_restore_plan(principal['sub'], plan_id)
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
    return {'items': [
        {
            'visitor_id': f'{row.visitor_id[:8]}…',
            'blocked_until': row.blocked_until,
            'challenge_required_until': row.challenge_required_until,
            'post_verification_watch_until': row.post_verification_watch_until,
            'strike_count': row.strike_count,
        }
        for row in rows
    ], 'captcha_degraded': runtime.challenge_provider.degraded}


@router.post('/moderation/{visitor_id}/block')
async def block(visitor_id: str, request: Request) -> Response:
    principal = _require(request, mutation=True)
    payload = await _json(request)
    minutes = _parse_minutes(payload.get('minutes', 30))
    await _runtime(request).admin.block_visitor(principal['sub'], visitor_id, minutes)
    return Response(status_code=204)


@router.post('/moderation/{visitor_id}/unblock')
async def unblock(visitor_id: str, request: Request) -> Response:
    principal = _require(request, mutation=True)
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
    enabled = bool(payload.get('enabled'))
    await _runtime(request).admin.set_read_only(principal['sub'], enabled)
    return {'draw_enabled': not _runtime(request).canvas.read_only}


def _parse_minutes(value: object) -> int:
    if isinstance(value, bool):
        raise HTTPException(status_code=422, detail='minutes 必须是整数')
    try:
        return int(str(value))
    except ValueError as error:
        raise HTTPException(status_code=422, detail='minutes 必须是整数') from error
