"""
Shopify Admin REST API: order fetch for sales analytics (same DB shape as eBay import).
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, parse_qs, unquote

import httpx


# Stable Admin API version (orders.json).
SHOPIFY_API_VERSION = "2024-10"


def _dec(val: Any) -> Optional[Decimal]:
    if val is None or val == "":
        return None
    try:
        return Decimal(str(val).strip())
    except Exception:
        return None


def _parse_ts_to_naive_utc(s: Optional[str]) -> Optional[datetime]:
    if not s or not str(s).strip():
        return None
    t = str(s).strip()
    # ISO 8601 with Z or offset
    t = t.replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(t)
    except ValueError:
        return None
    if d.tzinfo is not None:
        d = d.astimezone(timezone.utc).replace(tzinfo=None)
    return d


def _date_from_shopify(created_at: Optional[str]) -> date:
    dt = _parse_ts_to_naive_utc(created_at)
    if dt:
        return dt.date()
    return date.today()


def _country(order: dict) -> str:
    sa = (order.get("shipping_address") or {}) or {}
    cc = (sa.get("country_code") or "").strip().upper()[:2]
    if cc:
        return cc
    ba = (order.get("billing_address") or {}) or {}
    return (ba.get("country_code") or "").strip().upper()[:2] or "XX"


def _cancel_status(order: dict) -> Optional[str]:
    if order.get("cancelled_at"):
        return "CANCELED"
    return None  # eBay also uses NONE_REQUESTED; NULL matches _not_canceled for Shopify


def _line_items(order: dict) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    cur = (order.get("currency") or "GBP").strip().upper()[:3]
    for li in order.get("line_items") or []:
        eid = str(li.get("id") or "")
        if not eid:
            continue
        sku = (li.get("sku") or "").strip() or "UNKNOWN"
        qty = int(li.get("quantity") or 0) or 0
        if qty <= 0:
            continue
        unit = _dec(li.get("price"))
        line_total = unit * Decimal(qty) if unit is not None else _dec(li.get("pre_tax_price"))
        if line_total is None:
            line_total = _dec(li.get("discounted_total")) or _dec(li.get("line_price"))
        pre_tax = _dec(li.get("pre_tax_price")) or unit
        tax_lines = li.get("tax_lines") or []
        tax_sum = None
        if tax_lines:
            tax_sum = sum((_dec(t.get("price")) or Decimal(0)) for t in tax_lines)
        out.append(
            {
                "ebay_line_item_id": eid,
                "sku": sku,
                "quantity": qty,
                "currency": cur,
                "line_item_cost": pre_tax,
                "discounted_line_item_cost": _dec(li.get("discounted_price")) or pre_tax,
                "line_total": line_total,
                "tax_amount": tax_sum,
            }
        )
    if not out:
        oid = str(order.get("id") or "")
        out = [
            {
                "ebay_line_item_id": oid or "0",
                "sku": "UNKNOWN",
                "quantity": 1,
                "currency": cur,
                "line_item_cost": None,
                "discounted_line_item_cost": None,
                "line_total": _dec(order.get("current_subtotal_price")) or _dec(order.get("subtotal_price")),
                "tax_amount": None,
            }
        ]
    return out


def parse_shopify_order_to_import(order: dict) -> dict:
    """
    Map one Shopify order JSON to the same structure as eBay `parse_orders_to_import` output
    (keys consumed by `execute_order_import` / Shopify path).
    """
    oid = str(int(order.get("id") or 0))
    if not oid or oid == "0":
        raise ValueError("Shopify order missing id")

    created = order.get("created_at")
    last_mod = _parse_ts_to_naive_utc(order.get("updated_at")) or _parse_ts_to_naive_utc(created) or datetime.utcnow()
    ccy = (order.get("currency") or "GBP").strip().upper()[:3] or "GBP"

    price_total = _dec(order.get("current_total_price")) or _dec(order.get("total_price"))
    subtotal = _dec(order.get("current_subtotal_price")) or _dec(order.get("subtotal_price"))
    tax_total = _dec(order.get("current_total_tax")) or _dec(order.get("total_tax"))
    ship = _dec(order.get("total_shipping") or (order.get("total_shipping_price_set") or {}).get("shop_money", {}).get("amount"))
    disc = _dec(order.get("current_total_discounts")) or _dec(order.get("total_discounts"))

    # "Seller revenue" proxy (same field names as eBay; profit code converts to GBP):
    # Prefer order total less tax; falls back to subtotal + shipping.
    if price_total is not None and tax_total is not None:
        payout = price_total - tax_total
    elif subtotal is not None and ship is not None:
        payout = subtotal + ship - (disc or Decimal(0))
    else:
        payout = price_total or subtotal or Decimal(0)

    line_items = _line_items(order)

    buyer = (order.get("email") or order.get("name") or order.get("order_number") or "")

    return {
        "ebay_order_id": oid,
        "date": _date_from_shopify(created),
        "country": _country(order),
        "last_modified": last_mod,
        "cancel_status": _cancel_status(order),
        "buyer_username": str(buyer)[:255] if buyer else None,
        "order_currency": ccy,
        "price_subtotal": subtotal,
        "price_total": price_total,
        "tax_total": tax_total,
        "delivery_cost": ship,
        "price_discount": disc,
        "fee_total": None,
        "total_fee_basis_amount": None,
        "total_marketplace_fee": None,
        "total_due_seller": payout,
        "total_due_seller_currency": ccy,
        "order_payment_status": (order.get("financial_status") or "")[:50] or None,
        "sales_record_reference": str(order.get("name") or "")[:100] or None,
        "ebay_collect_and_remit_tax": None,
        "line_items": line_items,
    }


def _next_page_info(link_header: str) -> Optional[str]:
    if not link_header:
        return None
    for part in link_header.split(","):
        if 'rel="next"' not in part and "rel='next'" not in part:
            continue
        m = re.search(r"[<]([^>]+)[>]", part)
        if not m:
            continue
        url = m.group(1)
        q = parse_qs(urlparse(url).query)
        info = (q.get("page_info") or [None])[0]
        if info:
            return unquote(info)
    return None


def _base_url(shop: str) -> str:
    s = (shop or "").strip().rstrip("/")
    if not s:
        return ""
    s = s.replace("https://", "").replace("http://", "")
    s = s.split("/")[0]
    if ".myshopify.com" not in s:
        s = f"{s}.myshopify.com"
    return f"https://{s}"


async def fetch_shopify_orders_paginated(
    shop_domain: str,
    access_token: str,
    *,
    updated_at_min: Optional[datetime] = None,
    created_at_min: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch all orders in window, following Admin cursor pagination.
    status=any includes open and closed. Financial status is on each order.
    """
    base = _base_url(shop_domain)
    if not base or not access_token:
        return []

    headers = {
        "X-Shopify-Access-Token": access_token.strip(),
        "Content-Type": "application/json",
    }
    field_list = (
        "id,name,email,created_at,updated_at,cancelled_at,closed_at,"
        "currency,financial_status,fulfillment_status,"
        "subtotal_price,current_subtotal_price,total_line_items_price,"
        "current_total_price,total_price,total_tax,current_total_tax,total_shipping,total_shipping_price_set,"
        "total_discounts,current_total_discounts,shipping_address,billing_address,"
        "line_items,order_number"
    )

    first_params: dict = {
        "status": "any",
        "limit": "250",
        "fields": field_list,
    }
    if updated_at_min:
        s = updated_at_min.replace(tzinfo=timezone.utc) if updated_at_min.tzinfo is None else updated_at_min
        s = s.astimezone(timezone.utc).replace(tzinfo=None)
        first_params["updated_at_min"] = s.replace(microsecond=0).isoformat() + "Z"
    elif created_at_min:
        s = created_at_min.replace(tzinfo=timezone.utc) if created_at_min.tzinfo is None else created_at_min
        s = s.astimezone(timezone.utc).replace(tzinfo=None)
        first_params["created_at_min"] = s.replace(microsecond=0).isoformat() + "Z"

    all_orders: List[dict] = []
    url = f"{base}/admin/api/{SHOPIFY_API_VERSION}/orders.json"
    page_info: Optional[str] = None

    async with httpx.AsyncClient(timeout=120.0) as client:
        for _ in range(500):
            if page_info is None:
                p = first_params
            else:
                p = {
                    "limit": "250",
                    "page_info": page_info,
                    "fields": field_list,
                }
            r = await client.get(url, headers=headers, params=p)
            r.raise_for_status()
            data = r.json() or {}
            batch = data.get("orders") or []
            all_orders.extend(batch)
            nxt = _next_page_info(r.headers.get("link") or "")
            if not nxt:
                break
            page_info = nxt

    return all_orders
