from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse


router = APIRouter(prefix='/api/v2', tags=['session'])


@router.get('/session')
async def create_or_resume_session(request: Request) -> JSONResponse:
    runtime = request.app.state.runtime
    visitor_id = runtime.identity.verify(request.cookies.get(runtime.identity.COOKIE_NAME))
    response = JSONResponse(
        {'visitor_id': visitor_id, 'expires_in_days': runtime.settings.visitor_cookie_days},
        headers={'Cache-Control': 'no-store'},
    )
    if visitor_id is None:
        visitor_id, token = runtime.identity.issue()
        response = JSONResponse(
            {'visitor_id': visitor_id, 'expires_in_days': runtime.settings.visitor_cookie_days},
            headers={'Cache-Control': 'no-store'},
        )
        response.set_cookie(
            runtime.identity.COOKIE_NAME,
            token,
            max_age=runtime.identity.max_age,
            httponly=True,
            secure=runtime.settings.app_env == 'production',
            samesite='lax',
            path='/',
        )
    return response
