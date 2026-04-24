"""
Shopify credentials: SHOPIFY_SHOP + SHOPIFY_ACCESS_TOKEN from env, or encrypted rows in api_credentials.
Environment variables take precedence when both are set.
"""
from __future__ import annotations

from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import encryption_service
from app.models.settings import APICredential

SHOPIFY_SERVICE = "shopify"
KEY_SHOP = "shop"
KEY_ACCESS_TOKEN = "access_token"


def shopify_from_env() -> Optional[Tuple[str, str]]:
    shop = (getattr(settings, "SHOPIFY_SHOP", None) or "").strip()
    token = (getattr(settings, "SHOPIFY_ACCESS_TOKEN", None) or "").strip()
    if shop and token:
        return (shop, token)
    return None


def shopify_env_configured() -> bool:
    return shopify_from_env() is not None


async def resolve_shopify_credentials(db: AsyncSession) -> Optional[Tuple[str, str]]:
    env = shopify_from_env()
    if env:
        return env
    result = await db.execute(
        select(APICredential).where(
            APICredential.service_name == SHOPIFY_SERVICE,
            APICredential.key_name.in_((KEY_SHOP, KEY_ACCESS_TOKEN)),
            APICredential.is_active.is_(True),
        )
    )
    rows = {c.key_name: c for c in result.scalars().all()}
    shop_row = rows.get(KEY_SHOP)
    tok_row = rows.get(KEY_ACCESS_TOKEN)
    if not shop_row or not tok_row:
        return None
    try:
        shop = encryption_service.decrypt(shop_row.encrypted_value).strip()
        token = encryption_service.decrypt(tok_row.encrypted_value).strip()
    except Exception:
        return None
    if not shop or not token:
        return None
    return (shop, token)


async def shopify_configured_db(db: AsyncSession) -> bool:
    return await resolve_shopify_credentials(db) is not None


async def get_shopify_token_from_db(db: AsyncSession) -> Optional[str]:
    result = await db.execute(
        select(APICredential).where(
            APICredential.service_name == SHOPIFY_SERVICE,
            APICredential.key_name == KEY_ACCESS_TOKEN,
            APICredential.is_active.is_(True),
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        return None
    try:
        return encryption_service.decrypt(row.encrypted_value).strip()
    except Exception:
        return None


async def upsert_shopify_credentials(db: AsyncSession, shop: str, access_token: str) -> None:
    for key_name, value in ((KEY_SHOP, shop), (KEY_ACCESS_TOKEN, access_token)):
        enc = encryption_service.encrypt(value)
        result = await db.execute(
            select(APICredential).where(
                APICredential.service_name == SHOPIFY_SERVICE,
                APICredential.key_name == key_name,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.encrypted_value = enc
            existing.is_active = True
        else:
            db.add(
                APICredential(
                    service_name=SHOPIFY_SERVICE,
                    key_name=key_name,
                    encrypted_value=enc,
                    is_active=True,
                )
            )
    await db.commit()


async def clear_shopify_credentials_db(db: AsyncSession) -> int:
    result = await db.execute(
        select(APICredential).where(APICredential.service_name == SHOPIFY_SERVICE)
    )
    rows = list(result.scalars().all())
    for r in rows:
        await db.delete(r)
    if rows:
        await db.commit()
    return len(rows)
