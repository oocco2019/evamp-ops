"""N-agnostic shelf/column packer for A4 label sheets."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Literal, Optional, Sequence

from app.services.label_compose import (
    A4_HEIGHT_PT,
    A4_WIDTH_PT,
    INTER_LABEL_GAP_MM,
    MIN_SCALE,
    PT_PER_MM,
    SIDE_MARGIN_MM,
    VERTICAL_MARGIN_MM,
)
from app.services.label_compose.detect import ContentBox


PackMode = Literal["shelf_ltr", "shelf_rtl", "column_ttb", "column_btt"]
MODES: list[PackMode] = ["shelf_ltr", "shelf_rtl", "column_ttb", "column_btt"]


@dataclass(frozen=True)
class LabelInput:
    source_index: int
    box: ContentBox

    @property
    def width(self) -> float:
        return self.box.width

    @property
    def height(self) -> float:
        return self.box.height

    @property
    def area(self) -> float:
        return self.box.area


@dataclass
class Slot:
    source_index: int
    x: float
    y: float
    width: float
    height: float
    scale: float
    crop_llx: float
    crop_lly: float
    crop_urx: float
    crop_ury: float

    def to_dict(self) -> dict:
        return {
            "source_index": self.source_index,
            "x": round(self.x, 3),
            "y": round(self.y, 3),
            "width": round(self.width, 3),
            "height": round(self.height, 3),
            "scale": round(self.scale, 5),
            "crop": {
                "llx": round(self.crop_llx, 3),
                "lly": round(self.crop_lly, 3),
                "urx": round(self.crop_urx, 3),
                "ury": round(self.crop_ury, 3),
            },
        }

    @staticmethod
    def from_dict(d: dict) -> "Slot":
        crop = d.get("crop") or {}
        return Slot(
            source_index=int(d["source_index"]),
            x=float(d["x"]),
            y=float(d["y"]),
            width=float(d["width"]),
            height=float(d["height"]),
            scale=float(d.get("scale") or 1.0),
            crop_llx=float(crop.get("llx", 0)),
            crop_lly=float(crop.get("lly", 0)),
            crop_urx=float(crop.get("urx", 0)),
            crop_ury=float(crop.get("ury", 0)),
        )

    @property
    def crop_size_pt(self) -> tuple[float, float]:
        return (abs(self.crop_urx - self.crop_llx), abs(self.crop_ury - self.crop_lly))


def _place_base(
    label: LabelInput,
    side_margin: float,
    top_margin: float,
    scale: float,
) -> Slot:
    w = label.width * scale
    h = label.height * scale
    x = side_margin + max(0.0, (A4_WIDTH_PT - 2 * side_margin - w) / 2.0)
    y = A4_HEIGHT_PT - top_margin - h
    return Slot(
        source_index=label.source_index,
        x=x,
        y=y,
        width=w,
        height=h,
        scale=scale,
        crop_llx=label.box.llx,
        crop_lly=label.box.lly,
        crop_urx=label.box.urx,
        crop_ury=label.box.ury,
    )


def _pack_remaining_shelf(
    items: Sequence[LabelInput],
    *,
    region_x: float,
    region_y: float,
    region_w: float,
    region_h: float,
    gap: float,
    scale: float,
    rtl: bool,
) -> Optional[list[Slot]]:
    if region_w <= 0 or region_h <= 0:
        return None if items else []
    slots: list[Slot] = []
    cursor_y_top = region_y + region_h
    i = 0
    n = len(items)
    while i < n:
        row: list[LabelInput] = []
        row_w = 0.0
        row_h = 0.0
        while i < n:
            it = items[i]
            iw = it.width * scale
            ih = it.height * scale
            need = iw if not row else iw + gap
            if row and row_w + need > region_w + 1e-6:
                break
            if not row and iw > region_w + 1e-6:
                return None
            if ih > region_h + 1e-6:
                return None
            row.append(it)
            row_w += need
            row_h = max(row_h, ih)
            i += 1
        if not row:
            return None
        if cursor_y_top - row_h < region_y - 1e-6:
            return None
        # Center the row as a unit in the free region (shared vertical axis with base)
        row_start = region_x + max(0.0, (region_w - row_w) / 2.0)
        if rtl:
            x = row_start + row_w
            for it in row:
                iw = it.width * scale
                ih = it.height * scale
                x -= iw
                slots.append(
                    Slot(
                        source_index=it.source_index,
                        x=x,
                        y=cursor_y_top - row_h + (row_h - ih),
                        width=iw,
                        height=ih,
                        scale=scale,
                        crop_llx=it.box.llx,
                        crop_lly=it.box.lly,
                        crop_urx=it.box.urx,
                        crop_ury=it.box.ury,
                    )
                )
                x -= gap
        else:
            x = row_start
            for it in row:
                iw = it.width * scale
                ih = it.height * scale
                slots.append(
                    Slot(
                        source_index=it.source_index,
                        x=x,
                        y=cursor_y_top - row_h + (row_h - ih),
                        width=iw,
                        height=ih,
                        scale=scale,
                        crop_llx=it.box.llx,
                        crop_lly=it.box.lly,
                        crop_urx=it.box.urx,
                        crop_ury=it.box.ury,
                    )
                )
                x += iw + gap
        cursor_y_top -= row_h + gap
    return slots


def _pack_remaining_column(
    items: Sequence[LabelInput],
    *,
    region_x: float,
    region_y: float,
    region_w: float,
    region_h: float,
    gap: float,
    scale: float,
    bottom_up: bool,
) -> Optional[list[Slot]]:
    if region_w <= 0 or region_h <= 0:
        return None if items else []
    # Build columns first, then center the whole block in the region.
    columns: list[tuple[list[LabelInput], float, float]] = []
    i = 0
    n = len(items)
    while i < n:
        col: list[LabelInput] = []
        col_h = 0.0
        col_w = 0.0
        while i < n:
            it = items[i]
            iw = it.width * scale
            ih = it.height * scale
            need = ih if not col else ih + gap
            if col and col_h + need > region_h + 1e-6:
                break
            if not col and ih > region_h + 1e-6:
                return None
            if iw > region_w + 1e-6:
                return None
            col.append(it)
            col_h += need
            col_w = max(col_w, iw)
            i += 1
        if not col:
            return None
        columns.append((col, col_w, col_h))

    total_w = sum(cw for _, cw, _ in columns) + gap * max(0, len(columns) - 1)
    if total_w > region_w + 1e-6:
        return None
    cursor_x = region_x + max(0.0, (region_w - total_w) / 2.0)

    slots: list[Slot] = []
    for col, col_w, col_h in columns:
        if bottom_up:
            y = region_y + max(0.0, (region_h - col_h) / 2.0)
            for it in col:
                iw = it.width * scale
                ih = it.height * scale
                slots.append(
                    Slot(
                        source_index=it.source_index,
                        x=cursor_x + (col_w - iw) / 2.0,
                        y=y,
                        width=iw,
                        height=ih,
                        scale=scale,
                        crop_llx=it.box.llx,
                        crop_lly=it.box.lly,
                        crop_urx=it.box.urx,
                        crop_ury=it.box.ury,
                    )
                )
                y += ih + gap
        else:
            y_top = region_y + region_h - max(0.0, (region_h - col_h) / 2.0)
            for it in col:
                iw = it.width * scale
                ih = it.height * scale
                y_top -= ih
                slots.append(
                    Slot(
                        source_index=it.source_index,
                        x=cursor_x + (col_w - iw) / 2.0,
                        y=y_top,
                        width=iw,
                        height=ih,
                        scale=scale,
                        crop_llx=it.box.llx,
                        crop_lly=it.box.lly,
                        crop_urx=it.box.urx,
                        crop_ury=it.box.ury,
                    )
                )
                y_top -= gap
        cursor_x += col_w + gap
    return slots


def _try_layout(
    ordered: Sequence[LabelInput],
    *,
    scale: float,
    mode: PackMode,
    side_margin_mm: float = SIDE_MARGIN_MM,
    vertical_margin_mm: float = VERTICAL_MARGIN_MM,
    gap_mm: float = INTER_LABEL_GAP_MM,
) -> Optional[list[Slot]]:
    side = side_margin_mm * PT_PER_MM
    vert = vertical_margin_mm * PT_PER_MM
    gap = gap_mm * PT_PER_MM
    if not ordered:
        return []

    base = ordered[0]
    base_scale = min(scale, 1.0)
    max_base_w = A4_WIDTH_PT - 2 * side
    max_base_h = A4_HEIGHT_PT - 2 * vert
    if base.width * base_scale > max_base_w:
        base_scale = max_base_w / base.width
    if base.height * base_scale > max_base_h:
        base_scale = min(base_scale, max_base_h / base.height)
    if base_scale < MIN_SCALE - 1e-9:
        return None
    base_scale = min(base_scale, 1.0)

    base_slot = _place_base(base, side, vert, base_scale)
    rest = list(ordered[1:])
    if not rest:
        return [base_slot]

    free_top = base_slot.y - gap
    free_bottom = vert
    free_h = free_top - free_bottom
    free_x = side
    free_w = A4_WIDTH_PT - 2 * side
    if free_h <= 0:
        return None

    rem_scale = min(scale, 1.0)
    if mode == "shelf_ltr":
        rem = _pack_remaining_shelf(
            rest,
            region_x=free_x,
            region_y=free_bottom,
            region_w=free_w,
            region_h=free_h,
            gap=gap,
            scale=rem_scale,
            rtl=False,
        )
    elif mode == "shelf_rtl":
        rem = _pack_remaining_shelf(
            rest,
            region_x=free_x,
            region_y=free_bottom,
            region_w=free_w,
            region_h=free_h,
            gap=gap,
            scale=rem_scale,
            rtl=True,
        )
    elif mode == "column_ttb":
        rem = _pack_remaining_column(
            rest,
            region_x=free_x,
            region_y=free_bottom,
            region_w=free_w,
            region_h=free_h,
            gap=gap,
            scale=rem_scale,
            bottom_up=False,
        )
    else:
        rem = _pack_remaining_column(
            rest,
            region_x=free_x,
            region_y=free_bottom,
            region_w=free_w,
            region_h=free_h,
            gap=gap,
            scale=rem_scale,
            bottom_up=True,
        )
    if rem is None:
        return None
    return [base_slot, *rem]


def _max_scale_for(
    ordered: Sequence[LabelInput],
    mode: PackMode,
) -> Optional[tuple[float, list[Slot]]]:
    lo, hi = MIN_SCALE, 1.0
    trial = _try_layout(ordered, scale=lo, mode=mode)
    if trial is None:
        return None
    best: tuple[float, list[Slot]] = (lo, trial)
    for _ in range(18):
        mid = (lo + hi) / 2.0
        slots = _try_layout(ordered, scale=mid, mode=mode)
        if slots is not None:
            best = (mid, slots)
            lo = mid
        else:
            hi = mid
    return best


def _whitespace(slots: list[Slot]) -> float:
    used = sum(s.width * s.height for s in slots)
    printable = (A4_WIDTH_PT - 2 * SIDE_MARGIN_MM * PT_PER_MM) * (
        A4_HEIGHT_PT - 2 * VERTICAL_MARGIN_MM * PT_PER_MM
    )
    return max(0.0, printable - used)


def center_slots_on_a4(
    slots: Sequence[Slot],
    *,
    side_mm: float = SIDE_MARGIN_MM,
    vert_mm: float = VERTICAL_MARGIN_MM,
) -> list[Slot]:
    """
    Scale (never up) so the group fits inside the min-margin frame, then translate
    so leftover space is equal on opposite edges — content sits in the page center.
    """
    if not slots:
        return []
    side = side_mm * PT_PER_MM
    vert = vert_mm * PT_PER_MM
    min_x = min(s.x for s in slots)
    min_y = min(s.y for s in slots)
    max_x = max(s.x + s.width for s in slots)
    max_y = max(s.y + s.height for s in slots)
    gw = max(max_x - min_x, 1e-6)
    gh = max(max_y - min_y, 1e-6)
    max_w = A4_WIDTH_PT - 2 * side
    max_h = A4_HEIGHT_PT - 2 * vert
    fit = min(1.0, max_w / gw, max_h / gh)
    if fit < MIN_SCALE:
        fit = MIN_SCALE

    placed: list[Slot] = []
    for s in slots:
        nw = s.width * fit
        nh = s.height * fit
        placed.append(
            Slot(
                source_index=s.source_index,
                x=(s.x - min_x) * fit,
                y=(s.y - min_y) * fit,
                width=nw,
                height=nh,
                scale=s.scale * fit,
                crop_llx=s.crop_llx,
                crop_lly=s.crop_lly,
                crop_urx=s.crop_urx,
                crop_ury=s.crop_ury,
            )
        )
    gw2 = max(s.x + s.width for s in placed) - min(s.x for s in placed)
    gh2 = max(s.y + s.height for s in placed) - min(s.y for s in placed)
    # After normalize to origin, min is 0
    ox = (A4_WIDTH_PT - gw2) / 2.0
    oy = (A4_HEIGHT_PT - gh2) / 2.0
    return [
        Slot(
            source_index=s.source_index,
            x=s.x + ox,
            y=s.y + oy,
            width=s.width,
            height=s.height,
            scale=s.scale,
            crop_llx=s.crop_llx,
            crop_lly=s.crop_lly,
            crop_urx=s.crop_urx,
            crop_ury=s.crop_ury,
        )
        for s in placed
    ]


def align_lone_slots_to_group_axis(slots: Sequence[Slot]) -> list[Slot]:
    """
    Labels that sit alone on their horizontal band (typical vertical stack) are
    snapped to the group's vertical centerline. Side-by-side pairs in a row are
    left as packed so they do not overlap.
    """
    if len(slots) <= 1:
        return list(slots)
    min_x = min(s.x for s in slots)
    max_x = max(s.x + s.width for s in slots)
    cx = (min_x + max_x) / 2.0
    out: list[Slot] = []
    for s in slots:
        alone = True
        for o in slots:
            if o.source_index == s.source_index:
                continue
            if s.y + s.height <= o.y + 1e-6 or o.y + o.height <= s.y + 1e-6:
                continue
            alone = False
            break
        if alone:
            out.append(
                Slot(
                    source_index=s.source_index,
                    x=cx - s.width / 2.0,
                    y=s.y,
                    width=s.width,
                    height=s.height,
                    scale=s.scale,
                    crop_llx=s.crop_llx,
                    crop_lly=s.crop_lly,
                    crop_urx=s.crop_urx,
                    crop_ury=s.crop_ury,
                )
            )
        else:
            out.append(s)
    return out


def finalize_slots(slots: Sequence[Slot]) -> list[Slot]:
    """Center lone stack items on one axis, then center the group on the page."""
    return center_slots_on_a4(align_lone_slots_to_group_axis(slots))


def _order_for_variant(labels: Sequence[LabelInput], variant: int) -> list[LabelInput]:
    sorted_desc = sorted(labels, key=lambda L: L.area, reverse=True)
    if len(sorted_desc) <= 1:
        return list(sorted_desc)
    base = sorted_desc[0]
    rest = list(sorted_desc[1:])
    if variant == 0:
        return [base, *rest]
    rng = random.Random(variant)
    rng.shuffle(rest)
    if (variant // len(MODES)) % 2 == 1:
        rest.reverse()
    if rest:
        rot = variant % len(rest)
        rest = rest[rot:] + rest[:rot]
    return [base, *rest]


def generate_arrangements(labels: Sequence[LabelInput]) -> list[list[Slot]]:
    """Best-first ranked list (tests / initial pick)."""
    if not labels:
        return []
    ranked: list[tuple[float, float, list[Slot]]] = []
    for variant in range(max(8, len(labels) * 2)):
        ordered = _order_for_variant(labels, variant)
        mode = MODES[variant % len(MODES)]
        found = _max_scale_for(ordered, mode)
        if not found:
            continue
        scale, slots = found
        slots = finalize_slots(slots)
        ranked.append((scale, _whitespace(slots), slots))
    ranked.sort(key=lambda t: (-t[0], t[1]))
    out: list[list[Slot]] = []
    seen_keys: set[tuple] = set()
    for _, __, slots in ranked:
        key = tuple(
            (s.source_index, round(s.x, 1), round(s.y, 1), round(s.width, 1), round(s.height, 1))
            for s in sorted(slots, key=lambda s: s.source_index)
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        out.append(slots)
    return out


def layout_for_variant(labels: Sequence[LabelInput], variant: int) -> Optional[list[Slot]]:
    """
    Unbounded deterministic layout for Regenerate.
    variant 0 = best of a short search; later indices shuffle/mode-cycle forever.
    Final result is centered on the A4 with equal leftover margins.
    """
    if not labels:
        return []
    if variant <= 0:
        best = generate_arrangements(labels)
        return best[0] if best else None

    ordered = _order_for_variant(labels, variant)
    mode = MODES[variant % len(MODES)]
    found = _max_scale_for(ordered, mode)
    if found:
        return finalize_slots(found[1])
    for m in MODES:
        found = _max_scale_for(ordered, m)
        if found:
            return finalize_slots(found[1])
    best = generate_arrangements(labels)
    return best[0] if best else None


def remap_slots_by_content_size(
    cached_slots: Sequence[Slot],
    labels: Sequence[LabelInput],
) -> Optional[list[Slot]]:
    """
    Rebind cached slot geometry to the current upload order.

    Fingerprints are order-invariant (sorted rounded content sizes), but cached
    slots are stored with the original upload ``source_index``. Re-uploading the
    same size mix in a different file order must match by content size — not by
    index — or crops are stretched into the wrong slot.
    """
    from collections import defaultdict

    from app.services.label_compose.fingerprint import box_size_mm, round_mm

    if len(cached_slots) != len(labels):
        return None

    by_size: dict[tuple[int, int], list[LabelInput]] = defaultdict(list)
    for lab in labels:
        w_mm, h_mm = box_size_mm(lab.box)
        by_size[(round_mm(w_mm), round_mm(h_mm))].append(lab)

    used: set[int] = set()
    fixed: list[Slot] = []
    for slot in cached_slots:
        cw_pt, ch_pt = slot.crop_size_pt
        if cw_pt <= 0 or ch_pt <= 0:
            return None
        key = (round_mm(cw_pt / PT_PER_MM), round_mm(ch_pt / PT_PER_MM))
        lab: Optional[LabelInput] = None
        for candidate in by_size.get(key, []):
            if candidate.source_index not in used:
                lab = candidate
                break
        if lab is None:
            return None
        used.add(lab.source_index)
        fixed.append(
            Slot(
                source_index=lab.source_index,
                x=slot.x,
                y=slot.y,
                width=slot.width,
                height=slot.height,
                scale=slot.scale,
                crop_llx=lab.box.llx,
                crop_lly=lab.box.lly,
                crop_urx=lab.box.urx,
                crop_ury=lab.box.ury,
            )
        )

    if len(fixed) != len(labels) or len(used) != len(labels):
        return None
    return fixed


def slots_from_overrides(
    labels: Sequence[LabelInput],
    override_slots: Sequence[dict],
) -> list[Slot]:
    by_idx = {L.source_index: L for L in labels}
    result: list[Slot] = []
    for d in override_slots:
        idx = int(d["source_index"])
        label = by_idx.get(idx)
        if not label:
            continue
        crop = d.get("crop") or {}
        width = float(d["width"])
        result.append(
            Slot(
                source_index=idx,
                x=float(d["x"]),
                y=float(d["y"]),
                width=width,
                height=float(d["height"]),
                scale=float(
                    d.get("scale")
                    or (width / label.width if label.width else 1.0)
                ),
                crop_llx=float(crop.get("llx", label.box.llx)),
                crop_lly=float(crop.get("lly", label.box.lly)),
                crop_urx=float(crop.get("urx", label.box.urx)),
                crop_ury=float(crop.get("ury", label.box.ury)),
            )
        )
    return result
