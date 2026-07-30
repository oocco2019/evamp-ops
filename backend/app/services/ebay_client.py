"""
eBay API client: OAuth 2.0 and Sell Fulfillment API (orders).
"""
import base64
import secrets
import re
from decimal import Decimal
from urllib.parse import urlencode
from datetime import datetime, date, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, Union
import httpx
from app.core.config import settings


# OAuth scopes: orders (Fulfillment), messaging (Message API), finances (order earnings), inventory (image upload for messages)
EBAY_SCOPE_FULFILLMENT = "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly"
EBAY_SCOPE_MESSAGE = "https://api.ebay.com/oauth/api_scope/commerce.message"
EBAY_SCOPE_FINANCES = "https://api.ebay.com/oauth/api_scope/sell.finances"
EBAY_SCOPE_INVENTORY = "https://api.ebay.com/oauth/api_scope/sell.inventory"
EBAY_SCOPES = f"{EBAY_SCOPE_FULFILLMENT} {EBAY_SCOPE_MESSAGE} {EBAY_SCOPE_FINANCES} {EBAY_SCOPE_INVENTORY}"


def get_authorization_url(state: Optional[str] = None) -> str:
    """
    Build the eBay OAuth consent URL. User is redirected here to log in and grant access.
    Requests fulfillment (orders), commerce.message (messaging), sell.finances (order earnings), sell.inventory (image upload for message attachments).
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
            # Full raw eBay order object (incl. lineItems) for long-term recovery; see docs/DATA_RETENTION.md.
            "raw_payload": o,
        })
    return result


def _extract_buyer_vehicle_string(buyer_checkout_notes: Optional[str]) -> Optional[str]:
    """
    eBay buyerCheckoutNotes format examples:
    - EN: "Buyer's Vehicle: Tesla Model 3 2021 Electric Motor Saloon ..."
    - DE: "Fahrzeug des Käufers: Jeep Wrangler IV 2023 JL 2.0 4xe Plug-in-Hybrid ..."
    """

    if not buyer_checkout_notes:
        return None

    m = re.search(r"Buyer's Vehicle:\s*([^\n\r]+)", buyer_checkout_notes, flags=re.IGNORECASE)
    if m:
        return (m.group(1) or "").strip()

    m = re.search(r"Fahrzeug des Käufers:\s*([^\n\r]+)", buyer_checkout_notes, flags=re.IGNORECASE)
    if m:
        return (m.group(1) or "").strip()

    return None


def _parse_year_from_text(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    # Keep it conservative to reduce accidental matches.
    m = re.search(r"\b(19\d{2}|20\d{2}|2030)\b", s)
    if not m:
        return None
    try:
        return int(m.group(1))
    except (TypeError, ValueError):
        return None


def _vehicle_type_from_text(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    hay = s.lower()
    if any(k in hay for k in ("plug-in hybrid", "plug in hybrid", "phev", "plug-in")):
        return "PHEV"
    if "electric" in hay and "hybrid" in hay:
        return "PHEV"
    if "ev" in hay or "electric" in hay:
        return "EV"
    if "hybrid" in hay:
        return "Hybrid"
    return None


def _clean_vehicle_fragment(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    # Drop some common separators used in eBay strings.
    out = str(s)
    out = out.replace("--", " ")
    out = re.sub(r"\s+", " ", out).strip()
    # Avoid over-stripping hyphenated makes like "Mercedes-Benz".
    return out or None


# Standalone generation markers only (space-separated), not hyphenated like V-Class / E-Class.
_ROMAN_GENERATION_TOKEN_RE = re.compile(
    r"(?i)^(VIII|VII|III|II|IV|IX|VI|V|X|I)$"
)

# Tokens that should keep a specific casing after title-case.
_MODEL_TOKEN_CASING = {
    "ev": "EV",
    "phev": "PHEV",
    "e-tron": "e-tron",
    "e-tech": "E-Tech",
    "id.": None,  # handled below for ID.3 / ID.4 style
    "sw": "SW",
    "suv": "SUV",
    "awd": "AWD",
    "mk": "MK",
}


def _title_token(tok: str) -> str:
    low = tok.lower()
    if low in _MODEL_TOKEN_CASING and _MODEL_TOKEN_CASING[low]:
        return _MODEL_TOKEN_CASING[low]
    if low.startswith("id.") and len(low) > 3:
        return "ID." + tok[3:]
    # EV / EQ family and short letter+digit codes: XC60, V60, C40, EQB, EV6, EQA
    if re.fullmatch(r"(?i)eq[a-z0-9.-]*", tok) or re.fullmatch(r"(?i)ev\d*", tok):
        return tok.upper()
    m = re.fullmatch(r"([A-Za-z]{1,5})(\d+[A-Za-z0-9]*)", tok)
    if m:
        return m.group(1).upper() + m.group(2)
    if re.fullmatch(r"[A-Za-z]{2,5}\d*", tok) and any(c.isdigit() for c in tok):
        return tok.upper()
    if low in ("zs", "nx", "rz", "hs", "cla", "slk", "mg", "mx"):
        return tok.upper()
    if low.startswith("mg") and len(tok) <= 5:
        # MG 4 / MG5 style handled as separate tokens; MGS5 etc.
        return tok.upper() if tok.isalpha() else tok[:2].upper() + tok[2:]
    # Hyphenated names (E-Class, V-Class, MX-30). Known e-tron/e-tech already
    # returned from _MODEL_TOKEN_CASING above — do not special-case all e-* here
    # or E-Class becomes E-class.
    if "-" in tok:
        return "-".join(_title_token(p) if p else p for p in tok.split("-"))
    return tok[:1].upper() + tok[1:].lower() if tok else tok


def normalize_vehicle_make(make: Optional[str]) -> Optional[str]:
    cleaned = _clean_vehicle_fragment(make)
    if not cleaned:
        return None
    low = cleaned.lower()
    if low in ("mercedes benz", "mercedes-benz", "mercedes"):
        return "Mercedes-Benz"
    if low in ("land rover",):
        return "Land Rover"
    if low in ("alfa romeo",):
        return "Alfa Romeo"
    if low == "vw":
        return "VW"
    if low == "bmw":
        return "BMW"
    if low == "kia":
        return "Kia"
    if low == "mg":
        return "MG"
    if low == "byd":
        return "BYD"
    if low == "gmc":
        return "GMC"
    if low == "ds":
        return "DS"
    if low in ("mini",):
        return "MINI"
    return " ".join(_title_token(t) for t in cleaned.split())


def normalize_vehicle_model(model: Optional[str]) -> Optional[str]:
    """
    Canonical model for stats: strip Roman generation suffixes and normalize casing.

    Outlander III → Outlander, Kuga III → Kuga, Golf VIII → Golf, V60 II → V60.
    Keeps hyphenated names (V-Class, E-Class). Arabic numbers (Model 3, 208, ID.3) kept.
    Trailing body tokens like SUV are dropped (Enyaq SUV → Enyaq).
    """
    cleaned = _clean_vehicle_fragment(model)
    if not cleaned:
        return None
    tokens = [t for t in cleaned.split() if not _ROMAN_GENERATION_TOKEN_RE.match(t)]
    while tokens and tokens[-1].lower() in ("suv",):
        tokens.pop()
    if not tokens:
        return None
    return " ".join(_title_token(t) for t in tokens)


# Product-title tokens that end the make/model prefix on EV/PHEV cable listings.
_LISTING_TITLE_STOP_TOKENS = frozenset(
    {
        "ev",
        "phev",
        "hev",
        "charging",
        "charger",
        "ladekabel",
        "ladegerät",
        "ladegerat",
        "ladegeraet",
        "cable",
        "lead",
        "typ",
        "type",
        "level",
        "home",
        "portable",
        "mains",
        "schuko",
        "nema",
        "elektroauto",
        "hybrid",
        "plug-in",
        "plugin",
    }
)

_LISTING_TITLE_MULTI_WORD_MAKES = (
    ("land rover", 2),
    ("alfa romeo", 2),
    ("mercedes benz", 2),
    ("mercedes-benz", 1),
)

_LISTING_TITLE_YEAR_RANGE_RE = re.compile(r"^\d{4}(-\d{4}|-on)$", re.IGNORECASE)
_LISTING_TITLE_MODEL_CODE_RE = re.compile(r"^[A-Za-z]{1,4}\d+[A-Za-z0-9]*$", re.IGNORECASE)


def _simplify_listing_title_model_tokens(tokens: List[str]) -> List[str]:
    """Prefer a single model when the title lists several fitments (2008 3008, EX60 XC60)."""
    if len(tokens) >= 2 and all(t.isdigit() for t in tokens):
        return tokens[:1]
    if len(tokens) >= 2 and all(_LISTING_TITLE_MODEL_CODE_RE.match(t) for t in tokens):
        return tokens[:1]
    return tokens


def _parse_vehicle_from_listing_title(title: Optional[str]) -> Dict[str, Optional[str]]:
    """
    Infer make/model from a vehicle-branded listing title when checkout has no buyer vehicle.

    Examples:
      HYUNDAI INSTER EV Ladekabel ... → Hyundai / Inster
      SKODA ENYAQ IV EV Charging ... → Skoda / Enyaq
      LAND ROVER RANGE ROVER EVOQUE PHEV ... → Land Rover / Range Rover Evoque
    """
    cleaned = _clean_vehicle_fragment(title)
    if not cleaned:
        return {"vehicle_make": None, "vehicle_model": None, "vehicle_raw": None}

    # Only treat charger / cable style titles as vehicle indicators.
    hay = cleaned.lower()
    if not any(
        k in hay
        for k in (
            " ev ",
            "phev",
            "ladekabel",
            "charging",
            "charger",
            "ladegerät",
            "ladegerat",
            "ladegeraet",
        )
    ):
        # Leading "MAKE MODEL EV ..." has no trailing space after EV when EV is last before more words;
        # also allow title start patterns via token scan below, but require an EV/PHEV/cable keyword.
        if not re.search(r"(?i)\b(ev|phev|ladekabel|charging|charger|ladegerät|ladegerat|ladegeraet)\b", cleaned):
            return {"vehicle_make": None, "vehicle_model": None, "vehicle_raw": None}

    tokens = cleaned.replace(",", " ").split()
    if len(tokens) < 2:
        return {"vehicle_make": None, "vehicle_model": None, "vehicle_raw": None}

    low_tokens = [t.lower() for t in tokens]
    make_token_count = 1
    joined2 = " ".join(low_tokens[:2]) if len(low_tokens) >= 2 else ""
    for make_key, n in _LISTING_TITLE_MULTI_WORD_MAKES:
        if make_key == joined2 or (n == 1 and low_tokens[0] == make_key):
            make_token_count = n
            break
        if n == 1 and low_tokens[0].replace(" ", "") == make_key.replace(" ", ""):
            make_token_count = 1
            break

    make_raw = " ".join(tokens[:make_token_count])
    if make_raw.lower() in _LISTING_TITLE_STOP_TOKENS or make_raw.upper() == "EV":
        return {"vehicle_make": None, "vehicle_model": None, "vehicle_raw": None}

    model_tokens: List[str] = []
    for tok in tokens[make_token_count:]:
        low = tok.lower()
        if low in _LISTING_TITLE_STOP_TOKENS or _LISTING_TITLE_YEAR_RANGE_RE.match(tok):
            break
        model_tokens.append(tok)

    model_tokens = _simplify_listing_title_model_tokens(model_tokens)
    if not model_tokens:
        return {"vehicle_make": None, "vehicle_model": None, "vehicle_raw": None}

    make = normalize_vehicle_make(make_raw)
    model = normalize_vehicle_model(" ".join(model_tokens))
    if make and model and model.lower() == make.lower():
        model = None
    if not (make and model):
        return {"vehicle_make": None, "vehicle_model": None, "vehicle_raw": None}

    return {
        "vehicle_make": make,
        "vehicle_model": model,
        "vehicle_raw": f"{make_raw} {' '.join(model_tokens)}".strip(),
    }


def extract_customer_vehicle_details_from_ebay_order(raw_order: Dict[str, Any]) -> Dict[str, Optional[object]]:
    """
    Best-effort extraction of vehicle make/model/year/type from a raw eBay Fulfillment order.

    Primary source: raw_order.lineItems[].compatibilityProperties (structured).
    Fallback source: raw_order.buyerCheckoutNotes (free text).
    Last resort: line item listing title (vehicle-branded charger listings).

    Output keys:
      - vehicle_make, vehicle_model, vehicle_year, vehicle_type
      - vehicle_raw: the raw extracted vehicle string when available
      - vehicle_source: "compatibilityProperties", "buyerCheckoutNotes", or "listingTitle"
    """

    raw_order = raw_order or {}

    buyer_notes = raw_order.get("buyerCheckoutNotes")
    buyer_vehicle = _extract_buyer_vehicle_string(buyer_notes)

    compat_props: Optional[List[Dict[str, Any]]] = None
    for li in raw_order.get("lineItems") or []:
        cps = li.get("compatibilityProperties") or []
        if cps:
            compat_props = cps
            break

    compat_map: Dict[str, Optional[str]] = {}
    if compat_props:
        for p in compat_props:
            name = (p.get("propertyName") or "").strip().lower()
            if not name:
                continue
            compat_map[name] = p.get("propertyValue")

    compat_make = _clean_vehicle_fragment(compat_map.get("make"))
    compat_model = _clean_vehicle_fragment(compat_map.get("model"))
    compat_year = _parse_year_from_text(str(compat_map.get("year") or ""))
    compat_type = _vehicle_type_from_text(compat_map.get("type"))

    note_year = _parse_year_from_text(buyer_vehicle)

    # Parse make/model from buyer vehicle string by taking:
    # - make = first word token
    # - model = remaining tokens before the year token
    note_make: Optional[str] = None
    note_model: Optional[str] = None
    if buyer_vehicle and (note_year is not None):
        note_clean = _clean_vehicle_fragment(buyer_vehicle) or ""
        pre_year = note_clean.split(str(note_year))[0].strip()
        pre_year = pre_year.replace(",", " ").strip()
        tokens = pre_year.split()
        if len(tokens) >= 2:
            note_make = tokens[0]
            note_model = " ".join(tokens[1:])

    # Merge: keep structured fields when present, fill gaps from note.
    vehicle_make = normalize_vehicle_make(compat_make or note_make)
    vehicle_model = normalize_vehicle_model(compat_model or note_model)
    # Drop redundant make prefix in model ("MG HS" → "HS" when make is MG).
    # Keep numeric lines like "MG 4" / "MG 5" as the full model string.
    if vehicle_make and vehicle_model:
        make_low = vehicle_make.lower()
        model_low = vehicle_model.lower()
        if model_low == make_low:
            vehicle_model = None
        elif model_low.startswith(make_low + " "):
            remainder = vehicle_model[len(vehicle_make) :].strip()
            if remainder and not remainder[0].isdigit():
                vehicle_model = normalize_vehicle_model(remainder)
    vehicle_year = compat_year or note_year

    note_type = _vehicle_type_from_text(buyer_vehicle)
    # Prefer the note when it implies a stronger classification (PHEV vs generic Hybrid).
    vehicle_type = note_type or compat_type

    vehicle_raw = _clean_vehicle_fragment(buyer_vehicle) or (
        " ".join([x for x in [vehicle_make, vehicle_model, str(vehicle_year) if vehicle_year else None] if x]).strip() or None
    )

    if compat_make or compat_model or compat_year:
        vehicle_source: Optional[str] = "compatibilityProperties"
    elif note_make or note_model or note_year:
        vehicle_source = "buyerCheckoutNotes"
    else:
        vehicle_source = None

    # No buyer/compat vehicle → infer from vehicle-branded listing title.
    if not vehicle_make and not vehicle_model:
        title = None
        for li in raw_order.get("lineItems") or []:
            t = (li.get("title") or "").strip()
            if t:
                title = t
                break
        from_title = _parse_vehicle_from_listing_title(title)
        if from_title.get("vehicle_make") and from_title.get("vehicle_model"):
            vehicle_make = from_title["vehicle_make"]
            vehicle_model = from_title["vehicle_model"]
            vehicle_raw = from_title.get("vehicle_raw") or title
            if not vehicle_type:
                vehicle_type = _vehicle_type_from_text(title)
            vehicle_source = "listingTitle"

    if not (vehicle_make or vehicle_model or vehicle_year):
        vehicle_source = None

    return {
        "vehicle_make": vehicle_make,
        "vehicle_model": vehicle_model,
        "vehicle_year": vehicle_year,
        "vehicle_type": vehicle_type,
        "vehicle_raw": vehicle_raw,
        "vehicle_source": vehicle_source,
    }


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
    conversation_type is required. Valid values per eBay docs: FROM_MEMBERS, FROM_EBAY (only).
    start_time/end_time (ISO 8601) are supported only when conversation_type is FROM_MEMBERS.
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


async def fetch_all_conversations(
    access_token: str,
    conversation_type: str,
    start_time: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Fetch all conversations for a type (paginating), optionally filtered by start_time."""
    all_conversations: List[Dict[str, Any]] = []
    offset = 0
    while True:
        data = await fetch_message_conversations_page(
            access_token,
            conversation_type=conversation_type,
            start_time=start_time,
            limit=limit,
            offset=offset,
        )
        conversations = data.get("conversations") or []
        all_conversations.extend(conversations)
        total = data.get("total") or 0
        if not conversations or offset + len(conversations) >= total or not data.get("next"):
            break
        offset += limit
    return all_conversations


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
    message_media: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Send a message in an existing conversation via eBay REST Message API.
    message_media: optional list of {mediaName, mediaType, mediaUrl}. Types: IMAGE, DOC, PDF, TXT. Max 5. URLs must be HTTPS.
    messageText must be non-empty after eBay-side trimming; callers sending attachments only should pass
    a non-strippable placeholder (see messages.py), not a plain space.
    Returns the created message details including messageId and messageMedia.
    """
    payload: Dict[str, Any] = {
        "conversationId": conversation_id,
        "messageText": message_text[:2000],
    }
    if reference_id:
        payload["reference"] = {
            "referenceId": reference_id,
            "referenceType": "LISTING",
        }
    if message_media:
        payload["messageMedia"] = [
            {"mediaName": m.get("mediaName", ""), "mediaType": (m.get("mediaType") or "IMAGE").upper(), "mediaUrl": m.get("mediaUrl") or ""}
            for m in message_media[:5]
        ]
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


# Commerce Media API (images). Requires sell.inventory scope. Base URL: apim.ebay.com
MEDIA_API_IMAGE_BASE = "/commerce/media/v1_beta/image"

# Allowed image extensions for message attachments (eBay: JPG, GIF, PNG, BMP, TIFF, AVIF, HEIC, WEBP)
ALLOWED_IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".gif", ".png", ".bmp", ".tiff", ".tif", ".avif", ".heic", ".webp"})


async def upload_image_for_message(
    access_token: str,
    file_bytes: bytes,
    filename: str,
) -> Dict[str, Any]:
    """
    Upload an image to eBay Picture Services via Commerce Media API. Returns { mediaUrl, mediaName, mediaType }.
    Requires OAuth scope sell.inventory. If 403, the app may not have that scope.
    """
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{settings.EBAY_MEDIA_API_URL}{MEDIA_API_IMAGE_BASE}/create_image_from_file",
            headers={"Authorization": f"Bearer {access_token}"},
            files={"image": (filename or "image.jpg", file_bytes)},
        )
        r.raise_for_status()
        location = r.headers.get("location") or ""
        image_id = location.rstrip("/").split("/")[-1] if location else None
        if not image_id:
            raise ValueError("eBay Media API did not return image ID in Location header")
        get_r = await client.get(
            f"{settings.EBAY_MEDIA_API_URL}{MEDIA_API_IMAGE_BASE}/{image_id}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        get_r.raise_for_status()
        data = get_r.json()
        image_url = data.get("imageUrl") or ""
        if not image_url:
            raise ValueError("eBay getImage did not return imageUrl")
        return {
            "mediaUrl": image_url,
            "mediaName": filename or "image.jpg",
            "mediaType": "IMAGE",
        }


# --- Trading API GetItem (by item ID) ---
# https://developer.ebay.com/devzone/xml/docs/reference/ebay/getitem.html
# Uses same user OAuth token via X-EBAY-API-IAF-TOKEN. Returns listing details including SKU when listing is SKU-tracked.

# Marketplace ID (REST) -> Trading API SiteID
_EBAY_MARKETPLACE_TO_SITE_ID: Dict[str, int] = {
    "EBAY_US": 0,
    "EBAY_CA": 2,
    "EBAY_GB": 3,
    "EBAY_AU": 15,
    "EBAY_AT": 16,
    "EBAY_DE": 77,
    "EBAY_FR": 71,
    "EBAY_IT": 101,
    "EBAY_ES": 186,
}


async def trading_get_item(access_token: str, item_id: str) -> Dict[str, Any]:
    """
    Trading API GetItem: get listing by item ID (e.g. 136528644539 from ebay.com/itm/136528644539).
    Uses settings.EBAY_MARKETPLACE_ID for SiteID (e.g. EBAY_GB = UK).
    Returns {"sku": "...", "title": "..."} when listing has SKU; SKU may be None for legacy listings.
    Raises httpx.HTTPStatusError on HTTP errors; on API errors (e.g. invalid item) response body is in exception.
    """
    import logging
    import xml.etree.ElementTree as ET

    log = logging.getLogger(__name__)
    item_id = str(item_id).strip()
    mkt = (settings.EBAY_MARKETPLACE_ID or "EBAY_GB").strip().upper()
    site_id = _EBAY_MARKETPLACE_TO_SITE_ID.get(mkt, 3)
    url = "https://api.ebay.com/ws/api.dll"
    payload = (
        '<?xml version="1.0" encoding="utf-8"?>'
        "<GetItemRequest xmlns=\"urn:ebay:apis:eBLBaseComponents\">"
        "<DetailLevel>ReturnAll</DetailLevel>"
        f"<ItemID>{item_id}</ItemID>"
        "</GetItemRequest>"
    )
    headers = {
        "X-EBAY-API-IAF-TOKEN": access_token,
        "X-EBAY-API-CALL-NAME": "GetItem",
        "X-EBAY-API-SITEID": str(site_id),
        "X-EBAY-API-COMPATIBILITY-LEVEL": "1085",
        "Content-Type": "application/xml",
    }
    log.info("listing_video: trading_get_item item_id=%s site_id=%s", item_id, site_id)
    async with httpx.AsyncClient() as client:
        r = await client.post(url, content=payload, headers=headers)
    log.info("listing_video: trading_get_item status=%s", r.status_code)
    if r.status_code != 200:
        log.warning("listing_video: trading_get_item body=%s", (r.text or "")[:500])
        r.raise_for_status()

    root = ET.fromstring(r.text or "")
    # eBay response uses default namespace urn:ebay:apis:eBLBaseComponents; ET exposes as {uri}LocalName
    NS = "urn:ebay:apis:eBLBaseComponents"
    errors = root.findall(f".//{{{NS}}}Errors/{{{NS}}}Error")
    if not errors:
        errors = root.findall(".//Errors/Error")
    if errors:
        err = errors[0]
        code = err.find(f"{{{NS}}}ErrorCode") or err.find("ErrorCode")
        short = err.find(f"{{{NS}}}ShortMessage") or err.find("ShortMessage")
        code_val = code.text if code is not None else ""
        msg = (short.text if short is not None else "") or "Trading API error"
        log.warning("listing_video: trading_get_item API error code=%s msg=%s", code_val, msg)
        raise httpx.HTTPStatusError(
            msg,
            request=r.request,
            response=r,
        )

    item = root.find(f".//{{{NS}}}Item") or root.find(".//Item")
    if item is None:
        raise httpx.HTTPStatusError(
            "GetItem response missing Item",
            request=r.request,
            response=r,
        )
    sku_el = item.find(f"{{{NS}}}SKU") or item.find("SKU")
    title_el = item.find(f"{{{NS}}}Title") or item.find("Title")
    sku = (sku_el.text or "").strip() or None if sku_el is not None else None
    title = (title_el.text or "").strip() or None if title_el is not None else None
    video_ids: List[str] = []
    video_details = item.find(f"{{{NS}}}VideoDetails") or item.find("VideoDetails")
    if video_details is not None:
        for vid_el in video_details.findall(f"{{{NS}}}VideoID") or video_details.findall("VideoID") or []:
            if vid_el.text and (v := (vid_el.text or "").strip()):
                video_ids.append(v)  # preserve exact character count; do not truncate
    log.info("listing_video: trading_get_item sku=%s title=%s video_ids=%s", sku, (title[:50] + "..." if title and len(title) > 50 else title), video_ids)
    return {"sku": sku, "title": title, "item_id": item_id, "video_ids": video_ids}


def _trading_xml_escape(s: str) -> str:
    """Escape for use inside an XML element text."""
    if not s:
        return ""
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


async def trading_revise_fixed_price_item(
    access_token: str, item_id: str, video_id: str, marketplace_id: Optional[str] = None
) -> None:
    """
    Trading API ReviseFixedPriceItem: add (or set) video on a listing by item ID.
    Uses same auth; SiteID from marketplace_id if provided, else settings.EBAY_MARKETPLACE_ID.
    Raises httpx.HTTPStatusError on HTTP or API errors.
    """
    import logging
    import xml.etree.ElementTree as ET

    log = logging.getLogger(__name__)
    item_id = str(item_id).strip()
    video_id = (video_id or "").strip()
    if not video_id:
        raise ValueError("video_id is required")
    mkt = (marketplace_id or settings.EBAY_MARKETPLACE_ID or "EBAY_GB").strip().upper()
    site_id = _EBAY_MARKETPLACE_TO_SITE_ID.get(mkt, 3)
    url = "https://api.ebay.com/ws/api.dll"
    payload = (
        '<?xml version="1.0" encoding="utf-8"?>'
        "<ReviseFixedPriceItemRequest xmlns=\"urn:ebay:apis:eBLBaseComponents\">"
        f"<Item><ItemID>{_trading_xml_escape(item_id)}</ItemID>"
        "<VideoDetails>"
        f"<VideoID>{_trading_xml_escape(video_id)}</VideoID>"
        "</VideoDetails></Item>"
        "</ReviseFixedPriceItemRequest>"
    )
    headers = {
        "X-EBAY-API-IAF-TOKEN": access_token,
        "X-EBAY-API-CALL-NAME": "ReviseFixedPriceItem",
        "X-EBAY-API-SITEID": str(site_id),
        "X-EBAY-API-COMPATIBILITY-LEVEL": "1085",
        "Content-Type": "application/xml",
    }
    log.info("listing_video: trading_revise_fixed_price_item item_id=%s", item_id)
    async with httpx.AsyncClient() as client:
        r = await client.post(url, content=payload, headers=headers)
    log.info("listing_video: trading_revise_fixed_price_item status=%s", r.status_code)
    if r.status_code != 200:
        log.warning("listing_video: trading_revise body=%s", (r.text or "")[:500])
        r.raise_for_status()

    root = ET.fromstring(r.text or "")
    NS = "urn:ebay:apis:eBLBaseComponents"
    errors = root.findall(f".//{{{NS}}}Errors/{{{NS}}}Error")
    if not errors:
        errors = root.findall(".//Errors/Error")
    if errors:
        err = errors[0]
        code = err.find(f"{{{NS}}}ErrorCode") or err.find("ErrorCode")
        short = err.find(f"{{{NS}}}ShortMessage") or err.find("ShortMessage")
        code_val = code.text if code is not None else ""
        msg = (short.text if short is not None else "") or "Trading API error"
        log.warning("listing_video: trading_revise API error code=%s msg=%s", code_val, msg)
        raise httpx.HTTPStatusError(
            msg,
            request=r.request,
            response=r,
        )


async def trading_get_seller_list_by_sku(
    access_token: str, sku: str, marketplace_id: Optional[str] = None
):
    """
    Trading API GetSellerList without SKUArray; fetches all active listings, filters server-side by SKU (case-insensitive).
    Yields progress dicts {"type": "progress", "message": "Scanned page X/Y, found Z matches so far"}, then yields the list of matched item IDs.
    CSV-uploaded listings are not matched by GetSellerList SKUArray; this hybrid approach works for them.
    """
    import logging
    import xml.etree.ElementTree as ET

    log = logging.getLogger(__name__)
    sku = (sku or "").strip()
    sku_lower = sku.lower() if sku else ""
    if not sku:
        yield []
        return
    mkt = (marketplace_id or settings.EBAY_MARKETPLACE_ID or "EBAY_GB").strip().upper()
    site_id = _EBAY_MARKETPLACE_TO_SITE_ID.get(mkt, 3)
    url = "https://api.ebay.com/ws/api.dll"
    now = datetime.now(timezone.utc)
    end_from = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    end_to = (now + timedelta(days=120)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    matched_item_ids: List[str] = []
    page = 1
    per_page = 200
    NS = "urn:ebay:apis:eBLBaseComponents"
    total_pages = 1

    while True:
        payload = (
            '<?xml version="1.0" encoding="utf-8"?>'
            "<GetSellerListRequest xmlns=\"urn:ebay:apis:eBLBaseComponents\">"
            f"<EndTimeFrom>{end_from}</EndTimeFrom>"
            f"<EndTimeTo>{end_to}</EndTimeTo>"
            "<GranularityLevel>Fine</GranularityLevel>"
            "<Pagination>"
            f"<EntriesPerPage>{per_page}</EntriesPerPage>"
            f"<PageNumber>{page}</PageNumber>"
            "</Pagination>"
            "</GetSellerListRequest>"
        )
        headers = {
            "X-EBAY-API-IAF-TOKEN": access_token,
            "X-EBAY-API-CALL-NAME": "GetSellerList",
            "X-EBAY-API-SITEID": str(site_id),
            "X-EBAY-API-COMPATIBILITY-LEVEL": "1085",
            "Content-Type": "application/xml",
        }
        log.info("listing_video: trading_get_seller_list_by_sku sku=%s page=%s", sku, page)
        async with httpx.AsyncClient() as client:
            r = await client.post(url, content=payload, headers=headers)
        if r.status_code != 200:
            log.warning("listing_video: GetSellerList status=%s body=%s", r.status_code, (r.text or "")[:500])
            r.raise_for_status()

        root = ET.fromstring(r.text or "")
        errors = root.findall(f".//{{{NS}}}Errors/{{{NS}}}Error")
        if not errors:
            errors = root.findall(".//Errors/Error")
        if errors:
            err = errors[0]
            short = err.find(f"{{{NS}}}ShortMessage") or err.find("ShortMessage")
            msg = (short.text if short is not None else "") or "GetSellerList error"
            log.warning("listing_video: GetSellerList API error: %s", msg)
            raise httpx.HTTPStatusError(msg, request=r.request, response=r)

        pagination_result = root.find(f".//{{{NS}}}PaginationResult") or root.find(".//PaginationResult")
        if pagination_result is not None:
            total_el = pagination_result.find(f"{{{NS}}}TotalNumberOfPages") or pagination_result.find("TotalNumberOfPages")
            if total_el is not None and total_el.text:
                try:
                    total_pages = max(1, int(total_el.text))
                except (TypeError, ValueError):
                    pass

        item_array = root.find(f".//{{{NS}}}ItemArray") or root.find(".//ItemArray")
        if item_array is None:
            if page == 1:
                log.warning("listing_video: GetSellerList sku=%s site_id=%s returned no ItemArray", sku, site_id)
            break
        items = item_array.findall(f"{{{NS}}}Item") or item_array.findall("Item") or []
        for item in items:
            sku_el = item.find(f"{{{NS}}}SKU") or item.find("SKU")
            if sku_el is not None and sku_el.text and (sku_el.text or "").strip().lower() == sku_lower:
                iid_el = item.find(f"{{{NS}}}ItemID") or item.find("ItemID")
                if iid_el is not None and iid_el.text:
                    iid = (iid_el.text or "").strip()
                    if iid:
                        matched_item_ids.append(iid)

        yield {"type": "progress", "message": f"Scanned page {page}/{total_pages}, found {len(matched_item_ids)} matches so far."}

        if page >= total_pages:
            break
        if len(items) < per_page:
            break
        page += 1
        if page > 100:
            break

    log.info("listing_video: trading_get_seller_list_by_sku sku=%s found=%s", sku, len(matched_item_ids))
    yield matched_item_ids


# --- Sell Inventory API (listing / video on inventory item) ---
# Requires sell.inventory scope. Base: api.ebay.com
# https://developer.ebay.com/api-docs/sell/inventory/resources/inventory_item/methods/getInventoryItem
# https://developer.ebay.com/api-docs/sell/inventory/resources/inventory_item/methods/createOrReplaceInventoryItem


def _encode_sku(sku: str) -> str:
    """URL-encode SKU for path (eBay allows special chars in SKU)."""
    from urllib.parse import quote
    return quote(str(sku).strip(), safe="")


async def get_inventory_items(
    access_token: str, limit: int = 100, offset: int = 0
) -> Dict[str, Any]:
    """
    List inventory item SKUs (getInventoryItems). Returns paginated { inventoryItems: [ { sku }, ... ], total, ... }.
    Used to search for which SKU has a given listingId.
    """
    import logging
    log = logging.getLogger(__name__)
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{settings.EBAY_API_URL}/sell/inventory/v1/inventory_item",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            params={"limit": limit, "offset": offset},
        )
        log.info("listing_video: get_inventory_items status=%s", r.status_code)
        r.raise_for_status()
        return r.json()


async def get_offers(access_token: str, sku: str) -> Dict[str, Any]:
    """
    Get offers for a SKU (getOffers). Returns { offers: [ { offerId, sku, listing: { listingId }, ... } ], ... }.
    Used to find which SKU has listingId == item number.
    """
    import logging
    log = logging.getLogger(__name__)
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{settings.EBAY_API_URL}/sell/inventory/v1/offer",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            params={"sku": sku},
        )
        log.info("listing_video: get_offers sku=%s status=%s", sku, r.status_code)
        r.raise_for_status()
        return r.json()


async def get_offer(access_token: str, offer_id: str) -> Dict[str, Any]:
    """
    Get offer by offer ID (getOffer). Use listing ID (item number) as offer_id when they are the same.
    Returns offer details including sku so we can fetch the inventory item for videoIds.
    """
    import logging
    log = logging.getLogger(__name__)
    from urllib.parse import quote
    offer_id = str(offer_id).strip()
    encoded = quote(offer_id, safe="")
    url = f"{settings.EBAY_API_URL}/sell/inventory/v1/offer/{encoded}"
    log.info("listing_video: get_offer request offer_id=%s url=%s", offer_id, url)
    async with httpx.AsyncClient() as client:
        r = await client.get(
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
        )
        log.info("listing_video: get_offer response status=%s", r.status_code)
        if r.status_code != 200:
            log.warning("listing_video: get_offer error body=%s", r.text[:500] if r.text else "")
        r.raise_for_status()
        data = r.json()
        log.info("listing_video: get_offer keys=%s sku=%s inventoryItemId=%s", list(data.keys()) if isinstance(data, dict) else type(data), data.get("sku") if isinstance(data, dict) else None, data.get("inventoryItemId") if isinstance(data, dict) else None)
        return data


async def get_inventory_item(access_token: str, sku: str) -> Dict[str, Any]:
    """
    Get inventory item by SKU (getInventoryItem). Returns full item including product (images, videoIds, etc.).
    Raises httpx.HTTPStatusError on 404 or other API errors.
    """
    import logging
    log = logging.getLogger(__name__)
    encoded = _encode_sku(sku)
    url = f"{settings.EBAY_API_URL}/sell/inventory/v1/inventory_item/{encoded}"
    log.info("listing_video: get_inventory_item request sku=%s encoded=%s", sku, encoded)
    async with httpx.AsyncClient() as client:
        r = await client.get(
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
        )
        log.info("listing_video: get_inventory_item response status=%s", r.status_code)
        if r.status_code != 200:
            log.warning("listing_video: get_inventory_item error body=%s", r.text[:500] if r.text else "")
        r.raise_for_status()
        data = r.json()
        product = data.get("product") if isinstance(data, dict) else None
        video_ids = product.get("videoIds") if isinstance(product, dict) else None
        log.info("listing_video: get_inventory_item product keys=%s videoIds=%s", list(product.keys()) if isinstance(product, dict) else None, video_ids)
        return data


async def create_or_replace_inventory_item(
    access_token: str, sku: str, body: Dict[str, Any]
) -> None:
    """
    Create or replace inventory item (createOrReplaceInventoryItem). Use after modifying body (e.g. product.videoIds).
    Returns 204 No Content on success.
    """
    encoded = _encode_sku(sku)
    async with httpx.AsyncClient() as client:
        r = await client.put(
            f"{settings.EBAY_API_URL}/sell/inventory/v1/inventory_item/{encoded}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json=body,
        )
        r.raise_for_status()
