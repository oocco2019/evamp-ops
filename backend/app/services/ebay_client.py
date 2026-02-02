"""
eBay API client: OAuth 2.0 and Sell Fulfillment API (orders).
"""
import base64
import secrets
from urllib.parse import urlencode
from datetime import datetime, date, timedelta, timezone
from typing import Any, Dict, List, Optional
import httpx
from app.core.config import settings


# OAuth scopes: orders (Fulfillment) and messaging (Message API)
EBAY_SCOPE_FULFILLMENT = "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly"
EBAY_SCOPE_MESSAGE = "https://api.ebay.com/oauth/api_scope/commerce.message"
EBAY_SCOPES = f"{EBAY_SCOPE_FULFILLMENT} {EBAY_SCOPE_MESSAGE}"


def get_authorization_url(state: Optional[str] = None) -> str:
    """
    Build the eBay OAuth consent URL. User is redirected here to log in and grant access.
    Requests both fulfillment (orders) and commerce.message (messaging) scopes.
    """
    state = state or secrets.token_urlsafe(32)
    # Strip whitespace so .env typos don't break (eBay rejects redirect_uri with spaces)
    redirect_uri = (settings.EBAY_REDIRECT_URI or "").strip()
    params = {
        "client_id": (settings.EBAY_APP_ID or "").strip(),
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": EBAY_SCOPES,
        "state": state,
    }
    q = urlencode(params)
    return f"{settings.EBAY_AUTH_URL}/authorize?{q}"


def _basic_auth_header() -> str:
    """Base64-encoded client_id:client_secret for OAuth token requests."""
    creds = f"{settings.EBAY_APP_ID}:{settings.EBAY_CERT_ID}"
    return base64.b64encode(creds.encode()).decode()


async def exchange_code_for_token(code: str) -> Dict[str, Any]:
    """
    Exchange authorization code for access token and refresh token.
    Returns dict with access_token, refresh_token, expires_in.
    """
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{settings.EBAY_IDENTITY_URL}/token",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {_basic_auth_header()}",
            },
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": (settings.EBAY_REDIRECT_URI or "").strip(),
            },
        )
        r.raise_for_status()
        return r.json()


async def refresh_access_token(refresh_token: str) -> Dict[str, Any]:
    """
    Get a new access token using refresh token.
    Returns dict with access_token, expires_in.
    """
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{settings.EBAY_IDENTITY_URL}/token",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {_basic_auth_header()}",
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )
        r.raise_for_status()
        return r.json()


def _parse_iso_date(iso_str: Optional[str]) -> Optional[date]:
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.date()
    except Exception:
        return None


def _parse_iso_datetime(iso_str: Optional[str]) -> Optional[datetime]:
    if not iso_str:
        return None
    try:
        return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except Exception:
        return None


def _naive_utc(dt: datetime) -> datetime:
    """Return datetime as naive UTC for DB columns (TIMESTAMP WITHOUT TIME ZONE)."""
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _order_country(ebay_order: Dict[str, Any]) -> str:
    """Extract shipping country from order. Default to US if missing."""
    try:
        instructions = ebay_order.get("fulfillmentStartInstructions") or []
        for inst in instructions:
            ship = inst.get("shippingStep", {}).get("shipTo", {})
            addr = ship.get("contactAddress", {})
            cc = addr.get("countryCode")
            if cc:
                return cc
            dest = inst.get("finalDestinationAddress", {})
            cc = dest.get("countryCode")
            if cc:
                return cc
        buyer = ebay_order.get("buyer", {}).get("buyerRegistrationAddress", {})
        addr = buyer.get("contactAddress", {})
        return addr.get("countryCode") or "US"
    except Exception:
        return "US"


async def fetch_orders_page(
    access_token: str,
    creation_start: Optional[datetime] = None,
    creation_end: Optional[datetime] = None,
    last_modified_since: Optional[datetime] = None,
    limit: int = 200,
    offset: int = 0,
) -> Dict[str, Any]:
    """
    Fetch one page of orders from Sell Fulfillment API.
    Filter by creationdate or lastmodifieddate. Returns API response with orders, next, total.
    """
    filters = []
    if creation_start and creation_end:
        start_s = creation_start.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        end_s = creation_end.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        filters.append(f"creationdate:[{start_s}..{end_s}]")
    elif creation_start:
        start_s = creation_start.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        filters.append(f"creationdate:[{start_s}..]")
    elif last_modified_since:
        since_s = last_modified_since.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        filters.append(f"lastmodifieddate:[{since_s}..]")

    filter_str = ",".join(filters) if filters else None

    params: Dict[str, Any] = {"limit": limit, "offset": offset}
    if filter_str:
        params["filter"] = filter_str

    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{settings.EBAY_API_URL}/sell/fulfillment/v1/order",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            params=params,
        )
        r.raise_for_status()
        return r.json()


