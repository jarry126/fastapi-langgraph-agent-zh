"""应用会话模型."""

from typing import (
    TYPE_CHECKING,
    Optional,
)

from sqlmodel import (
    Field,
    Relationship,
)

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.chat_message import ChatMessage
    from app.models.user import User


class Session(BaseModel, table=True):
    """用于存储聊天会话的模型.

    Attributes:
        id: 主键
        user_id: Foreign key to the user
        name: Name of the session (defaults to empty string)
        username: Display name copied from the user at session creation
        created_at: session 创建时间
        messages: Relationship to session messages
        user: Relationship to the session owner
    """

    id: str = Field(primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    name: str = Field(default="")
    username: Optional[str] = Field(default=None)
    user: "User" = Relationship(back_populates="sessions")
    chat_messages: list["ChatMessage"] = Relationship(back_populates="session")
