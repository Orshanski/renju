"""CLI: создать первого админа.  uv run python -m scripts.create_admin <username> <password>"""

import asyncio
import sys

from app.config import Settings
from app.dal import users as dal
from app.db.engine import make_engine
from app.db.session import make_sessionmaker


async def create_admin(username: str, password: str) -> None:
    engine = make_engine(Settings())
    sm = make_sessionmaker(engine)
    try:
        async with sm() as session:
            if await dal.get_user_by_username(session, username) is not None:
                print(f"User '{username}' already exists.")
                raise SystemExit(1)
            uid = await dal.create_user(session, username, password, role="admin")
            await session.commit()
            print(f"Admin '{username}' created (id={uid}).")
    finally:
        await engine.dispose()


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: python -m scripts.create_admin <username> <password>")
        raise SystemExit(2)
    asyncio.run(create_admin(sys.argv[1], sys.argv[2]))


if __name__ == "__main__":
    main()
