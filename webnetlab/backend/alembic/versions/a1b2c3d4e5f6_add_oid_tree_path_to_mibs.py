"""add_oid_tree_path_to_mibs

Revision ID: a1b2c3d4e5f6
Revises: ecff710e6dff
Create Date: 2026-07-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'ecff710e6dff'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('mibs', sa.Column('oid_tree_path', sa.String(length=512), nullable=True))


def downgrade() -> None:
    op.drop_column('mibs', 'oid_tree_path')
