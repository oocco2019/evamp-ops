"""
Settings API endpoints (GN01)
- API credential management
- AI model selection
- Warehouse management
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, Field

from app.core.database import get_db
from app.core.security import encryption_service
from app.models.settings import APICredential, AIModelSetting, Warehouse, EmailTemplate, AppBranding, AppNotepad

router = APIRouter()

BRANDING_ID = 1
LOGO_MAX_BYTES = 1_048_576  # 1 MiB
FAVICON_MAX_BYTES = 262_144  # 256 KiB
ALLOWED_LOGO_MIMES = frozenset({"image/png", "image/jpeg", "image/svg+xml", "image/webp"})
ALLOWED_FAVICON_MIMES = frozenset(
    {"image/png", "image/jpeg", "image/svg+xml", "image/x-icon", "image/vnd.microsoft.icon"}
)


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


# === Email Template Endpoints (CS11) ===

class EmailTemplateCreate(BaseModel):
    """Schema for email template creation"""
    name: str = Field(..., max_length=100)
    recipient_email: str = Field(..., max_length=255)
    subject: str = Field(..., max_length=500)
    body: str


class EmailTemplateResponse(BaseModel):
    """Schema for email template response"""
    id: int
    name: str
    recipient_email: str
    subject: str
    body: str
    
    model_config = {"from_attributes": True}


@router.post("/email-templates", response_model=EmailTemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_email_template(
    template: EmailTemplateCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create an email template (CS11)"""
    db_template = EmailTemplate(
        name=template.name,
        recipient_email=template.recipient_email,
        subject=template.subject,
        body=template.body,
    )
    db.add(db_template)
    try:
        await db.commit()
        await db.refresh(db_template)
    except Exception:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Template with this name already exists"
        )
    return db_template


@router.get("/email-templates", response_model=List[EmailTemplateResponse])
async def list_email_templates(db: AsyncSession = Depends(get_db)):
    """List all email templates"""
    result = await db.execute(select(EmailTemplate))
    return list(result.scalars().all())


@router.get("/email-templates/{template_id}", response_model=EmailTemplateResponse)
async def get_email_template(template_id: int, db: AsyncSession = Depends(get_db)):
    """Get a specific email template"""
    result = await db.execute(select(EmailTemplate).where(EmailTemplate.id == template_id))
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    return template


@router.put("/email-templates/{template_id}", response_model=EmailTemplateResponse)
async def update_email_template(
    template_id: int,
    template_update: EmailTemplateCreate,
    db: AsyncSession = Depends(get_db)
):
    """Update an email template"""
    result = await db.execute(select(EmailTemplate).where(EmailTemplate.id == template_id))
    db_template = result.scalar_one_or_none()
    if not db_template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    
    db_template.name = template_update.name
    db_template.recipient_email = template_update.recipient_email
    db_template.subject = template_update.subject
    db_template.body = template_update.body
    
    await db.commit()
    await db.refresh(db_template)
    return db_template


