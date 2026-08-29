from __future__ import annotations

from typing import TypeAlias

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


AsyncSessionFactory: TypeAlias = async_sessionmaker[AsyncSession]


def create_database(
    database_url: str,
    *,
    sql_echo: bool = False,
) -> tuple[AsyncEngine, AsyncSessionFactory]:
    engine = create_async_engine(
        database_url,
        echo=sql_echo,
        pool_pre_ping=True,
        future=True,
    )
    return engine, async_sessionmaker(engine, expire_on_commit=False)
