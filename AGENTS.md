# Repository Guidelines

## Project Structure & Module Organization

This repository has two independently run applications:

- `pixel_front/` is the Vue 3 + Vite client. UI components live in `src/components/`, WebSocket handling is in `src/utils/ws.js`, and static assets are in `src/assets/` and `public/`.
- `pixel_back/` is the FastAPI service. Keep API routes in `app/api/`, WebSocket handling in `app/websocket/`, orchestration in `app/services/`, process-local state in `app/state/`, persistence in `app/db/`, and event models in `app/schemas/`.
- `pixel_back/tests/` contains backend unit tests run with the standard-library `unittest` runner.

Snapshot PNG/JSON files in `pixel_back/snapshots/` are runtime data. Docker mounts the deployment directory's `snapshots/` folder at `/app/snapshots`. Do not rename or remove snapshots without keeping PostgreSQL metadata consistent.

## Build, Test, and Development Commands

Run commands from each subproject, not the repository root:

```bash
cd pixel_front && npm install && npm run dev   # Vite dev server (port 8080)
cd pixel_front && npm run build                # production build in dist/
cd pixel_front && npm run preview              # serve the built client

cd pixel_back && pip install -r requirements.txt
cd pixel_back && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
cd pixel_back && python -m unittest discover -s tests -p "test_*.py"
```

The backend needs Python 3.10+, PostgreSQL, and a local `.env`. It is intentionally single-process; do not configure multiple Uvicorn workers. Check `GET /health` after startup. There is no configured lint command; run relevant unit tests and validate service-dependent behavior manually.

## Coding Style & Naming Conventions

Match the surrounding code. Frontend files use two-space indentation, single quotes, Vue Composition API, and PascalCase component filenames (for example, `CanvasBoard.vue`). Keep helper modules camelCase, such as `ws.js`.

Backend Python uses four-space indentation, snake_case modules/functions, PascalCase classes, and async I/O. Reuse `get_db_session()` transaction scopes instead of committing from CRUD helpers. Preserve the flat canvas index formula `y * CANVAS_WIDTH + x` and normalized `#RRGGBB` colors.

## Testing Guidelines

Add focused Python tests named `test_*.py` under `pixel_back/tests/`. Document manual verification in the pull request, including WebSocket sync, rate-limit behavior, or snapshot recovery when relevant.

## Commit & Pull Request Guidelines

Recent history follows Conventional Commit-style prefixes, commonly `feat:`, `fix:`, `docs:`, and `chore:`; use a short imperative summary, e.g. `fix: correct canvas coordinate bounds`. Keep commits scoped to one concern. Pull requests should explain the user-visible change, list validation performed, link related issues, and include screenshots or recordings for UI/canvas interaction changes. Note any configuration, database, or snapshot-data impact explicitly.
