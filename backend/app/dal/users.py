from sqlalchemy import func, select

from ..auth import hash_password
from ..models.user import User


async def get_user_by_id(session, user_id: int) -> User | None:
    return await session.get(User, user_id)


async def get_user_by_username(session, username: str) -> User | None:
    return (
        await session.execute(select(User).where(User.username == username))
    ).scalar_one_or_none()


async def list_users(session) -> list[User]:
    return list((await session.execute(select(User).order_by(User.id))).scalars())


async def create_user(session, username: str, password: str, role: str = "user") -> int:
    user = User(username=username, password_hash=hash_password(password), role=role)
    session.add(user)
    await session.flush()  # получить id без commit (commit — зона сервиса/сессии)
    return user.id


async def delete_user(session, user_id: int) -> None:
    user = await session.get(User, user_id)
    if user is not None:
        await session.delete(user)


async def count_admins(session) -> int:
    return (
        await session.execute(select(func.count()).select_from(User).where(User.role == "admin"))
    ).scalar_one()


async def is_last_admin(session, user_id: int) -> bool:
    user = await session.get(User, user_id)
    if user is None or user.role != "admin":
        return False
    return await count_admins(session) <= 1
