"""Persist the short high-risk observation window after CAPTCHA success."""

from alembic import op
import sqlalchemy as sa


revision = '20260830_03'
down_revision = '20260829_02'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column['name'] for column in sa.inspect(bind).get_columns('moderation_states')}
    if 'post_verification_watch_until' not in columns:
        op.add_column(
            'moderation_states',
            sa.Column('post_verification_watch_until', sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    raise RuntimeError(
        'This moderation-history migration is intentionally non-destructive; '
        'restore a database backup to roll back.'
    )
