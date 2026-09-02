"""Hand-written doubles with the real collaborator's signatures."""

from __future__ import annotations


class FakeAsyncRedis:
    """In-memory ``redis.asyncio`` subset: ``get`` / ``set`` / ``delete``.

    Set ``get_raises`` or ``set_raises`` to an exception instance to simulate
    an outage on that operation; every other call keeps working, which is how
    a real partial failure looks.
    """

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.get_raises: Exception | None = None
        self.set_raises: Exception | None = None
        self.closed = False

    async def get(self, key: str) -> str | None:
        if self.get_raises is not None:
            raise self.get_raises
        return self.store.get(key)

    async def set(self, key: str, value: str) -> bool:
        if self.set_raises is not None:
            raise self.set_raises
        self.store[key] = value
        return True

    async def delete(self, *keys: str) -> int:
        removed = sum(1 for key in keys if self.store.pop(key, None) is not None)
        return removed

    async def aclose(self) -> None:
        self.closed = True


__all__ = ["FakeAsyncRedis"]
