"""${message | trim}."""

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from typing import Sequence, Union

import sqlmodel  # noqa: F401
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# Alembic 使用的迁移版本标识符。
revision: str = ${repr(up_revision)}
down_revision: Union[str, Sequence[str], None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    """升级数据库结构。"""
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """回滚数据库结构。"""
    ${downgrades if downgrades else "pass"}
