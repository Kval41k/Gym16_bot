"""Keep a reset marker so stale devices cannot silently restore removed registrations."""
from alembic import op
import sqlalchemy as sa
revision = '20261105_04'
down_revision = '20261102_03'
branch_labels = None
depends_on = None

def upgrade():
    if 'registration_reset' not in {c['name'] for c in sa.inspect(op.get_bind()).get_columns('users')}:
        op.add_column('users', sa.Column('registration_reset', sa.Boolean(), nullable=False, server_default=sa.false()))
    if op.get_bind().dialect.name == 'postgresql':
        op.alter_column('practice_sessions', 'answer', type_=sa.Text(), existing_type=sa.String(1000))

def downgrade():
    op.drop_column('users', 'registration_reset')