def parse_orders_to_import(api_response: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Convert getOrders response to our Order + LineItem shape.
    Returns list of dicts: { ebay_order_id, date, country, last_modified, line_items: [ { ebay_line_item_id, sku, quantity } ] }
    """
    orders = api_response.get("orders") or []
    result = []
    for o in orders:
        order_id = o.get("orderId")
        if not order_id:
            continue
        creation_date = _parse_iso_date(o.get("creationDate"))
        last_modified = _parse_iso_datetime(o.get("lastModifiedDate"))
        if not creation_date:
            creation_date = date.today()
        if not last_modified:
            last_modified = _naive_utc(datetime.now(timezone.utc))
        else:
            last_modified = _naive_utc(last_modified)

        country = _order_country(o)
        buyer_username = (o.get("buyer") or {}).get("username")
        cancel_status = (o.get("cancelStatus") or {}).get("cancelState")
        if cancel_status not in ("CANCELED", "IN_PROGRESS", "NONE_REQUESTED"):
            cancel_status = "NONE_REQUESTED"
        line_items = []
        for li in o.get("lineItems") or []:
            line_items.append({
                "ebay_line_item_id": li.get("lineItemId") or "",
                "sku": (li.get("sku") or "").strip() or "UNKNOWN",
                "quantity": int(li.get("quantity", 1)),
            })
        if not line_items:
            line_items = [{"ebay_line_item_id": order_id, "sku": "UNKNOWN", "quantity": 1}]

        result.append({
            "ebay_order_id": order_id,
            "date": creation_date,
            "country": country,
            "last_modified": last_modified,
            "cancel_status": cancel_status,
            "buyer_username": buyer_username,
            "line_items": line_items,
        })
    return result


async def fetch_all_orders(
    access_token: str,
    creation_start: datetime,
    creation_end: datetime,
    page_size: int = 200,
) -> List[Dict[str, Any]]:
    """
    Fetch all orders in a date range, paginating through results.
    """
    all_orders = []
    offset = 0
    while True:
        data = await fetch_orders_page(
            access_token,
            creation_start=creation_start,
            creation_end=creation_end,
            limit=page_size,
            offset=offset,
        )
        parsed = parse_orders_to_import(data)
        all_orders.extend(parsed)
        if not data.get("next"):
            break
        offset += page_size
        if offset >= (data.get("total") or 0):
            break
    return all_orders


async def fetch_orders_modified_since(
    access_token: str,
    since: datetime,
    page_size: int = 200,
) -> List[Dict[str, Any]]:
    """Fetch all orders modified since given datetime (for incremental sync)."""
    all_orders = []
    offset = 0
    while True:
        data = await fetch_orders_page(
            access_token,
            last_modified_since=since,
            limit=page_size,
            offset=offset,
        )
        parsed = parse_orders_to_import(data)
        all_orders.extend(parsed)
        if not data.get("next"):
            break
        offset += page_size
        if offset >= (data.get("total") or 0):
            break
    return all_orders


# --- Message API (commerce/message/v1) ---

MESSAGE_API_BASE = "/commerce/message/v1"


async def fetch_message_conversations_page(
    access_token: str,
    conversation_type: str = "FROM_MEMBERS",
    conversation_status: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """
    Fetch one page of conversations from eBay Message API.
    conversation_type is required: FROM_MEMBERS (member-to-member) or FROM_EBAY.
    start_time/end_time (ISO 8601) filter by conversation activity for FROM_MEMBERS.
    """
    params: Dict[str, Any] = {
        "conversation_type": conversation_type,
        "limit": min(limit, 50),
        "offset": offset,
    }
    if conversation_status:
        params["conversation_status"] = conversation_status
    if start_time:
        params["start_time"] = start_time
    if end_time:
        params["end_time"] = end_time
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{settings.EBAY_API_URL}{MESSAGE_API_BASE}/conversation",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            params=params,
        )
        r.raise_for_status()
        return r.json()


async def fetch_conversation_messages_page(
    access_token: str,
    conversation_id: str,
    conversation_type: str = "FROM_MEMBERS",
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """Fetch one page of messages for a conversation."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{settings.EBAY_API_URL}{MESSAGE_API_BASE}/conversation/{conversation_id}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            params={
                "conversation_type": conversation_type,
                "limit": min(limit, 50),
                "offset": offset,
            },
        )
        r.raise_for_status()
        return r.json()


async def fetch_all_conversation_messages(
    access_token: str,
    conversation_id: str,
    conversation_type: str = "FROM_MEMBERS",
    page_size: int = 50,
) -> List[Dict[str, Any]]:
    """Fetch all messages in a conversation, paginating as needed."""
    all_messages: List[Dict[str, Any]] = []
    offset = 0
    while True:
        data = await fetch_conversation_messages_page(
            access_token,
            conversation_id,
            conversation_type=conversation_type,
            limit=page_size,
            offset=offset,
        )
        messages = data.get("messages") or []
        all_messages.extend(messages)
        if not data.get("next") or offset + len(messages) >= (data.get("total") or 0):
            break
        offset += page_size
    return all_messages


async def send_message(
    access_token: str,
    conversation_id: str,
    message_text: str,
    reference_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Send a message in an existing conversation via eBay REST Message API.
    Returns the created message details including messageId.
    Max message_text length: 2000 characters.
    """
    payload: Dict[str, Any] = {
        "conversationId": conversation_id,
        "messageText": message_text[:2000],  # eBay enforces 2000 char limit
    }
    if reference_id:
        payload["reference"] = {
            "referenceId": reference_id,
            "referenceType": "LISTING",
        }
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{settings.EBAY_API_URL}{MESSAGE_API_BASE}/send_message",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        r.raise_for_status()
        return r.json()
