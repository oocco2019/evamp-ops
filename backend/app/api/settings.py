"""
Settings API endpoints (GN01)
- API credential management
- AI model selection
- Warehouse management
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, Field

from app.core.database import get_db
from app.core.security import encryption_service
from app.models.settings import APICredential, AIModelSetting, Warehouse

router = APIRouter()


# === Pydantic Schemas ===

class APICredentialCreate(BaseModel):
    """Schema for creating API credentials"""
    service_name: str = Field(..., description="e.g., ebay, anthropic, openai")
    key_name: str = Field(..., description="e.g., app_id, api_key")
    value: str = Field(..., description="Plain text value (will be encrypted)")


class APICredentialResponse(BaseModel):
    """Schema for API credential response (never returns decrypted value)"""
    id: int
    service_name: str
    key_name: str
    is_active: bool
    
    model_config = {"from_attributes": True}


class APICredentialTest(BaseModel):
    """Test if credentials are set"""
    service_name: str
    is_configured: bool
    keys_present: List[str]


class AIModelSettingCreate(BaseModel):
    """Schema for AI model configuration"""
    provider: str = Field(..., description="anthropic, openai, or litellm")
    model_name: str = Field(..., description="e.g., claude-3-5-sonnet-20241022")
    is_default: bool = False
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 2000
    system_prompt_override: Optional[str] = None


class AIModelSettingResponse(BaseModel):
    """Schema for AI model response"""
    id: int
    provider: str
    model_name: str
    is_default: bool
    temperature: Optional[float]
    max_tokens: Optional[int]
    
    model_config = {"from_attributes": True}


class WarehouseCreate(BaseModel):
    """Schema for warehouse creation"""
    shortname: str
    address: str
    country_code: str = Field(..., max_length=2, description="ISO 3166-1 alpha-2")


class WarehouseResponse(BaseModel):
    """Schema for warehouse response"""
    id: int
    shortname: str
    address: str
    country_code: str
    
    model_config = {"from_attributes": True}


# === API Credential Endpoints ===

@router.post("/credentials", response_model=APICredentialResponse, status_code=status.HTTP_201_CREATED)
async def create_credential(
    credential: APICredentialCreate,
    db: AsyncSession = Depends(get_db)
):
    """
    Store an API credential (encrypted).
    GN01: Secure API key storage.
    """
    # Encrypt the value
    encrypted_value = encryption_service.encrypt(credential.value)
    
    # Check if credential already exists
    result = await db.execute(
        select(APICredential).where(
            APICredential.service_name == credential.service_name,
            APICredential.key_name == credential.key_name
        )
    )
    existing = result.scalar_one_or_none()
    
    if existing:
        # Update existing
        existing.encrypted_value = encrypted_value
        existing.is_active = True
        await db.commit()
        await db.refresh(existing)
        return existing
    
    # Create new
    db_credential = APICredential(
        service_name=credential.service_name,
        key_name=credential.key_name,
        encrypted_value=encrypted_value,
        is_active=True
    )
    db.add(db_credential)
    await db.commit()
    await db.refresh(db_credential)
    
    return db_credential


@router.get("/credentials", response_model=List[APICredentialResponse])
async def list_credentials(
    service_name: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    List all stored credentials (without decrypted values).
    Optionally filter by service_name.
    """
    query = select(APICredential)
    if service_name:
        query = query.where(APICredential.service_name == service_name)
    
    result = await db.execute(query)
    credentials = result.scalars().all()
    return credentials


@router.get("/credentials/test/{service_name}", response_model=APICredentialTest)
async def test_credentials(
    service_name: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Check if credentials are configured for a service.
    """
    result = await db.execute(
        select(APICredential).where(
            APICredential.service_name == service_name,
            APICredential.is_active == True
        )
    )
    credentials = result.scalars().all()
    
    return APICredentialTest(
        service_name=service_name,
        is_configured=len(credentials) > 0,
        keys_present=[c.key_name for c in credentials]
    )


@router.delete("/credentials/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(
    credential_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Delete an API credential"""
    result = await db.execute(
        select(APICredential).where(APICredential.id == credential_id)
    )
    credential = result.scalar_one_or_none()
    
    if not credential:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found"
        )
    
    await db.delete(credential)
    await db.commit()


# === AI Model Settings Endpoints ===

