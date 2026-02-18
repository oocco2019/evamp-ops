"""
eBay API client: OAuth 2.0 and Sell Fulfillment API (orders).
"""
import base64
import secrets
from decimal import Decimal
from urllib.parse import urlencode
from datetime import datetime, date, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
import httpx
from app.core.config import settings


# OAuth scopes: orders (Fulfillment), messaging (Message API), finances (net order earnings)
EBAY_SCOPE_FULFILLMENT = "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly"
EBAY_SCOPE_MESSAGE = "https://api.ebay.com/oauth/api_scope/commerce.message"
EBAY_SCOPE_FINANCES = "https://api.ebay.com/oauth/api_scope/sell.finances"
EBAY_SCOPES = f"{EBAY_SCOPE_FULFILLMENT} {EBAY_SCOPE_MESSAGE} {EBAY_SCOPE_FINANCES}"


def get_authorization_url(state: Optional[str] = None) -> str:
    """
    Build the eBay OAuth consent URL. User is redirected here to log in and grant access.
    Requests fulfillment (orders), commerce.message (messaging), and sell.finances (order earnings) scopes.
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


def _parse_amount(amount: Any) -> Tuple[Optional[Decimal], Optional[str]]:
    """Parse eBay Amount { value: str, currency?: str }. Returns (value, currency)."""
    if not amount or not isinstance(amount, dict):
        return None, None
    raw = amount.get("value")
    if raw is None:
        return None, amount.get("currency")
    try:
        return Decimal(str(raw).strip()), (amount.get("currency") or "").strip() or None
    except Exception:
        return None, amount.get("currency")


def _parse_total_due_seller(amount: Any) -> Tuple[Optional[Decimal], Optional[str]]:
    """
    Parse paymentSummary.totalDueSeller for Order earnings.
    eBay UI shows 'Order earnings' in GBP (seller payout currency). The API may return
    value/currency in order currency (e.g. EUR) and convertedFromValue/convertedFromCurrency
    in GBP. Prefer the GBP amount when present so we match the eBay order details figure.
    """
    if not amount or not isinstance(amount, dict):
        return None, None
    currency = (amount.get("currency") or "").strip().upper() or None
    converted_cc = (amount.get("convertedFromCurrency") or "").strip().upper() or None
    # Prefer GBP: either main currency is GBP, or converted (payout) is GBP
    if currency == "GBP":
        raw = amount.get("value")
        if raw is not None:
            try:
                return Decimal(str(raw).strip()), "GBP"
            except Exception:
                pass
    if converted_cc == "GBP":
        raw = amount.get("convertedFromValue")
        if raw is not None:
            try:
                return Decimal(str(raw).strip()), "GBP"
            except Exception:
                pass
    # Fallback: use main value/currency
    return _parse_amount(amount)


def _sum_tax_amounts(taxes: Any, collect_and_remit: Any) -> Optional[Decimal]:
    """Sum tax from lineItems.taxes and lineItems.ebayCollectAndRemitTaxes."""
    total = None
    for arr in (taxes or [], collect_and_remit or []):
        for t in arr if isinstance(arr, list) else []:
            if isinstance(t, dict) and "amount" in t:
                val, _ = _parse_amount(t["amount"])
                if val is not None:
                    total = (total or Decimal(0)) + val
    return total


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
    params["fieldGroups"] = "TAX_BREAKDOWN"

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


async def fetch_order_by_id(access_token: str, order_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch a single order by eBay order ID (getOrder).
    Returns full order including paymentSummary; use when getOrders omits it.
    """
    params: Dict[str, Any] = {"fieldGroups": "TAX_BREAKDOWN"}
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{settings.EBAY_API_URL}/sell/fulfillment/v1/order/{order_id}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            params=params,
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()


