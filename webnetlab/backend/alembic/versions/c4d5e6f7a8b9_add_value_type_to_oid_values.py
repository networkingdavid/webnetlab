"""add value_type to oid_values

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2024-01-01 00:00:01.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'c4d5e6f7a8b9'
down_revision = 'b3c4d5e6f7a8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('oid_values',
        sa.Column('value_type', sa.String(length=32), nullable=False, server_default='string'))


def downgrade() -> None:
    op.drop_column('oid_values', 'value_type')