@router.delete("/email-templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_email_template(template_id: int, db: AsyncSession = Depends(get_db)):
    """Delete an email template"""
    result = await db.execute(select(EmailTemplate).where(EmailTemplate.id == template_id))
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    await db.delete(template)
    await db.commit()


# === App branding ===


class BrandingUpdate(BaseModel):
    app_name: str = Field(..., min_length=1, max_length=120)


class BrandingResponse(BaseModel):
    app_name: str
    has_logo: bool
    has_favicon: bool
    logo_url: Optional[str] = None
    favicon_url: Optional[str] = None
    favicon_mime: Optional[str] = None
    updated_at: Optional[str] = None


async def favicon_http_response(db: AsyncSession) -> Response:
    """Serve uploaded favicon bytes (used by /favicon.ico and API)."""
    row = await _get_or_create_branding(db)
    if not row.favicon_data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No favicon configured.")
    return Response(
        content=row.favicon_data,
        media_type=row.favicon_mime or "application/octet-stream",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


async def _get_or_create_branding(db: AsyncSession) -> AppBranding:
    result = await db.execute(select(AppBranding).where(AppBranding.id == BRANDING_ID))
    row = result.scalar_one_or_none()
    if row is None:
        row = AppBranding(id=BRANDING_ID, app_name="EvampOps")
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


def _branding_to_response(row: AppBranding) -> BrandingResponse:
    version = row.updated_at.isoformat() if row.updated_at else None
    vq = f"?v={version}" if version else ""
    return BrandingResponse(
        app_name=row.app_name,
        has_logo=bool(row.logo_data),
        has_favicon=bool(row.favicon_data),
        logo_url=f"/api/settings/branding/logo{vq}" if row.logo_data else None,
        favicon_url=f"/favicon.ico{vq}" if row.favicon_data else None,
        favicon_mime=row.favicon_mime if row.favicon_data else None,
        updated_at=version,
    )


@router.get("/branding", response_model=BrandingResponse)
async def get_branding(db: AsyncSession = Depends(get_db)):
    """App display name and logo/favicon URLs for nav and browser tab."""
    row = await _get_or_create_branding(db)
    return _branding_to_response(row)


@router.put("/branding", response_model=BrandingResponse)
async def update_branding(body: BrandingUpdate, db: AsyncSession = Depends(get_db)):
    row = await _get_or_create_branding(db)
    row.app_name = body.app_name.strip()
    await db.commit()
    await db.refresh(row)
    return _branding_to_response(row)


# === App notepad ===

NOTEPAD_ID = 1


class NotepadUpdate(BaseModel):
    body: str = Field(..., max_length=500_000)


class NotepadResponse(BaseModel):
    body: str
    updated_at: Optional[str] = None


async def _get_or_create_notepad(db: AsyncSession) -> AppNotepad:
    result = await db.execute(select(AppNotepad).where(AppNotepad.id == NOTEPAD_ID))
    row = result.scalar_one_or_none()
    if row is None:
        row = AppNotepad(id=NOTEPAD_ID, body="")
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


def _notepad_to_response(row: AppNotepad) -> NotepadResponse:
    return NotepadResponse(
        body=row.body or "",
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


@router.get("/notepad", response_model=NotepadResponse)
async def get_notepad(db: AsyncSession = Depends(get_db)):
    """Home-page free-form notepad body."""
    row = await _get_or_create_notepad(db)
    return _notepad_to_response(row)


@router.put("/notepad", response_model=NotepadResponse)
async def update_notepad(body: NotepadUpdate, db: AsyncSession = Depends(get_db)):
    row = await _get_or_create_notepad(db)
    row.body = body.body
    await db.commit()
    await db.refresh(row)
    return _notepad_to_response(row)


async def _read_upload(file: UploadFile, max_bytes: int, allowed: frozenset[str]) -> tuple[bytes, str]:
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type: {content_type or 'unknown'}",
        )
    data = await file.read()
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file.")
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large (max {max_bytes // 1024} KiB).",
        )
    return data, content_type


@router.post("/branding/logo", response_model=BrandingResponse)
async def upload_logo(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    data, mime = await _read_upload(file, LOGO_MAX_BYTES, ALLOWED_LOGO_MIMES)
    row = await _get_or_create_branding(db)
    row.logo_data = data
    row.logo_mime = mime
    await db.commit()
    await db.refresh(row)
    return _branding_to_response(row)


@router.post("/branding/favicon", response_model=BrandingResponse)
async def upload_favicon(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    data, mime = await _read_upload(file, FAVICON_MAX_BYTES, ALLOWED_FAVICON_MIMES)
    row = await _get_or_create_branding(db)
    row.favicon_data = data
    row.favicon_mime = mime
    await db.commit()
    await db.refresh(row)
    return _branding_to_response(row)


@router.delete("/branding/logo", response_model=BrandingResponse)
async def delete_logo(db: AsyncSession = Depends(get_db)):
    row = await _get_or_create_branding(db)
    row.logo_data = None
    row.logo_mime = None
    await db.commit()
    await db.refresh(row)
    return _branding_to_response(row)


@router.delete("/branding/favicon", response_model=BrandingResponse)
async def delete_favicon(db: AsyncSession = Depends(get_db)):
    row = await _get_or_create_branding(db)
    row.favicon_data = None
    row.favicon_mime = None
    await db.commit()
    await db.refresh(row)
    return _branding_to_response(row)


@router.get("/branding/logo")
async def get_logo(db: AsyncSession = Depends(get_db)):
    row = await _get_or_create_branding(db)
    if not row.logo_data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No logo configured.")
    return Response(content=row.logo_data, media_type=row.logo_mime or "application/octet-stream")


@router.get("/branding/favicon")
async def get_favicon(db: AsyncSession = Depends(get_db)):
    return await favicon_http_response(db)
