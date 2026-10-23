"""Read-only preflight for the V2 additive migration.

Run with the `pixel_back` Conda environment before `alembic upgrade head`.
It reports data that requires a human decision and exits non-zero when found.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Support both `python scripts/pre_migration_audit.py` in Docker and local runs.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import text

from app.core.settings import Settings
from app.db.session import create_database


async def main() -> int:
    settings = Settings.from_environment()
    engine, session_factory = create_database(settings.database_url)
    blocking_checks = {
        'invalid_coordinates': 'SELECT count(*) FROM pixel_logs WHERE x < 0 OR y < 0 OR x >= :width OR y >= :height',
        'unsupported_invalid_colors': """
            SELECT count(*)
            FROM pixel_logs
            WHERE color IS NULL
               OR (color !~ '^#[0-9A-Fa-f]{6}$' AND color NOT IN ('#000', ''))
        """,
        'null_snapshot_high_water': 'SELECT count(*) FROM canvas_snapshots WHERE last_log_id IS NULL',
        'snapshot_beyond_log_head': 'SELECT count(*) FROM canvas_snapshots WHERE last_log_id > COALESCE((SELECT max(id) FROM pixel_logs), 0)',
    }
    repairable_checks = {
        'legacy_short_black_colors': "SELECT count(*) FROM pixel_logs WHERE color = '#000'",
        'legacy_empty_colors': "SELECT count(*) FROM pixel_logs WHERE color = ''",
        'duplicate_snapshot_paths_same_high_water': """
            SELECT count(*)
            FROM (
                SELECT data_file_path
                FROM canvas_snapshots
                GROUP BY data_file_path
                HAVING count(*) > 1 AND count(DISTINCT last_log_id) = 1
            ) duplicate_paths
        """,
        'duplicate_snapshot_paths_different_high_water': """
            SELECT count(*)
            FROM (
                SELECT data_file_path
                FROM canvas_snapshots
                GROUP BY data_file_path
                HAVING count(*) > 1 AND count(DISTINCT last_log_id) > 1
            ) duplicate_paths
        """,
    }
    failed = False
    try:
        async with session_factory() as session:
            for name, statement in blocking_checks.items():
                parameters = {'width': settings.canvas_width, 'height': settings.canvas_height}
                count = int((await session.execute(text(statement), parameters)).scalar() or 0)
                print(f'{name}: {count}')
                failed = failed or count > 0
            for name, statement in repairable_checks.items():
                count = int((await session.execute(text(statement))).scalar() or 0)
                if name.startswith('duplicate_snapshot_paths'):
                    message = 'will be verified by reconcile_legacy_snapshots.py --apply'
                else:
                    message = 'will be repaired by 20260829_02'
                print(f'{name}: {count} ({message})')
            for row in (await session.execute(text('SELECT id, data_file_path FROM canvas_snapshots'))).all():
                candidate = settings.snapshot_directory / row.data_file_path
                if not candidate.is_file():
                    print(f'missing_snapshot_file: id={row.id} path={row.data_file_path}')
    finally:
        await engine.dispose()
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
