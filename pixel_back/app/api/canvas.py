from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from app.db import repositories


router = APIRouter(prefix='/api/v2/canvas', tags=['canvas'])


@router.get('/snapshots/{snapshot_id}.png')
async def get_snapshot(snapshot_id: int, request: Request) -> FileResponse:
    runtime = request.app.state.runtime
    async with runtime.session_factory() as session:
        snapshot = await repositories.get_snapshot(session, snapshot_id)
    if snapshot is None or snapshot.status != 'valid' or not snapshot.data_file_path.endswith('.png'):
        raise HTTPException(status_code=404, detail='快照不存在')
    try:
        path = runtime.snapshot_store.path_for(snapshot.data_file_path)
    except Exception as error:
        raise HTTPException(status_code=404, detail='快照不可用') from error
    if not path.is_file():
        raise HTTPException(status_code=404, detail='快照文件不存在')
    return FileResponse(path, media_type='image/png', headers={'Cache-Control': 'public, max-age=300'})


@router.get('/events')
async def get_events(
    request: Request,
    after: int = Query(default=0, ge=0),
    through: int | None = Query(default=None, ge=0),
    limit: int = Query(default=5000, ge=1, le=5000),
) -> dict:
    runtime = request.app.state.runtime
    async with runtime.session_factory() as session:
        rows = await repositories.get_pixels_after(session, after, through=through, limit=limit)
        head = await repositories.get_latest_pixel_id(session)
    return {
        'events': [
            {'event_id': row.id, 'x': row.x, 'y': row.y, 'color': row.color, 'source': row.source}
            for row in rows
        ],
        'head_event_id': head,
        'has_more': bool(rows and (through is None or rows[-1].id < through) and len(rows) == limit),
    }
