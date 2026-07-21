"""App branding API."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_get_branding_defaults():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/settings/branding")
    assert res.status_code == 200
    data = res.json()
    assert data["app_name"] == "EvampOps"
    assert data["has_logo"] is False
    assert data["has_favicon"] is False


@pytest.mark.asyncio
async def test_update_branding_name():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.put("/api/settings/branding", json={"app_name": "Evamp Test"})
    assert res.status_code == 200
    assert res.json()["app_name"] == "Evamp Test"
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.put("/api/settings/branding", json={"app_name": "EvampOps"})


@pytest.mark.asyncio
async def test_upload_logo_and_favicon():
    transport = ASGITransport(app=app)
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        logo_res = await client.post(
            "/api/settings/branding/logo",
            files={"file": ("logo.png", png, "image/png")},
        )
        assert logo_res.status_code == 200
        assert logo_res.json()["has_logo"] is True
        fav_res = await client.post(
            "/api/settings/branding/favicon",
            files={"file": ("favicon.png", png, "image/png")},
        )
        assert fav_res.status_code == 200
        assert fav_res.json()["has_favicon"] is True
        logo_get = await client.get("/api/settings/branding/logo")
        assert logo_get.status_code == 200
        assert logo_get.headers["content-type"].startswith("image/png")
        await client.delete("/api/settings/branding/logo")
        await client.delete("/api/settings/branding/favicon")
