"""Normalize the mixed timestamp semantics in the legacy canvas history.

The original canvas stored UTC wall-clock values in PostgreSQL ``timestamp
without time zone`` columns.  A later deployment started storing
Asia/Shanghai wall-clock values in those same columns.  Consequently the
database contains two representations of the same conceptual instant.

The production history was checked before this migration was written:

* pixel log ``365552`` is the final UTC-wall-clock row;
* pixel log ``365553`` is the first Asia/Shanghai-wall-clock row;
* snapshots are classified by their immutable ``last_log_id`` high-water
  mark, so a snapshot always uses the representation of the event it records.

``visit_logs`` has been ``timestamp with time zone`` since it was introduced,
and is deliberately not included here.
"""

from alembic import op
import sqlalchemy as sa


revision = '20260831_04'
down_revision = '20260830_03'
branch_labels = None
depends_on = None


LAST_UTC_PIXEL_LOG_ID = 365552
FIRST_SHANGHAI_PIXEL_LOG_ID = LAST_UTC_PIXEL_LOG_ID + 1


def _timezone_aware(bind, table: str, column: str) -> bool:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table):
        raise RuntimeError(f'{table} is missing; cannot normalize timestamp history')

    details = next((item for item in inspector.get_columns(table) if item['name'] == column), None)
    if details is None:
        raise RuntimeError(f'{table}.{column} is missing; cannot normalize timestamp history')

    column_type = details['type']
    if not isinstance(column_type, sa.DateTime):
        raise RuntimeError(f'{table}.{column} is {column_type!s}, expected a timestamp column')
    return bool(column_type.timezone)


def _require_expected_boundary(bind) -> None:
    pixel_ids = set(
        bind.execute(
            sa.text(
                '''
                SELECT id
                FROM pixel_logs
                WHERE id IN (:last_utc_id, :first_shanghai_id)
                '''
            ),
            {
                'last_utc_id': LAST_UTC_PIXEL_LOG_ID,
                'first_shanghai_id': FIRST_SHANGHAI_PIXEL_LOG_ID,
            },
        ).scalars()
    )
    expected_ids = {LAST_UTC_PIXEL_LOG_ID, FIRST_SHANGHAI_PIXEL_LOG_ID}
    if pixel_ids != expected_ids:
        raise RuntimeError(
            'The verified UTC/Asia-Shanghai pixel boundary is absent from this database. '
            'Refusing to reinterpret timestamp data from a different deployment.'
        )

    unmatched_snapshots = int(
        bind.execute(
            sa.text(
                '''
                SELECT count(*)
                FROM canvas_snapshots
                WHERE last_log_id IS NULL
                   OR last_log_id > (SELECT max(id) FROM pixel_logs)
                '''
            )
        ).scalar()
        or 0
    )
    if unmatched_snapshots:
        raise RuntimeError(
            f'Found {unmatched_snapshots} snapshots without a valid pixel-log high-water mark; '
            'repair snapshot metadata before normalizing timestamp history.'
        )


def _normalize_pixel_timestamps() -> None:
    op.execute(
        sa.text(
            f'''
            ALTER TABLE pixel_logs
                ALTER COLUMN created_at DROP DEFAULT,
                ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE
                USING CASE
                    WHEN id <= {LAST_UTC_PIXEL_LOG_ID}
                        THEN created_at AT TIME ZONE 'UTC'
                    ELSE created_at AT TIME ZONE 'Asia/Shanghai'
                END,
                ALTER COLUMN created_at SET DEFAULT now()
            '''
        )
    )


def _normalize_snapshot_timestamps() -> None:
    op.execute(
        sa.text(
            f'''
            ALTER TABLE canvas_snapshots
                ALTER COLUMN created_at DROP DEFAULT,
                ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE
                USING CASE
                    WHEN last_log_id <= {LAST_UTC_PIXEL_LOG_ID}
                        THEN created_at AT TIME ZONE 'UTC'
                    ELSE created_at AT TIME ZONE 'Asia/Shanghai'
                END,
                ALTER COLUMN created_at SET DEFAULT now()
            '''
        )
    )


def upgrade() -> None:
    bind = op.get_bind()
    pixel_is_aware = _timezone_aware(bind, 'pixel_logs', 'created_at')
    snapshot_is_aware = _timezone_aware(bind, 'canvas_snapshots', 'created_at')

    if pixel_is_aware and snapshot_is_aware:
        # Supports an environment where this repair was applied manually before
        # Alembic reached this revision, without reinterpreting data a second time.
        return
    if pixel_is_aware != snapshot_is_aware:
        raise RuntimeError(
            'pixel_logs and canvas_snapshots have different timestamp types; '
            'inspect the partial migration before retrying.'
        )

    _require_expected_boundary(bind)
    _normalize_pixel_timestamps()
    _normalize_snapshot_timestamps()


def downgrade() -> None:
    raise RuntimeError(
        'This timestamp-history repair cannot be downgraded safely; '
        'restore the pre-migration database backup instead.'
    )
