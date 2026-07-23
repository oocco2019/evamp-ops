"""Render composed A4 PDF from cropped vector (or PNG-derived) pages."""

from __future__ import annotations

import io
from typing import Sequence

from pypdf import PageObject, PdfReader, PdfWriter, Transformation
from pypdf.generic import ArrayObject, DecodedStreamObject, NameObject, RectangleObject

from app.services.label_compose import A4_HEIGHT_PT, A4_WIDTH_PT
from app.services.label_compose.layout import Slot


def _contents_bytes(page: PageObject) -> bytes:
    contents = page.get_contents()
    if contents is None:
        return b""
    if isinstance(contents, ArrayObject):
        out = b""
        for item in contents:
            out += item.get_object().get_data()
        return out
    return contents.get_object().get_data()


def _set_contents(page: PageObject, data: bytes) -> None:
    stream = DecodedStreamObject()
    stream.set_data(data)
    page[NameObject("/Contents")] = stream


def _merge_clipped(
    canvas: PageObject,
    page: PageObject,
    transformation: Transformation,
    x: float,
    y: float,
    w: float,
    h: float,
) -> None:
    """
    Merge a source page onto canvas, clipped to the destination slot.

    Setting CropBox alone does not clip during merge_transformed_page — without an
    explicit clip, full-page carrier PDFs paint into the side margins.
    """
    before = _contents_bytes(canvas)
    clip = (
        f"\nq\n{x:.4f} {y:.4f} {w:.4f} {h:.4f} re\nW\nn\n".encode("ascii")
    )
    _set_contents(canvas, before + clip)
    canvas.merge_transformed_page(page, transformation, expand=False)
    after = _contents_bytes(canvas)
    _set_contents(canvas, after + b"\nQ\n")


def render_a4(pdf_bytes_by_source: dict[int, bytes], slots: Sequence[Slot]) -> bytes:
    """
    Place each source page's content region onto a blank A4 using
    scale + translate, clipped to the slot. Barcodes remain vector for PDF inputs.
    """
    canvas = PageObject.create_blank_page(width=A4_WIDTH_PT, height=A4_HEIGHT_PT)

    for slot in slots:
        raw = pdf_bytes_by_source.get(slot.source_index)
        if not raw:
            continue
        reader = PdfReader(io.BytesIO(raw))
        if not reader.pages:
            continue
        page = reader.pages[0]
        llx, lly, urx, ury = (
            slot.crop_llx,
            slot.crop_lly,
            slot.crop_urx,
            slot.crop_ury,
        )
        crop = RectangleObject([llx, lly, urx, ury])
        page.cropbox = crop
        page.mediabox = crop
        try:
            page.trimbox = crop
        except Exception:
            pass

        cw = max(urx - llx, 1e-6)
        ch = max(ury - lly, 1e-6)
        sx = slot.width / cw
        sy = slot.height / ch
        # Map crop lower-left → slot lower-left
        transformation = (
            Transformation()
            .translate(-llx, -lly)
            .scale(sx, sy)
            .translate(slot.x, slot.y)
        )
        _merge_clipped(
            canvas,
            page,
            transformation,
            slot.x,
            slot.y,
            slot.width,
            slot.height,
        )

    writer = PdfWriter()
    writer.add_page(canvas)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def preview_png_base64(pdf_bytes: bytes, dpi: int = 120) -> str:
    """Rasterise composed A4 for UI preview (avoids browser PDF viewer chrome)."""
    import base64

    from pdf2image import convert_from_bytes

    images = convert_from_bytes(
        pdf_bytes, dpi=dpi, first_page=1, last_page=1, fmt="png"
    )
    if not images:
        raise ValueError("preview rasterisation failed")
    buf = io.BytesIO()
    images[0].save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")
