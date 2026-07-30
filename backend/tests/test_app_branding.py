"""App branding API.

Destructive tests restore prior logo/favicon so they never wipe a live DB icon.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.mark.asyncio
async def test_get_branding_shape():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/settings/branding")
    assert res.status_code == 200
    data = res.json()
    assert "app_name" in data
    assert isinstance(data["has_logo"], bool)
    assert isinstance(data["has_favicon"], bool)


@pytest.mark.asyncio
async def test_update_branding_name_restores():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        before = (await client.get("/api/settings/branding")).json()
        original_name = before["app_name"]
        res = await client.put("/api/settings/branding", json={"app_name": "Evamp Test"})
        assert res.status_code == 200
        assert res.json()["app_name"] == "Evamp Test"
        restore = await client.put("/api/settings/branding", json={"app_name": original_name})
        assert restore.status_code == 200
        assert restore.json()["app_name"] == original_name


@pytest.mark.asyncio
async def test_upload_icon_sets_logo_and_favicon_then_restores():
    """Upload must set both; prior assets are restored so live icons are not wiped."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        before = (await client.get("/api/settings/branding")).json()
        had_logo = before["has_logo"]
        had_favicon = before["has_favicon"]
        prev_logo = (
            await client.get("/api/settings/branding/logo")
            if had_logo
            else None
        )
        prev_favicon = (
            await client.get("/favicon.ico")
            if had_favicon
            else None
        )

        icon_res = await client.post(
            "/api/settings/branding/icon",
            files={"file": ("icon.png", PNG_1X1, "image/png")},
        )
        assert icon_res.status_code == 200
        body = icon_res.json()
        assert body["has_logo"] is True
        assert body["has_favicon"] is True

        logo_get = await client.get("/api/settings/branding/logo")
        assert logo_get.status_code == 200
        assert logo_get.headers["content-type"].startswith("image/png")

        fav_get = await client.get("/favicon.ico")
        assert fav_get.status_code == 200

        # Restore previous state — never leave the live icon wiped.
        if had_logo and prev_logo is not None and prev_logo.status_code == 200:
            await client.post(
                "/api/settings/branding/logo",
                files={
                    "file": (
                        "restore.png",
                        prev_logo.content,
                        prev_logo.headers.get("content-type", "image/png"),
                    )
                },
            )
        else:
            await client.delete("/api/settings/branding/logo")

        if had_favicon and prev_favicon is not None and prev_favicon.status_code == 200:
            await client.post(
                "/api/settings/branding/favicon",
                files={
                    "file": (
                        "restore.ico",
                        prev_favicon.content,
                        prev_favicon.headers.get("content-type", "image/png"),
                    )
                },
            )
        else:
            await client.delete("/api/settings/branding/favicon")
