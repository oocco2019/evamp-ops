"""
Shared eBay OAuth: get a valid access token from DB (refresh_token), refresh if needed.
Used by stock (order import) and messages (sync) APIs.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException

from app.core.security import encryption_service
from app.models.settings import APICredential
from app.services.ebay_client import refresh_access_token


async def get_ebay_access_token(db: AsyncSession) -> str:
    """
    Return a valid eBay access token using the stored refresh token.
    Raises HTTPException 400 if eBay is not connected.
    """
    result = await db.execute(
        select(APICredential).where(
            APICredential.service_name == "ebay",
            APICredential.key_name == "refresh_token",
            APICredential.is_active == True,
        )
    )
    cred = result.scalar_one_or_none()
    if not cred:
        raise HTTPException(
            status_code=400,
            detail="eBay not connected. Connect eBay first in Settings.",
        )
    refresh_token = encryption_service.decrypt(cred.encrypted_value)
    token_data = await refresh_access_token(refresh_token)
    return token_data["access_token"]
