"""App notepad API."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_notepad_get_and_update():
    transport = ASGITransport(app=app)
    marker = "Warehouse: Unit 4\nhttps://example.com/docs"
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        get_res = await client.get("/api/settings/notepad")
        assert get_res.status_code == 200
        assert isinstance(get_res.json()["body"], str)
        previous = get_res.json()["body"]

        put_res = await client.put("/api/settings/notepad", json={"body": marker})
        assert put_res.status_code == 200
        assert put_res.json()["body"] == marker

        again = await client.get("/api/settings/notepad")
        assert again.json()["body"] == marker

        # Restore whatever was in the DB (tests share the real database).
        await client.put("/api/settings/notepad", json={"body": previous})
