"""Client behaviour (retries, pagination) against a fake HTTP transport (no network)."""

import httpx
import pytest

from pipeline.ingest import manifold_client
from pipeline.ingest.manifold_client import ManifoldClient


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(manifold_client.time, "sleep", lambda s: None)


def client_with(handler) -> ManifoldClient:
    return ManifoldClient(min_interval=0, transport=httpx.MockTransport(handler))


def test_retries_on_429_then_succeeds():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) < 3:
            return httpx.Response(429, json={"error": "too many requests"})
        return httpx.Response(200, json={"ok": True})

    assert client_with(handler).get("/x") == {"ok": True}
    assert len(calls) == 3


def test_gives_up_after_max_attempts():
    with pytest.raises(RuntimeError, match="failed after 6 attempts"):
        client_with(lambda r: httpx.Response(503)).get("/x")


def test_does_not_retry_client_errors():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(404)

    with pytest.raises(httpx.HTTPStatusError):
        client_with(handler).get("/x")
    assert len(calls) == 1


def test_pagination_follows_before_cursor_and_stops_on_short_page():
    pages = {None: [{"id": "a"}, {"id": "b"}], "b": [{"id": "c"}]}
    seen = []

    def handler(request):
        before = request.url.params.get("before")
        seen.append(before)
        return httpx.Response(200, json=pages[before])

    got = list(client_with(handler).iter_market_pages(page_size=2))
    assert got == [pages[None], pages["b"]]
    assert seen == [None, "b"]
