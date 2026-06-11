from app.auth import bump_token_epoch, hash_password
from app.dal import users as dal
from app.dtos.auth import UserDTO
from app.exceptions import ConflictError, NotFoundError


async def list_users(session) -> list[UserDTO]:
    users = await dal.list_users(session)
    return [UserDTO(id=u.id, username=u.username, role=u.role) for u in users]


async def create_user(session, username: str, password: str, role: str) -> int:
    if await dal.get_user_by_username(session, username) is not None:
        raise ConflictError("Username already exists")
    uid = await dal.create_user(session, username, password, role=role)
    await session.commit()  # писатель коммитит ЯВНО (session_scope не коммитит)
    return uid


async def delete_user(session, target_id: int, actor_id: int) -> None:
    target = await dal.get_user_by_id(session, target_id)
    if target is None:
        raise NotFoundError("User not found")
    if target_id == actor_id:
        raise ConflictError("Cannot delete yourself")
    if await dal.is_last_admin(session, target_id):
        raise ConflictError("Cannot delete the last admin")
    await dal.delete_user(session, target_id)
    await session.commit()


async def reset_password(session, target_id: int, new_password: str) -> None:
    target = await dal.get_user_by_id(session, target_id)
    if target is None:
        raise NotFoundError("User not found")
    target.password_hash = hash_password(new_password)
    await bump_token_epoch(session, target_id)  # отзыв сессий (autoflush сбросит password_hash)
    await session.commit()
