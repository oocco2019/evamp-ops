"""Fingerprint layouts from sorted rounded content-box sizes."""

from __future__ import annotations

import hashlib
from typing import Iterable, Sequence

from app.services.label_compose import LAYOUT_FINGERPRINT_TAG, PT_PER_MM, ROUND_MM, SIDE_MARGIN_MM, VERTICAL_MARGIN_MM
from app.services.label_compose.detect import ContentBox


def box_size_mm(box: ContentBox) -> tuple[float, float]:
    return (box.width / PT_PER_MM, box.height / PT_PER_MM)


def round_mm(value: float, step: float = ROUND_MM) -> int:
    if step <= 0:
        return int(round(value))
    return int(round(value / step) * step)


def fingerprint_from_boxes(boxes: Sequence[ContentBox]) -> str:
    """Stable key: layout params + sorted rounded (w_mm, h_mm) pairs."""
    parts = sorted(
        (round_mm(w), round_mm(h)) for w, h in (box_size_mm(b) for b in boxes)
    )
    sizes = ",".join(f"{w}x{h}" for w, h in parts)
    payload = (
        f"{LAYOUT_FINGERPRINT_TAG}|side={SIDE_MARGIN_MM}|vert={VERTICAL_MARGIN_MM}|{sizes}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def fingerprint_from_sizes_mm(sizes: Iterable[tuple[float, float]]) -> str:
    parts = sorted((round_mm(w), round_mm(h)) for w, h in sizes)
    size_s = ",".join(f"{w}x{h}" for w, h in parts)
    payload = (
        f"{LAYOUT_FINGERPRINT_TAG}|side={SIDE_MARGIN_MM}|vert={VERTICAL_MARGIN_MM}|{size_s}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
