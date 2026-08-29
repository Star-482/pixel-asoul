"""Add V2 durability, anonymous moderation and administration metadata.

The migration is additive. Historical pixels, visits and snapshot rows stay in
place; old rows gain deterministic request identifiers so the unique index can
be introduced safely.
"""

from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa


revision = '20260829_01'
down_revision = None
branch_labels = None
depends_on = None


def _column_names(bind, table: str) -> set[str]:
    inspector = sa.inspect(bind)
    return {column['name'] for column in inspector.get_columns(table)} if inspector.has_table(table) else set()


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    bind = op.get_bind()
    if column.name not in _column_names(bind, table):
        op.add_column(table, column)


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table('pixel_logs'):
        raise RuntimeError('pixel_logs is missing; initialize the legacy schema before applying V2 migration')

    _add_column_if_missing('pixel_logs', sa.Column('request_id', sa.String(36), nullable=True))
    _add_column_if_missing('pixel_logs', sa.Column('visitor_id', sa.String(36), nullable=True))
    _add_column_if_missing('pixel_logs', sa.Column('visit_id', sa.BigInteger(), nullable=True))
    _add_column_if_missing('pixel_logs', sa.Column('previous_color', sa.String(7), nullable=True))
    _add_column_if_missing('pixel_logs', sa.Column('source', sa.String(32), nullable=False, server_default='user'))
    _add_column_if_missing('pixel_logs', sa.Column('restore_operation_id', sa.String(36), nullable=True))

    _add_column_if_missing('visit_logs', sa.Column('visitor_id', sa.String(36), nullable=True))
    _add_column_if_missing('visit_logs', sa.Column('connection_id', sa.String(36), nullable=True))
    _add_column_if_missing('visit_logs', sa.Column('disconnected_at', sa.DateTime(timezone=True), nullable=True))

    _add_column_if_missing('canvas_snapshots', sa.Column('width', sa.Integer(), nullable=True))
    _add_column_if_missing('canvas_snapshots', sa.Column('height', sa.Integer(), nullable=True))
    _add_column_if_missing('canvas_snapshots', sa.Column('sha256', sa.String(64), nullable=True))
    _add_column_if_missing('canvas_snapshots', sa.Column('status', sa.String(16), nullable=False, server_default='valid'))

    old_ids = [row[0] for row in bind.execute(sa.text('SELECT id FROM pixel_logs WHERE request_id IS NULL'))]
    for pixel_id in old_ids:
        bind.execute(
            sa.text('UPDATE pixel_logs SET request_id = :request_id WHERE id = :id'),
            {'id': pixel_id, 'request_id': str(uuid5(NAMESPACE_URL, f'pixel-log:{pixel_id}'))},
        )
    bind.execute(sa.text("UPDATE pixel_logs SET source = 'user' WHERE source IS NULL"))
    bind.execute(sa.text("UPDATE canvas_snapshots SET status = 'valid' WHERE status IS NULL OR status = 'ready'"))

    op.create_table(
        'site_counters',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('total_visits', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('total_placed_pixels', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.CheckConstraint('id = 1', name='ck_site_counters_singleton'),
    )
    bind.execute(sa.text('''
        INSERT INTO site_counters (id, total_visits, total_placed_pixels)
        SELECT 1, (SELECT count(*) FROM visit_logs), (SELECT count(*) FROM pixel_logs WHERE source = 'user')
        ON CONFLICT (id) DO NOTHING
    '''))
    op.create_table(
        'moderation_states',
        sa.Column('visitor_id', sa.String(36), primary_key=True),
        sa.Column('verified_until', sa.DateTime(timezone=True)),
        sa.Column('blocked_until', sa.DateTime(timezone=True)),
        sa.Column('challenge_required_until', sa.DateTime(timezone=True)),
        sa.Column('strike_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('challenge_failures', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_table(
        'restore_plans',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_by', sa.String(64), nullable=False),
        sa.Column('target_event_id', sa.BigInteger(), nullable=False),
        sa.Column('head_event_id', sa.BigInteger(), nullable=False),
        sa.Column('mode', sa.String(32), nullable=False),
        sa.Column('filters_json', sa.Text(), nullable=False),
        sa.Column('preview_file_path', sa.String(255)),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(16), nullable=False, server_default='ready'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_table(
        'restore_operations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('plan_id', sa.String(36), sa.ForeignKey('restore_plans.id'), nullable=False),
        sa.Column('created_by', sa.String(64), nullable=False),
        sa.Column('affected_pixels', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('skipped_pixels', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(16), nullable=False, server_default='running'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
    )
    op.create_table(
        'admin_actions',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('admin_id', sa.String(64), nullable=False),
        sa.Column('action', sa.String(64), nullable=False),
        sa.Column('details_json', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )

    indexes = [
        ('ux_pixel_logs_request_id', 'pixel_logs', ['request_id'], True),
        ('ix_pixel_logs_visitor_created', 'pixel_logs', ['visitor_id', 'created_at'], False),
        ('ix_pixel_logs_visit_id', 'pixel_logs', ['visit_id'], False),
        ('ix_pixel_logs_created_id', 'pixel_logs', ['created_at', 'id'], False),
        ('ix_pixel_logs_xy_id', 'pixel_logs', ['x', 'y', 'id'], False),
    ]
    existing = {item['name'] for item in sa.inspect(bind).get_indexes('pixel_logs')}
    for name, table, columns, unique in indexes:
        if name not in existing:
            op.create_index(name, table, columns, unique=unique)


def downgrade() -> None:
    # Deliberately retain operational audit/history data. Rollback is performed
    # by restoring the pre-migration database backup described in deployment.
    raise RuntimeError('This additive safety migration has no destructive downgrade')
