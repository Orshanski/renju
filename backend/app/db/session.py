from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def make_sessionmaker(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def session_scope(sm: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    """Только rollback-on-error + close. Коммит — ЯВНО в сервисах записи.
    Почему не авто-commit: SQLAlchemy autobegin открывает транзакцию на ЛЮБОМ
    SELECT, поэтому `session.in_transaction()` True и для read-only — отличить
    «были изменения» так нельзя; а DAL делает flush() (после него session.dirty/new
    пусты). Надёжная модель: писатели (admin_service.*) коммитят сами, читатели
    (get_current_user, get_me, list_users) не коммитят вовсе → ноль лишних fsync на GET."""
    session = sm()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
