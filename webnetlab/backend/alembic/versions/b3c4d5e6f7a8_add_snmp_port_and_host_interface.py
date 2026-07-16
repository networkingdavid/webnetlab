"""add snmp_port to devices and host_interface to networks

Revision ID: b3c4d5e6f7a8
Revises: a1b2c3d4e5f6
Create Date: 2024-01-01 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'b3c4d5e6f7a8'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('devices',
        sa.Column('snmp_port', sa.Integer(), nullable=True))
    op.add_column('networks',
        sa.Column('host_interface', sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column('devices', 'snmp_port')
    op.drop_column('networks', 'host_interface')
