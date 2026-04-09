"""Helpers for OC inventory snapshot history (movement vs prior observation)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class HistoryPoint:
    recorded_at: datetime
    mfskuid: str
    service_region: str
    available: int
    in_transit: int
    received: int


def attach_deltas(points: List[HistoryPoint]) -> List[Dict[str, Any]]:
    """
    For each (mfskuid, service_region) series, ordered by recorded_at, set delta_* vs previous row.
    """
    key_fn = lambda p: (p.mfskuid.strip().lower(), (p.service_region or "").strip().upper())
    by_key: Dict[tuple[str, str], List[HistoryPoint]] = {}
    for p in points:
        k = key_fn(p)
        by_key.setdefault(k, []).append(p)
    out: List[Dict[str, Any]] = []
    for series in by_key.values():
        series.sort(key=lambda x: x.recorded_at)
        prev: Optional[HistoryPoint] = None
        for p in series:
            d_av: Optional[int] = None
            d_it: Optional[int] = None
            d_rc: Optional[int] = None
            if prev is not None:
                d_av = p.available - prev.available
                d_it = p.in_transit - prev.in_transit
                d_rc = p.received - prev.received
            out.append(
                {
                    "recorded_at": p.recorded_at,
                    "mfskuid": p.mfskuid,
                    "service_region": p.service_region,
                    "available": p.available,
                    "in_transit": p.in_transit,
                    "received": p.received,
                    "delta_available": d_av,
                    "delta_in_transit": d_it,
                    "delta_received": d_rc,
                }
            )
            prev = p
    out.sort(key=lambda r: (r["recorded_at"], r["mfskuid"].lower(), r["service_region"]))
    return out
