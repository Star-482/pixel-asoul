from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.runtime import ApplicationRuntime


router = APIRouter(tags=['health'])


async def _database_ok(runtime: ApplicationRuntime) -> bool:
    try:
        async with runtime.session_factory() as session:
            await session.execute(text('SELECT 1'))
        return True
    except Exception:
        return False


@router.get('/health')
async def health(request: Request) -> JSONResponse:
    runtime = request.app.state.runtime
    database = await _database_ok(runtime)
    checks = {'application': runtime.health.ready, 'database': database, 'canvas': runtime.canvas_state.is_initialized()}
    okay = all(checks.values())
    return JSONResponse(status_code=200 if okay else 503, content={'status': 'healthy' if okay else 'unhealthy', 'checks': checks, **runtime.health.snapshot()})


@router.get('/health/live')
async def live(request: Request) -> JSONResponse:
    return JSONResponse(status_code=200, content={'status': 'live', 'draining': request.app.state.runtime.health.draining})


@router.get('/health/ready')
async def ready(request: Request) -> JSONResponse:
    runtime = request.app.state.runtime
    okay = runtime.health.ready and not runtime.health.draining and await _database_ok(runtime)
    return JSONResponse(status_code=200 if okay else 503, content={'status': 'ready' if okay else 'not_ready', **runtime.health.snapshot()})
