"""Private inbox read state and content reports, preserving existing data."""
from alembic import op
import sqlalchemy as sa

revision = '20261101_02'
down_revision = '20261028_01'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {c['name'] for c in sa.inspect(bind).get_columns('notifications')}
    for name, column in (
        ('kind', sa.Column('kind', sa.String(30), nullable=False, server_default='general')),
        ('link', sa.Column('link', sa.String(80))),
        ('read_at', sa.Column('read_at', sa.DateTime(timezone=True))),
    ):
        if name not in columns:
            op.add_column('notifications', column)
    if 'content_reports' not in sa.inspect(bind).get_table_names():
        op.create_table('content_reports',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('reporter_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='SET NULL')),
            sa.Column('target_type', sa.String(16), nullable=False),
            sa.Column('target_id', sa.Integer(), nullable=False),
            sa.Column('post_id', sa.Integer(), nullable=False),
            sa.Column('reason', sa.String(40), nullable=False),
            sa.Column('details', sa.Text(), nullable=False),
            sa.Column('context_json', sa.Text(), nullable=False),
            sa.Column('status', sa.String(16), nullable=False),
            sa.Column('resolved_by', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='SET NULL')),
            sa.Column('resolution', sa.Text()),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('resolved_at', sa.DateTime(timezone=True)),
            sa.UniqueConstraint('reporter_id', 'target_type', 'target_id', name='uq_report_target_user'))
        for name in ('reporter_id', 'status', 'created_at'):
            op.create_index('ix_content_reports_' + name, 'content_reports', [name])


def downgrade():
    raise RuntimeError('Refusing to delete inbox state or reports; restore a verified backup instead')
