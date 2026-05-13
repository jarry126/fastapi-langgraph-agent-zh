"""应用用户模型."""

from typing import (
    TYPE_CHECKING,
    List,
    Optional,
)

import bcrypt
from sqlmodel import (
    Field,
    Relationship,
)

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.chat_message import ChatMessage
    from app.models.session import Session


class User(BaseModel, table=True):
    """用于存储用户账号的模型.

    Attributes:
        id: 主键
        email: 用户邮箱。 (unique)
        hashed_password: Bcrypt hashed password
        username: 可选显示名称。 for the user
        created_at: 用户创建时间
        sessions: Relationship to user's chat sessions
    """

    id: int = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    hashed_password: str
    username: Optional[str] = Field(default=None, index=False)
    sessions: List["Session"] = Relationship(back_populates="user")
    chat_messages: List["ChatMessage"] = Relationship(back_populates="user")

    def verify_password(self, password: str) -> bool:
        """校验提供的密码是否与哈希匹配."""
        return bcrypt.checkpw(password.encode("utf-8"), self.hashed_password.encode("utf-8"))

    @staticmethod
    def hash_password(password: str) -> str:
        """使用 bcrypt 对密码进行哈希."""
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


# 避免循环导入
from app.models.session import Session  # noqa: E402
