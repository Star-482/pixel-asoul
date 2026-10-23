from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.canvas.model import PixelCommand
from app.canvas.service import CanvasRejected
from app.core.events import ConnectionClosed, VisitCommitted
from app.core.runtime import ApplicationRuntime
from app.db import repositories
from app.realtime.hub import RealtimeConnection
from app.realtime.protocol import IncomingMessage, ProtocolError, error_payload, parse_message
from app.schemas.websocket import PixelPlaceData
from app.utils.utils import extract_client_ip_from_websocket


router = APIRouter()


def _origin_is_allowed(websocket: WebSocket, origins: tuple[str, ...]) -> bool:
    if not origins:
        return True
    return (websocket.headers.get('origin') or '').rstrip('/') in origins


@router.websocket('/ws/canvas')
async def canvas_websocket(websocket: WebSocket) -> None:
    runtime: ApplicationRuntime = websocket.app.state.runtime
    if not _origin_is_allowed(websocket, runtime.settings.allowed_origins):
        await websocket.close(code=1008, reason='Origin is not allowed')
        return
    visitor_id = runtime.identity.verify(websocket.cookies.get(runtime.identity.COOKIE_NAME))
    if visitor_id is None:
        await websocket.accept()
        await websocket.send_json(error_payload('session_required', '请先创建匿名会话'))
        await websocket.close(code=1008, reason='session required')
        return
    if not runtime.health.ready or runtime.health.draining:
        await websocket.close(code=1013, reason='service unavailable')
        return

    connection: RealtimeConnection | None = None
    visit_id: int | None = None
    online_opened = False
    connection_id = str(uuid4())
    client_ip = extract_client_ip_from_websocket(websocket, runtime.settings.trust_proxy_headers) or 'unknown'
    try:
        async with runtime.session_factory() as session:
            async with session.begin():
                visit = await repositories.create_visit(
                    session, visitor_id=visitor_id, connection_id=connection_id, ip=client_ip
                )
                visit_id = visit.id
                counters = await repositories.get_counters(session)
        stats = runtime.stats.visit_committed(counters.total_visits)
        stats = await runtime.stats.connection_opened()
        online_opened = True
        # Snapshot choice and head high-water are captured while a writer cannot
        # commit, so the first server message defines a lossless catch-up range.
        async with runtime.canvas_state.write_lock:
            head = runtime.canvas_state.head_event_id
            async with runtime.session_factory() as session:
                snapshot = await repositories.get_snapshot_at_or_before(session, head)
            ready = {
                'type': 'session.ready',
                'data': {
                    'session_id': connection_id,
                    'head_event_id': head,
                    'draw_enabled': not runtime.canvas.read_only,
                    'canvas': {'width': runtime.settings.canvas_width, 'height': runtime.settings.canvas_height},
                    'snapshot': None if snapshot is None else {
                        'id': snapshot.id, 'last_event_id': snapshot.last_log_id,
                        'url': f'/api/v2/canvas/snapshots/{snapshot.id}.png',
                    },
                    'stats': stats.as_dict(),
                },
            }
            connection = await runtime.hub.register(websocket, visitor_id, ready, connection_id=connection_id)
            connection.visit_id = visit_id
        runtime.dispatcher.publish_nowait(VisitCommitted(stats.as_dict()))

        assert connection is not None
        assert visit_id is not None

        while True:
            raw = await websocket.receive_text()
            try:
                runtime.abuse.allow_message(connection.id)
                message = parse_message(raw, runtime.settings.ws_max_message_bytes)
            except ProtocolError as error:
                await runtime.hub.send(connection.id, error_payload(str(error), '消息格式无效'))
                continue
            except Exception as error:
                code = getattr(error, 'code', 'rate_limited')
                await runtime.hub.send(connection.id, error_payload(code, str(error), retry_after=getattr(error, 'retry_after', None)))
                continue

            if message.type == 'pixel.place':
                await _place_pixel(runtime, connection, visitor_id, visit_id, client_ip, message)
            else:
                await runtime.hub.send(connection.id, error_payload('unsupported_type', '不支持的消息类型', request_id=message.request_id))
    except WebSocketDisconnect:
        pass
    except Exception:
        if connection is not None:
            await runtime.hub.send(connection.id, error_payload('internal_error', '连接处理失败，请重连'))
    finally:
        if connection is not None:
            await runtime.hub.close(connection.id)
            runtime.abuse.forget_connection(connection.id)
        if visit_id is not None:
            async with runtime.session_factory() as session:
                async with session.begin():
                    await repositories.close_visit(session, visit_id)
        if online_opened:
            stats = await runtime.stats.connection_closed()
            try:
                runtime.dispatcher.publish_nowait(ConnectionClosed(stats.as_dict()))
            except Exception:
                pass


async def _place_pixel(
    runtime: ApplicationRuntime,
    connection: RealtimeConnection,
    visitor_id: str,
    visit_id: int,
    client_ip: str,
    message: IncomingMessage,
) -> None:
    if not message.request_id:
        await runtime.hub.send(connection.id, error_payload('invalid_request_id', 'pixel.place 必须包含 request_id'))
        return
    try:
        data = PixelPlaceData.model_validate(message.data)
        x, y, color = data.x, data.y, data.color
    except ValidationError:
        await runtime.hub.send(connection.id, error_payload('invalid_pixel', '像素数据无效', request_id=message.request_id))
        return
    try:
        applied = await runtime.canvas.place(PixelCommand(message.request_id, x, y, color, visitor_id, visit_id, client_ip))
    except CanvasRejected as error:
        await runtime.hub.send(connection.id, error_payload(error.code, error.message, request_id=message.request_id, retry_after=error.retry_after))
        return
    await runtime.hub.send(connection.id, {
        'type': 'pixel.ack',
        'request_id': message.request_id,
        'data': {'event_id': applied.event_id, 'duplicate': applied.duplicate},
    })
