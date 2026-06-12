import asyncio
from collections.abc import AsyncGenerator


class InMemoryEventHub:
    def __init__(self):
        self._seq: dict[str, int] = {}
        self._log: dict[str, list[dict]] = {}
        self._subs: dict[str, list[asyncio.Queue]] = {}

    def publish(self, game_id: str, type_: str, payload: dict) -> int:
        seq = self._seq.get(game_id, 0) + 1
        self._seq[game_id] = seq
        ev = {"seq": seq, "type": type_, "payload": payload}
        self._log.setdefault(game_id, []).append(ev)
        for q in self._subs.get(game_id, []):
            q.put_nowait(ev)
        return seq

    def cursor(self, game_id: str) -> int:
        return self._seq.get(game_id, 0)

    async def subscribe(
        self, game_id: str, since: int, idle_timeout: float | None = None
    ) -> AsyncGenerator[dict, None]:  # noqa: UP043
        cur = self._seq.get(game_id, 0)
        if since > cur:  # курсор «из будущего» — недостижим
            yield {"seq": cur, "type": "reset", "payload": {}}
            return
        for ev in self._log.get(game_id, []):  # реплей из буфера
            if ev["seq"] > since:
                yield ev
        q: asyncio.Queue = asyncio.Queue()
        self._subs.setdefault(game_id, []).append(q)
        try:
            while True:
                if idle_timeout is None:
                    yield await q.get()
                else:
                    try:  # таймаут оборачивает q.get() ВНУТРИ генератора (см. note)
                        yield await asyncio.wait_for(q.get(), idle_timeout)
                    except TimeoutError:  # idle → ping, подписку НЕ закрываем
                        yield {"seq": self._seq.get(game_id, 0), "type": "ping", "payload": {}}
        finally:
            self._subs[game_id].remove(q)
