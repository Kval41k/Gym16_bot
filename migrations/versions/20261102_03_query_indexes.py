"""Indexes for scoped inbox and per-user practice history."""
from alembic import op
import sqlalchemy as sa

revision = '20261102_03'
down_revision = '20261101_02'
branch_labels = None
depends_on = None

INDEXES = (
    ('notifications', 'ix_notifications_user_id_id', ['user_id', 'id']),
    ('notifications', 'ix_notifications_user_read', ['user_id', 'read_at']),
    ('practice_sessions', 'ix_practice_sessions_user_answered', ['user_id', 'answered_at']),
)


def upgrade():
    for table, name, columns in INDEXES:
        if name not in {row['name'] for row in sa.inspect(op.get_bind()).get_indexes(table)}:
            op.create_index(name, table, columns)


def downgrade():
    for table, name, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table)
