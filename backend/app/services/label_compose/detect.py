"""Content bounding-box detection for shipping labels."""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image

from app.services.label_compose import (
    BG_THRESHOLD,
    CONTENT_PAD_MM,
    MIN_COMPONENT_PX,
    PT_PER_MM,
    RASTER_DPI,
)


@dataclass(frozen=True)
class ContentBox:
    """Crop box in PDF page coordinates (points, origin bottom-left)."""

    llx: float
    lly: float
    urx: float
    ury: float

    @property
    def width(self) -> float:
        return max(0.0, self.urx - self.llx)

    @property
    def height(self) -> float:
        return max(0.0, self.ury - self.lly)

    @property
    def area(self) -> float:
        return self.width * self.height


def _load_rgb(image: Image.Image) -> Image.Image:
    if image.mode in ("RGBA", "LA"):
        bg = Image.new("RGB", image.size, (255, 255, 255))
        bg.paste(image, mask=image.split()[-1])
        return bg
    return image.convert("RGB")


def _ink_mask(rgb: Image.Image, threshold: int = BG_THRESHOLD) -> list[list[bool]]:
    w, h = rgb.size
    px = rgb.load()
    mask = [[False] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y][:3]
            if r <= threshold or g <= threshold or b <= threshold:
                mask[y][x] = True
    return mask


def _component_bboxes(mask: list[list[bool]], min_px: int = MIN_COMPONENT_PX) -> list[tuple[int, int, int, int]]:
    """Return list of (min_x, min_y, max_x, max_y) inclusive for components above min_px."""
    h = len(mask)
    w = len(mask[0]) if h else 0
    visited = [[False] * w for _ in range(h)]
    boxes: list[tuple[int, int, int, int]] = []

    for y0 in range(h):
        for x0 in range(w):
            if not mask[y0][x0] or visited[y0][x0]:
                continue
            stack = [(x0, y0)]
            visited[y0][x0] = True
            min_x = max_x = x0
            min_y = max_y = y0
            count = 0
            while stack:
                x, y = stack.pop()
                count += 1
                if x < min_x:
                    min_x = x
                if x > max_x:
                    max_x = x
                if y < min_y:
                    min_y = y
                if y > max_y:
                    max_y = y
                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if 0 <= nx < w and 0 <= ny < h and mask[ny][nx] and not visited[ny][nx]:
                        visited[ny][nx] = True
                        stack.append((nx, ny))
            if count >= min_px:
                boxes.append((min_x, min_y, max_x, max_y))
    return boxes


def content_box_from_rgb(
    rgb: Image.Image,
    page_width_pt: float,
    page_height_pt: float,
    *,
    pad_mm: float = CONTENT_PAD_MM,
    threshold: int = BG_THRESHOLD,
) -> ContentBox:
    """Tight content box from an RGB raster of a page, in PDF points."""
    w_px, h_px = rgb.size
    if w_px <= 0 or h_px <= 0:
        return ContentBox(0, 0, page_width_pt, page_height_pt)

    mask = _ink_mask(rgb, threshold=threshold)
    components = _component_bboxes(mask)
    if not components:
        # Empty / all white — use full page
        return ContentBox(0, 0, page_width_pt, page_height_pt)

    min_x = min(c[0] for c in components)
    min_y = min(c[1] for c in components)
    max_x = max(c[2] for c in components)
    max_y = max(c[3] for c in components)

    # Raster origin is top-left; PDF origin is bottom-left
    sx = page_width_pt / w_px
    sy = page_height_pt / h_px
    llx = min_x * sx
    urx = (max_x + 1) * sx
    ury = page_height_pt - min_y * sy
    lly = page_height_pt - (max_y + 1) * sy

    pad = pad_mm * PT_PER_MM
    llx = max(0.0, llx - pad)
    lly = max(0.0, lly - pad)
    urx = min(page_width_pt, urx + pad)
    ury = min(page_height_pt, ury + pad)
    if urx <= llx or ury <= lly:
        return ContentBox(0, 0, page_width_pt, page_height_pt)
    return ContentBox(llx, lly, urx, ury)


def rasterise_pdf_page(pdf_bytes: bytes, page_index: int = 0) -> tuple[Image.Image, float, float]:
    """Return (RGB image, page_width_pt, page_height_pt) for one PDF page."""
    from pdf2image import convert_from_bytes
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    if page_index < 0 or page_index >= len(reader.pages):
        raise ValueError(f"PDF has no page index {page_index}")
    page = reader.pages[page_index]
    mediabox = page.mediabox
    page_w = float(mediabox.width)
    page_h = float(mediabox.height)

    images = convert_from_bytes(
        pdf_bytes,
        dpi=RASTER_DPI,
        first_page=page_index + 1,
        last_page=page_index + 1,
        fmt="png",
    )
    if not images:
        raise ValueError("pdf2image returned no images")
    return _load_rgb(images[0]), page_w, page_h


def detect_content_box_pdf(pdf_bytes: bytes, page_index: int = 0) -> ContentBox:
    rgb, page_w, page_h = rasterise_pdf_page(pdf_bytes, page_index=page_index)
    return content_box_from_rgb(rgb, page_w, page_h)


def detect_content_box_png(png_bytes: bytes) -> tuple[ContentBox, bytes]:
    """
    Detect content on a PNG and return (box, single-page PDF bytes).
    PDF page size matches the image pixel size at 72 DPI (1 px = 1 pt).
    """
    rgb = _load_rgb(Image.open(io.BytesIO(png_bytes)))
    page_w, page_h = float(rgb.size[0]), float(rgb.size[1])
    box = content_box_from_rgb(rgb, page_w, page_h)
    pdf_buf = io.BytesIO()
    rgb.save(pdf_buf, format="PDF", resolution=RASTER_DPI)
    return box, pdf_buf.getvalue()


def load_input_as_pdf_and_box(
    data: bytes,
    filename: str,
    content_type: str | None = None,
) -> tuple[bytes, ContentBox]:
    """Normalise PDF or PNG upload to (pdf_bytes, content_box)."""
    name = (filename or "").lower()
    ctype = (content_type or "").lower()
    is_png = name.endswith(".png") or "png" in ctype
    is_pdf = name.endswith(".pdf") or "pdf" in ctype
    if is_png and not is_pdf:
        box, pdf_bytes = detect_content_box_png(data)
        return pdf_bytes, box
    if is_pdf or data[:4] == b"%PDF":
        return data, detect_content_box_pdf(data)
    # Try PNG then PDF
    try:
        box, pdf_bytes = detect_content_box_png(data)
        return pdf_bytes, box
    except Exception:
        return data, detect_content_box_pdf(data)
