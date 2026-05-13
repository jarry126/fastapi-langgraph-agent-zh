"""Alembic 环境配置.

Loads the database URL from the application's settings so migrations
stay in sync with the running app configuration.
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

from alembic import context
from app.core.config import settings
from app.models.session import Session  # noqa: F401
from app.models.thread import Thread  # noqa: F401
from app.models.user import User  # noqa: F401

# Alembic 配置对象
config = context.config

# 从 ini 文件配置 Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 根据应用配置构建数据库 URL
DATABASE_URL = (
    f"postgresql://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
    f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
)
config.set_main_option("sqlalchemy.url", DATABASE_URL)

# 将 Alembic 指向 SQLModel metadata，以支持自动生成迁移
target_metadata = SQLModel.metadata

# 外部系统管理的表（LangGraph checkpointer、mem0、pgvector），Alembic 不应处理
EXCLUDE_TABLES = {
    "checkpoint_blobs",
    "checkpoint_writes",
    "checkpoint_migrations",
    "checkpoints",
    "longterm_memory",
    "mem0migrations",
}


def include_object(object, name, type_, reflected, compare_to):
    """过滤由外部系统管理的表."""
    if type_ == "table" and name in EXCLUDE_TABLES:
        return False
    return True


def run_migrations_offline() -> None:
    """以离线模式运行迁移.

    Emits SQL to stdout instead of executing against the database.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """以在线模式运行迁移.

    Creates an engine and runs migrations against the live database.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
