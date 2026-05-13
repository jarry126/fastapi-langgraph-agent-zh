"""应用数据库服务."""

from typing import (
    List,
    Optional,
)

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import QueuePool
from sqlmodel import (
    Session,
    col,
    create_engine,
    select,
)

from app.core.config import (
    Environment,
    settings,
)
from app.core.logging import logger
from app.models.chat_message import ChatMessage
from app.models.session import Session as ChatSession
from app.models.user import User


class DatabaseService:
    """数据库操作服务类.

    该类负责用户、会话和消息相关的数据库操作。
    使用 SQLModel 进行 ORM 操作，并维护数据库连接池。
    """

    def __init__(self):
        """初始化数据库服务和连接池."""
        try:
            # 配置当前环境对应的数据库连接池参数
            pool_size = settings.POSTGRES_POOL_SIZE
            max_overflow = settings.POSTGRES_MAX_OVERFLOW

            # 根据连接池配置创建数据库 engine
            connection_url = (
                f"postgresql://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
                f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
            )

            self.engine = create_engine(
                connection_url,
                pool_pre_ping=True,
                poolclass=QueuePool,
                pool_size=pool_size,
                max_overflow=max_overflow,
                pool_timeout=30,  # Connection timeout (seconds)
                pool_recycle=1800,  # Recycle connections after 30 minutes
            )

            logger.info("数据库连接池已初始化", pool_size=pool_size, max_overflow=max_overflow)
        except SQLAlchemyError as e:
            logger.error("database_initialization_error", error=str(e), environment=settings.ENVIRONMENT.value)
            # 生产环境不抛出异常，允许应用在数据库异常时继续启动
            if settings.ENVIRONMENT != Environment.PRODUCTION:
                raise

    async def create_user(self, email: str, password: str, username: str | None = None) -> User:
        """创建新用户.

        参数：
            email: 用户邮箱。 address
            password: Hashed password
            username: 可选显示名称。

        返回：
            User: 创建后的用户。
        """
        with Session(self.engine) as session:
            user = User(email=email, hashed_password=password, username=username)
            session.add(user)
            session.commit()
            session.refresh(user)
            logger.info("用户已创建", email=email)
            return user

    async def get_user(self, user_id: int) -> Optional[User]:
        """根据 ID 获取用户.

        参数：
            user_id: 要获取的用户 ID。

        返回：
            Optional[User]: 找到时返回用户，否则返回 None。
        """
        with Session(self.engine) as session:
            user = session.get(User, user_id)
            return user

    async def get_user_by_email(self, email: str) -> Optional[User]:
        """根据邮箱获取用户.

        参数：
            email: 要查询的用户邮箱。

        返回：
            Optional[User]: 找到时返回用户，否则返回 None。
        """
        with Session(self.engine) as session:
            statement = select(User).where(User.email == email)
            user = session.exec(statement).first()
            return user

    async def delete_user_by_email(self, email: str) -> bool:
        """根据邮箱删除用户.

        参数：
            email: 要删除的用户邮箱。

        返回：
            bool: 删除成功返回 True，用户不存在返回 False。
        """
        with Session(self.engine) as session:
            user = session.exec(select(User).where(User.email == email)).first()
            if not user:
                return False

            session.delete(user)
            session.commit()
            logger.info("用户已删除", email=email)
            return True

    async def create_session(
        self, session_id: str, user_id: int, name: str = "", username: str | None = None
    ) -> ChatSession:
        """创建新的聊天会话.

        参数：
            session_id: 新会话 ID。
            user_id: 会话所属用户 ID。
            name: 可选会话名称，默认空字符串。
            username: Display name copied from the user for LLM personalization

        返回：
            ChatSession: 创建后的会话。
        """
        with Session(self.engine) as session:
            chat_session = ChatSession(id=session_id, user_id=user_id, name=name, username=username)
            session.add(chat_session)
            session.commit()
            session.refresh(chat_session)
            logger.info("会话已创建", session_id=session_id, user_id=user_id, name=name)
            return chat_session

    async def delete_session(self, session_id: str) -> bool:
        """根据 ID 删除会话.

        参数：
            session_id: 要删除的会话 ID。

        返回：
            bool: 删除成功返回 True，会话不存在返回 False。
        """
        with Session(self.engine) as session:
            chat_session = session.get(ChatSession, session_id)
            if not chat_session:
                return False

            messages = session.exec(select(ChatMessage).where(col(ChatMessage.session_id) == session_id)).all()
            for message in messages:
                session.delete(message)
            session.delete(chat_session)
            session.commit()
            logger.info("会话已删除", session_id=session_id)
            return True

    async def get_session(self, session_id: str) -> Optional[ChatSession]:
        """根据 ID 获取会话.

        参数：
            session_id: 要获取的会话 ID。

        返回：
            Optional[ChatSession]: 找到时返回会话，否则返回 None。
        """
        with Session(self.engine) as session:
            chat_session = session.get(ChatSession, session_id)
            return chat_session

    async def get_user_session(self, session_id: str, user_id: int) -> Optional[ChatSession]:
        """仅在会话属于指定用户时，根据 ID 获取会话."""
        with Session(self.engine) as session:
            statement = select(ChatSession).where(
                col(ChatSession.id) == session_id,
                col(ChatSession.user_id) == user_id,
            )
            chat_session = session.exec(statement).first()
            return chat_session

    async def get_user_sessions(self, user_id: int) -> List[ChatSession]:
        """获取指定用户的所有会话.

        参数：
            user_id: 用户 ID。

        返回：
            List[ChatSession]: 用户的会话列表。
        """
        with Session(self.engine) as session:
            statement = (
                select(ChatSession).where(col(ChatSession.user_id) == user_id).order_by(col(ChatSession.created_at))
            )
            sessions = session.exec(statement).all()
            return list(sessions)

    async def update_session_name(self, session_id: str, name: str) -> ChatSession:
        """更新会话名称.

        参数：
            session_id: 要更新的会话 ID。
            name: 新会话名称。

        返回：
            ChatSession: 更新后的会话。

        抛出：
            HTTPException: 会话不存在时抛出。
        """
        with Session(self.engine) as session:
            chat_session = session.get(ChatSession, session_id)
            if not chat_session:
                raise HTTPException(status_code=404, detail="Session not found")

            chat_session.name = name
            session.add(chat_session)
            session.commit()
            session.refresh(chat_session)
            logger.info("会话名称已更新", session_id=session_id, name=name)
            return chat_session

    async def create_chat_message(
        self,
        session_id: str,
        user_id: int,
        question: str,
        answer: str,
        metadata: dict | None = None,
    ) -> ChatMessage:
        """持久化一轮用户可见的问题和答案."""
        with Session(self.engine) as session:
            chat_message = ChatMessage(
                session_id=session_id,
                user_id=user_id,
                question=question,
                answer=answer,
                message_metadata=metadata,
            )
            session.add(chat_message)
            session.commit()
            session.refresh(chat_message)
            logger.info("问答记录已保存", session_id=session_id, user_id=user_id, chat_message_id=chat_message.id)
            return chat_message

    async def get_chat_messages(self, session_id: str, user_id: int) -> List[ChatMessage]:
        """获取指定用户会话中的业务聊天轮次."""
        with Session(self.engine) as session:
            statement = (
                select(ChatMessage)
                .where(
                    col(ChatMessage.session_id) == session_id,
                    col(ChatMessage.user_id) == user_id,
                )
                .order_by(col(ChatMessage.created_at), col(ChatMessage.id))
            )
            messages = session.exec(statement).all()
            return list(messages)

    async def delete_chat_messages(self, session_id: str, user_id: int) -> int:
        """删除指定用户会话中的业务聊天轮次."""
        with Session(self.engine) as session:
            messages = session.exec(
                select(ChatMessage).where(
                    col(ChatMessage.session_id) == session_id,
                    col(ChatMessage.user_id) == user_id,
                )
            ).all()
            deleted_count = len(messages)
            for message in messages:
                session.delete(message)
            session.commit()
            logger.info("问答记录已删除", session_id=session_id, user_id=user_id, count=deleted_count)
            return deleted_count

    def get_session_maker(self):
        """获取用于创建数据库会话的 session maker.

        返回：
            Session: SQLModel session maker。
        """
        return Session(self.engine)

    async def health_check(self) -> bool:
        """检查数据库连接健康状态.

        返回：
            bool: 数据库健康返回 True，否则返回 False。
        """
        try:
            with Session(self.engine) as session:
                # 执行简单查询检查连接是否可用
                session.exec(select(1)).first()
                return True
        except Exception as e:
            logger.error("database_health_check_failed", error=str(e))
            return False


# 创建单例实例
database_service = DatabaseService()
