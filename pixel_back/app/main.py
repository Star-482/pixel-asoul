from __future__ import annotations

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin import router as admin_router
from app.api.canvas import router as canvas_router
from app.api.health import router as health_router
from app.api.session import router as session_router
from app.core.runtime import ApplicationRuntime
from app.core.settings import Settings
from app.websocket.endpoints import router as websocket_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    runtime = ApplicationRuntime(Settings.from_environment())
    app.state.runtime = runtime
    try:
        await runtime.start()
        yield
    finally:
        await runtime.stop()


settings = Settings.from_environment()
app = FastAPI(
    title='Pixel Canvas API',
    description='Single-process collaborative canvas with V2 synchronization.',
    version='3.0.0',
    lifespan=lifespan,
)
if settings.allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_credentials=True,
        allow_methods=['GET', 'POST', 'PUT', 'DELETE'],
        allow_headers=['Content-Type', 'X-CSRF-Token'],
    )

app.include_router(health_router)
app.include_router(session_router)
app.include_router(canvas_router)
app.include_router(admin_router)
app.include_router(websocket_router)


@app.get('/')
async def root() -> dict:
    return {
        'message': 'Pixel Canvas API',
        'protocol': 'v2',
        'session_endpoint': '/api/v2/session',
        'websocket': '/ws/canvas',
    }


if __name__ == '__main__':
    uvicorn.run('app.main:app', host='0.0.0.0', port=8000, reload=True)
