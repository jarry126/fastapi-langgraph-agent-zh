"""新增聊天消息表.

Revision ID: c7f2a08e4b1d
Revises: b25d38b0cd7c
Create Date: 2026-05-12 17:45:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel  # noqa: F401

from alembic import op

# Alembic 使用的迁移版本标识符。
revision: str = "c7f2a08e4b1d"
down_revision: Union[str, Sequence[str], None] = "b25d38b0cd7c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级数据库结构."""
    op.create_table(
        "chat_message",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("question", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("answer", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("message_metadata", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["session.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_chat_message_session_id"), "chat_message", ["session_id"], unique=False)
    op.create_index(op.f("ix_chat_message_user_id"), "chat_message", ["user_id"], unique=False)


def downgrade() -> None:
    """回滚数据库结构."""
    op.drop_index(op.f("ix_chat_message_user_id"), table_name="chat_message")
    op.drop_index(op.f("ix_chat_message_session_id"), table_name="chat_message")
    op.drop_table("chat_message")
