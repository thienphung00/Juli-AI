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


class FakeTikTokResponse:
    """The slice of ``requests.Response`` ``TikTokClient._handle_response`` reads."""

    def __init__(self, data: dict) -> None:
        self.status_code = 200
        self.text = ""
        self._body = {"code": 0, "message": "Success", "request_id": "fake", "data": data}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._body


class FakeTikTokTransport:
    """A ``requests.Session`` stand-in behind a real, guarded ``TikTokClient``.

    Never reaches TikTok (fast track P61-B tests). Every request is recorded with
    the access token it was signed with (the ``x-tts-access-token`` header), so a
    test can prove WHICH shop's credential a write went out under. Listings are
    held per product id: a detail GET answers the current listing, a listing edit
    (``PUT /product/{v}/products/{id}``) replaces its title / description, SEO and
    suggestion reads answer empty.
    """

    ACCESS_TOKEN_HEADER = "x-tts-access-token"

    def __init__(self, listings: dict[str, dict]) -> None:
        self.listings = {pid: dict(listing) for pid, listing in listings.items()}
        self.calls: list[dict] = []

    def _record(self, method: str, url: str, headers: dict | None, data: object) -> str:
        path = "/" + url.split("://", 1)[-1].split("/", 1)[-1].split("?", 1)[0]
        self.calls.append(
            {
                "method": method,
                "path": path,
                "access_token": (headers or {}).get(self.ACCESS_TOKEN_HEADER),
                "body": data,
            }
        )
        return path

    def get(self, url: str, params=None, headers=None, timeout=None) -> FakeTikTokResponse:
        path = self._record("GET", url, headers, None)
        product_id = path.rsplit("/", 1)[-1]
        if product_id in self.listings:
            return FakeTikTokResponse(dict(self.listings[product_id]))
        return FakeTikTokResponse({})

    def put(self, url: str, params=None, data=None, headers=None, timeout=None):
        import json

        path = self._record("PUT", url, headers, data)
        product_id = path.rsplit("/", 1)[-1]
        body = json.loads(data or "{}")
        listing = self.listings.setdefault(product_id, {"id": product_id})
        for field in ("title", "description"):
            if field in body:
                listing[field] = body[field]
        return FakeTikTokResponse({"product_id": product_id})

    def post(self, url: str, params=None, data=None, files=None, headers=None, timeout=None):
        self._record("POST", url, headers, data)
        return FakeTikTokResponse({})

    def writes(self) -> list[dict]:
        return [call for call in self.calls if call["method"] != "GET"]