async def fetch_transactions_for_order(
    access_token: str, order_id: str, marketplace_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Fetch Finances API transactions for a single order (getTransactions filtered by orderId).
    Returns the API response (transactions list) or None on 204/404/403.
    Used to get net Order earnings (SALE transaction amount = totalDueSeller minus ad fees).
    EU/UK sellers may require Digital Signatures; 403 here is expected until implemented.
    """
    mkt = (marketplace_id or getattr(settings, "EBAY_MARKETPLACE_ID", None) or "EBAY_GB").strip()
    # Filter syntax: filter=orderId:{orderId}
    filter_val = f"orderId:{{{order_id}}}"
    params: Dict[str, Any] = {"filter": filter_val, "limit": 50}
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{settings.EBAY_API_URL}/sell/finances/v1/transaction",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "X-EBAY-C-MARKETPLACE-ID": mkt,
            },
            params=params,
        )
        if r.status_code in (204, 404):
            return None
        if r.status_code == 403:
            return None
        r.raise_for_status()
        return r.json()


def _parse_amount_from_transaction_field(
    amount_obj: Any, prefer_currency: Optional[str] = "GBP"
) -> Tuple[Optional[Decimal], Optional[str]]:
    """Parse Amount object; prefer value in prefer_currency (e.g. GBP) when convertedFromCurrency/convertedToCurrency match."""
    if not amount_obj or not isinstance(amount_obj, dict):
        return None, None
    currency = (amount_obj.get("currency") or "").strip().upper() or None
    converted_cc = (amount_obj.get("convertedFromCurrency") or "").strip().upper() or None
    if prefer_currency and currency == prefer_currency:
        raw = amount_obj.get("value")
        if raw is not None:
            try:
                return Decimal(str(raw).strip()), prefer_currency
            except Exception:
                pass
    if prefer_currency and converted_cc == prefer_currency:
        raw = amount_obj.get("convertedFromValue")
        if raw is not None:
            try:
                return Decimal(str(raw).strip()), prefer_currency
            except Exception:
                pass
    return _parse_amount(amount_obj)


def parse_net_order_earnings_from_transactions(
    transactions_response: Optional[Dict[str, Any]],
) -> Tuple[Optional[Decimal], Optional[str]]:
    """
    From a getTransactions response (filtered by orderId), find the SALE transaction
    and return net Order earnings = amount (gross) minus totalFeeAmount minus any
    NON_SALE_CHARGE (e.g. ad fees) for the same order. Matches eBay UI "Order earnings".
    Prefer GBP when converted values present.
    """
    if not transactions_response or not isinstance(transactions_response, dict):
        return None, None
    transactions = transactions_response.get("transactions") or []
    gross_val = None
    currency = None
    sale_fee_val = None
    for t in transactions:
        if (t or {}).get("transactionType") != "SALE":
            continue
        amount_obj = (t or {}).get("amount")
        if not amount_obj or not isinstance(amount_obj, dict):
            continue
        gross_val, currency = _parse_amount_from_transaction_field(amount_obj, "GBP")
        if gross_val is None:
            gross_val, currency = _parse_amount(amount_obj)
        if gross_val is None:
            continue
        fee_obj = (t or {}).get("totalFeeAmount")
        if fee_obj and isinstance(fee_obj, dict):
            sale_fee_val, _ = _parse_amount_from_transaction_field(fee_obj, "GBP")
            if sale_fee_val is None:
                sale_fee_val, _ = _parse_amount(fee_obj)
        break
    if gross_val is None:
        return None, None
    net = gross_val - (sale_fee_val or Decimal(0))
    extra_debits = Decimal(0)
    for t in transactions:
        if (t or {}).get("transactionType") == "NON_SALE_CHARGE":
            amt = (t or {}).get("amount")
            if amt and isinstance(amt, dict):
                v, _ = _parse_amount_from_transaction_field(amt, "GBP")
                if v is None:
                    v, _ = _parse_amount(amt)
                if v is not None:
                    extra_debits += v
    net = net - extra_debits
    return net, currency


def parse_ad_fees_from_transactions(
    transactions_response: Optional[Dict[str, Any]],
) -> Tuple[Optional[Decimal], Optional[str], List[Dict[str, Any]]]:
    """
    From a getTransactions response (filtered by orderId), sum NON_SALE_CHARGE amounts (ad fees etc.)
    and return (total_ad_fees, currency, breakdown). Prefer GBP.
    breakdown: list of {fee_type, transaction_memo, amount, currency} for display.
    """
    if not transactions_response or not isinstance(transactions_response, dict):
        return None, None, []
    transactions = transactions_response.get("transactions") or []
    total = Decimal(0)
    currency: Optional[str] = None
    breakdown: List[Dict[str, Any]] = []
    for t in transactions:
        if (t or {}).get("transactionType") != "NON_SALE_CHARGE":
            continue
        amt = (t or {}).get("amount")
        if not amt or not isinstance(amt, dict):
            continue
        v, cc = _parse_amount_from_transaction_field(amt, "GBP")
        if v is None:
            v, cc = _parse_amount(amt)
        if v is not None:
            total += v
            if cc:
                currency = cc
            fee_type = (t or {}).get("feeType") or ""
            memo = (t or {}).get("transactionMemo") or ""
            breakdown.append({
                "fee_type": fee_type,
                "transaction_memo": memo,
                "amount": str(v),
                "currency": cc or "",
            })
    if total == 0 and not breakdown:
        return None, None, []
    return total, currency, breakdown


def parse_orders_to_import(api_response: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Convert getOrders response to our Order + LineItem shape.
    Includes all Fulfillment API fields we store: pricing, tax, fees.
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

        pricing = o.get("pricingSummary") or {}
        order_currency = None
        price_subtotal, _ = _parse_amount(pricing.get("priceSubtotal"))
        if pricing.get("priceSubtotal", {}).get("currency"):
            order_currency = (pricing["priceSubtotal"].get("currency") or "").strip()
        price_total, _ = _parse_amount(pricing.get("total"))
        if not order_currency and pricing.get("total", {}).get("currency"):
            order_currency = (pricing["total"].get("currency") or "").strip()
        tax_total, _ = _parse_amount(pricing.get("tax"))
        delivery_cost, _ = _parse_amount(pricing.get("deliveryCost"))
        price_discount, _ = _parse_amount(pricing.get("priceDiscount"))
        fee_total, _ = _parse_amount(pricing.get("fee"))

        total_fee_basis, _ = _parse_amount(o.get("totalFeeBasisAmount"))
        total_marketplace_fee, _ = _parse_amount(o.get("totalMarketplaceFee"))
        payment_summary = o.get("paymentSummary") or {}
        total_due_seller, total_due_seller_currency = _parse_total_due_seller(
            payment_summary.get("totalDueSeller")
        )
        order_payment_status = (o.get("orderPaymentStatus") or "").strip() or None
        sales_record_reference = (o.get("salesRecordReference") or "").strip() or None
        ebay_collect_and_remit_tax = o.get("ebayCollectAndRemitTax") if isinstance(o.get("ebayCollectAndRemitTax"), bool) else None

        line_items = []
        for li in o.get("lineItems") or []:
            line_currency = (li.get("lineItemCost") or {}).get("currency") or (li.get("total") or {}).get("currency") or order_currency
            line_item_cost, _ = _parse_amount(li.get("lineItemCost"))
            discounted_line_item_cost, _ = _parse_amount(li.get("discountedLineItemCost"))
            line_total, _ = _parse_amount(li.get("total"))
            tax_amount = _sum_tax_amounts(li.get("taxes"), li.get("ebayCollectAndRemitTaxes"))
            line_items.append({
                "ebay_line_item_id": li.get("lineItemId") or "",
                "sku": (li.get("sku") or "").strip() or "UNKNOWN",
                "quantity": int(li.get("quantity", 1)),
                "currency": line_currency or None,
                "line_item_cost": line_item_cost,
                "discounted_line_item_cost": discounted_line_item_cost,
                "line_total": line_total,
                "tax_amount": tax_amount,
            })
        if not line_items:
            line_items = [{"ebay_line_item_id": order_id, "sku": "UNKNOWN", "quantity": 1, "currency": None, "line_item_cost": None, "discounted_line_item_cost": None, "line_total": None, "tax_amount": None}]

        result.append({
            "ebay_order_id": order_id,
            "date": creation_date,
            "country": country,
            "last_modified": last_modified,
            "cancel_status": cancel_status,
            "buyer_username": buyer_username,
            "order_currency": order_currency or None,
            "price_subtotal": price_subtotal,
            "price_total": price_total,
            "tax_total": tax_total,
            "delivery_cost": delivery_cost,
            "price_discount": price_discount,
            "fee_total": fee_total,
            "total_fee_basis_amount": total_fee_basis,
            "total_marketplace_fee": total_marketplace_fee,
            "total_due_seller": total_due_seller,
            "total_due_seller_currency": total_due_seller_currency or None,
            "order_payment_status": order_payment_status,
            "sales_record_reference": sales_record_reference,
            "ebay_collect_and_remit_tax": ebay_collect_and_remit_tax,
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


async def update_conversation_read(
    access_token: str,
    conversation_id: str,
    read: bool,
    conversation_type: str = "FROM_MEMBERS",
) -> None:
    """
    Update the read status of a conversation on eBay.
    POST commerce/message/v1/update_conversation with conversationId, conversationType, read.
    Returns 204 No Content.
    """
    payload: Dict[str, Any] = {
        "conversationId": conversation_id,
        "conversationType": conversation_type,
        "read": read,
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{settings.EBAY_API_URL}{MESSAGE_API_BASE}/update_conversation",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        r.raise_for_status()


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
