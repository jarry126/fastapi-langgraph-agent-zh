"""应用线程模型."""

from datetime import (
    UTC,
    datetime,
)

from sqlmodel import (
    Field,
    SQLModel,
)


class Thread(SQLModel, table=True):
    """用于存储会话线程的模型.

    Attributes:
        id: 主键
        created_at: thread 创建时间
        messages: Relationship to messages in this thread
    """

    id: str = Field(primary_key=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