@router.post("/ai-models", response_model=AIModelSettingResponse, status_code=status.HTTP_201_CREATED)
async def create_ai_model_setting(
    model_setting: AIModelSettingCreate,
    db: AsyncSession = Depends(get_db)
):
    """
    Configure AI model settings.
    If is_default=True, unset other defaults.
    """
    # If setting as default, unset other defaults
    if model_setting.is_default:
        result = await db.execute(
            select(AIModelSetting).where(AIModelSetting.is_default == True)
        )
        existing_defaults = result.scalars().all()
        for existing in existing_defaults:
            existing.is_default = False
    
    # Create new setting
    db_setting = AIModelSetting(**model_setting.model_dump())
    db.add(db_setting)
    await db.commit()
    await db.refresh(db_setting)
    
    return db_setting


@router.get("/ai-models", response_model=List[AIModelSettingResponse])
async def list_ai_model_settings(
    db: AsyncSession = Depends(get_db)
):
    """List all AI model configurations"""
    result = await db.execute(select(AIModelSetting))
    settings = result.scalars().all()
    return settings


@router.get("/ai-models/default", response_model=AIModelSettingResponse)
async def get_default_ai_model(
    db: AsyncSession = Depends(get_db)
):
    """Get the current default AI model"""
    result = await db.execute(
        select(AIModelSetting).where(AIModelSetting.is_default == True)
    )
    setting = result.scalar_one_or_none()
    
    if not setting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No default AI model configured. Please configure one in settings."
        )
    
    return setting


@router.patch("/ai-models/{setting_id}/set-default", response_model=AIModelSettingResponse)
async def set_default_ai_model(
    setting_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Set a specific AI model as default"""
    # Get the setting
    result = await db.execute(
        select(AIModelSetting).where(AIModelSetting.id == setting_id)
    )
    setting = result.scalar_one_or_none()
    
    if not setting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="AI model setting not found"
        )
    
    # Unset other defaults
    result = await db.execute(
        select(AIModelSetting).where(AIModelSetting.is_default == True)
    )
    existing_defaults = result.scalars().all()
    for existing in existing_defaults:
        existing.is_default = False
    
    # Set this one as default
    setting.is_default = True
    await db.commit()
    await db.refresh(setting)
    
    return setting


@router.delete("/ai-models/{setting_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ai_model_setting(
    setting_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Delete an AI model configuration"""
    result = await db.execute(
        select(AIModelSetting).where(AIModelSetting.id == setting_id)
    )
    setting = result.scalar_one_or_none()
    
    if not setting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="AI model setting not found"
        )
    
    await db.delete(setting)
    await db.commit()


# === Warehouse Endpoints ===

@router.post("/warehouses", response_model=WarehouseResponse, status_code=status.HTTP_201_CREATED)
async def create_warehouse(
    warehouse: WarehouseCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create a warehouse (SM05)"""
    db_warehouse = Warehouse(**warehouse.model_dump())
    db.add(db_warehouse)
    try:
        await db.commit()
        await db.refresh(db_warehouse)
    except Exception as e:
        await db.rollback()
        if "unique" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Warehouse with this shortname already exists"
            )
        raise
    
    return db_warehouse


@router.get("/warehouses", response_model=List[WarehouseResponse])
async def list_warehouses(
    db: AsyncSession = Depends(get_db)
):
    """List all warehouses"""
    result = await db.execute(select(Warehouse))
    warehouses = result.scalars().all()
    return warehouses


@router.get("/warehouses/{warehouse_id}", response_model=WarehouseResponse)
async def get_warehouse(
    warehouse_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get a specific warehouse"""
    result = await db.execute(
        select(Warehouse).where(Warehouse.id == warehouse_id)
    )
    warehouse = result.scalar_one_or_none()
    
    if not warehouse:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Warehouse not found"
        )
    
    return warehouse


@router.put("/warehouses/{warehouse_id}", response_model=WarehouseResponse)
async def update_warehouse(
    warehouse_id: int,
    warehouse_update: WarehouseCreate,
    db: AsyncSession = Depends(get_db)
):
    """Update a warehouse"""
    result = await db.execute(
        select(Warehouse).where(Warehouse.id == warehouse_id)
    )
    db_warehouse = result.scalar_one_or_none()
    
    if not db_warehouse:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Warehouse not found"
        )
    
    # Update fields
    for field, value in warehouse_update.model_dump().items():
        setattr(db_warehouse, field, value)
    
    await db.commit()
    await db.refresh(db_warehouse)
    
    return db_warehouse


@router.delete("/warehouses/{warehouse_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_warehouse(
    warehouse_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Delete a warehouse"""
    result = await db.execute(
        select(Warehouse).where(Warehouse.id == warehouse_id)
    )
    warehouse = result.scalar_one_or_none()
    
    if not warehouse:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Warehouse not found"
        )
    
    await db.delete(warehouse)
    await db.commit()
