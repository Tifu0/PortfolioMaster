"""Test the refresh revision shared by stream consumers and config polling."""

import asyncio
import json
import uuid

from backend.api.routers import refresh


def test_listening_stream_reports_revision_and_releases_subscription(monkeypatch):
    monkeypatch.setattr(refresh, "_sse_subscribers", set())
    stamp = "2026-01-02T12:00:00+00:00"
    monkeypatch.setitem(refresh._state, "last_refresh_at", stamp)
    monkeypatch.setitem(refresh._state, "refresh_counter", 5)
    monkeypatch.setitem(refresh._state, "is_refreshing", False)

    async def listen():
        response = await refresh.refresh_stream(mode="listen", user_id=uuid.uuid4())
        stream = response.body_iterator
        try:
            connection = json.loads((await anext(stream)).removeprefix("data: "))
            assert connection["type"] == "connected"
            assert connection["last_refresh_at"] == stamp
            assert connection["refresh_counter"] == 5
            refresh._broadcast_refresh_event({"type": "complete"})
            completion = json.loads((await anext(stream)).removeprefix("data: "))
            assert completion["last_refresh_at"] == stamp
            assert completion["refresh_counter"] == 5
        finally:
            await stream.aclose()
            assert refresh._get_active_sse_subscribers_count() == 0

    asyncio.run(listen())
