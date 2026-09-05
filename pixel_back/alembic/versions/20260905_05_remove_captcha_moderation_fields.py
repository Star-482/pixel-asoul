"""Replace CAPTCHA moderation columns with overwrite cooldown escalation."""

from alembic import op
import sqlalchemy as sa


revision = '20260905_05'
down_revision = '20260831_04'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column['name'] for column in inspector.get_columns('moderation_states')}
    for name in (
        'challenge_required_until',
        'challenge_failures',
        'verified_until',
        'post_verification_watch_until',
    ):
        if name in columns:
            op.drop_column('moderation_states', name)
    if 'overwrite_cooldown_until' not in columns:
        op.add_column(
            'moderation_states',
            sa.Column('overwrite_cooldown_until', sa.DateTime(timezone=True), nullable=True),
        )
    if 'overwrite_watch_until' not in columns:
        op.add_column(
            'moderation_states',
            sa.Column('overwrite_watch_until', sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    raise RuntimeError(
        'This moderation-history migration is intentionally non-destructive; '
        'restore a database backup to roll back.'
    )
