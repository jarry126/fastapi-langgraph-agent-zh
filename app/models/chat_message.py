"""持久化用户可见聊天轮次的业务消息模型."""

from typing import (
    ClassVar,
    TYPE_CHECKING,
    Optional,
)

from sqlalchemy import (
    JSON,
    Column,
)
from sqlmodel import (
    Field,
    Relationship,
)

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.session import Session
    from app.models.user import User


class ChatMessage(BaseModel, table=True):
    """已持久化的用户可见聊天轮次.

    Stores the business chat history independently from LangGraph checkpoints,
    which remain an internal workflow state store.
    """

    __tablename__: ClassVar[str] = "chat_message"  # pyright: ignore[reportIncompatibleVariableOverride]

    id: int = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="session.id", index=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    question: str
    answer: str
    message_metadata: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    session: "Session" = Relationship(back_populates="chat_messages")
    user: "User" = Relationship(back_populates="chat_messages")
