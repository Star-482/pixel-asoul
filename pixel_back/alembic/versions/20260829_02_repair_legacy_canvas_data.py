"""Normalize verified legacy pixel colors.

This migration intentionally handles only defects identified by the read-only
preflight and confirmed against the legacy implementation:

* ``#000`` was accepted by the browser as black, so it becomes ``#000000``.
* an empty color was rendered as white by the legacy Redis canvas store, so it
  becomes ``#FFFFFF`` in the durable event log.
Duplicate snapshot files are deliberately not repaired in this database-only
migration.  A path collision can refer to different canvas states, so
``scripts/reconcile_legacy_snapshots.py --apply`` reconstructs and compares
the PNG before it marks any metadata invalid.

Unknown invalid colors abort the migration rather than silently changing
historical meaning.
"""

from alembic import op
import sqlalchemy as sa


revision = '20260829_02'
down_revision = '20260829_01'
branch_labels = None
depends_on = None


def _count(bind, statement: str) -> int:
    return int(bind.execute(sa.text(statement)).scalar() or 0)


def upgrade() -> None:
    bind = op.get_bind()

    unsupported_colors = _count(
        bind,
        """
        SELECT count(*)
        FROM pixel_logs
        WHERE color IS NULL
           OR (color !~ '^#[0-9A-Fa-f]{6}$' AND color NOT IN ('#000', ''))
        """,
    )
    if unsupported_colors:
        raise RuntimeError(
            f'Found {unsupported_colors} unsupported legacy pixel colors; '
            'inspect and repair them manually before retrying the migration.'
        )

    bind.execute(
        sa.text("UPDATE pixel_logs SET color = '#000000' WHERE color = '#000'")
    )
    bind.execute(
        sa.text("UPDATE pixel_logs SET color = '#FFFFFF' WHERE color = ''")
    )

def downgrade() -> None:
    raise RuntimeError(
        'This history-preserving repair migration cannot be downgraded; '
        'restore the pre-migration database backup instead.'
    )
