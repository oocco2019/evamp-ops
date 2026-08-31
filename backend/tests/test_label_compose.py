"""Unit tests for label compose detect / layout / fingerprint (no poppler required)."""

import io

from app.services.label_compose.detect import (
    ContentBox,
    content_box_from_rgb,
    load_input_as_pdf_and_box,
    normalize_pdf_for_compose,
)
from app.services.label_compose.fingerprint import fingerprint_from_boxes
from app.services.label_compose.layout import LabelInput, Slot, generate_arrangements
from app.services.label_compose.render import render_a4
from PIL import Image, ImageDraw
from pypdf import PageObject, PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject, NumberObject, RectangleObject


def _box(w: float, h: float, x: float = 0, y: float = 0) -> ContentBox:
    return ContentBox(x, y, x + w, y + h)


def test_content_box_ignores_white_margins():
    img = Image.new("RGB", (200, 300), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 30, 120, 130], fill=(0, 0, 0))
    box = content_box_from_rgb(img, 200, 300, pad_mm=0)
    assert box.width < 150
    assert box.height < 150
    assert box.llx < 40
    assert box.ury > 150  # near top of page in PDF coords


def test_fingerprint_stable_under_reorder():
    a = _box(100, 50)
    b = _box(40, 40)
    c = _box(200, 80)
    f1 = fingerprint_from_boxes([a, b, c])
    f2 = fingerprint_from_boxes([c, a, b])
    assert f1 == f2


def test_packer_fits_many_tiny_equal_boxes():
    labels = [
        LabelInput(source_index=i, box=_box(40, 30))
        for i in range(20)
    ]
    arrangements = generate_arrangements(labels)
    assert arrangements, "expected at least one packing"
    slots = arrangements[0]
    assert len(slots) == 20
    for s in slots:
        assert s.scale <= 1.0 + 1e-6
        assert s.x >= 0
        assert s.y >= 0
        assert s.x + s.width <= 595 + 1e-3
        assert s.y + s.height <= 842 + 1e-3


def test_packer_two_large_boxes_no_upscale():
    labels = [
        LabelInput(source_index=0, box=_box(400, 300)),
        LabelInput(source_index=1, box=_box(400, 280)),
    ]
    arrangements = generate_arrangements(labels)
    assert arrangements
    for slot in arrangements[0]:
        assert slot.scale <= 1.0 + 1e-6


def test_packer_respects_side_margins():
    from app.services.label_compose import PT_PER_MM, SIDE_MARGIN_MM, VERTICAL_MARGIN_MM

    labels = [LabelInput(source_index=i, box=_box(40, 30)) for i in range(8)]
    arrangements = generate_arrangements(labels)
    assert arrangements
    side = SIDE_MARGIN_MM * PT_PER_MM
    vert = VERTICAL_MARGIN_MM * PT_PER_MM
    for s in arrangements[0]:
        assert s.x >= side - 1e-3
        assert s.x + s.width <= 595 - side + 1e-3
        assert s.y >= vert - 1e-3
        assert s.y + s.height <= 842 - vert + 1e-3


def test_layout_group_is_centered():
    """Leftover space on opposite edges should match (centered cluster)."""
    labels = [
        LabelInput(source_index=0, box=_box(200, 100)),
        LabelInput(source_index=1, box=_box(80, 40)),
        LabelInput(source_index=2, box=_box(80, 40)),
    ]
    arrangements = generate_arrangements(labels)
    assert arrangements
    slots = arrangements[0]
    min_x = min(s.x for s in slots)
    max_x = max(s.x + s.width for s in slots)
    min_y = min(s.y for s in slots)
    max_y = max(s.y + s.height for s in slots)
    assert abs(min_x - (595 - max_x)) < 1.0
    assert abs(min_y - (842 - max_y)) < 1.0


def test_stacked_labels_share_vertical_centerline():
    """Narrow labels under a wide one should sit on the same center axis."""
    # Wide enough that they cannot sit side-by-side in the printable width.
    labels = [
        LabelInput(source_index=0, box=_box(400, 120)),
        LabelInput(source_index=1, box=_box(280, 60)),
        LabelInput(source_index=2, box=_box(200, 40)),
    ]
    arrangements = generate_arrangements(labels)
    assert arrangements
    centers = [s.x + s.width / 2 for s in arrangements[0]]
    assert max(centers) - min(centers) < 2.0


def test_single_label_arrangement():
    labels = [LabelInput(source_index=0, box=_box(300, 200))]
    arrangements = generate_arrangements(labels)
    assert len(arrangements) >= 1
    assert len(arrangements[0]) == 1
    s = arrangements[0][0]
    # Single label centered on the page
    assert abs(s.x - (595 - s.width) / 2) < 1.0
    assert abs(s.y - (842 - s.height) / 2) < 1.0


def _make_ink_pdf(
    *,
    rotate: int = 0,
    mediabox: list[float] | None = None,
    content_rect: tuple[float, float, float, float] | None = None,
) -> bytes:
    """Minimal carrier-like PDF: black rect on an otherwise blank page."""
    if mediabox is None:
        mediabox = [0.0, 0.0, 200.0, 100.0]
    llx, lly, urx, ury = mediabox
    width, height = urx - llx, ury - lly
    if content_rect is None:
        content_rect = (llx + 20, lly + 20, llx + 120, lly + 70)
    cx0, cy0, cx1, cy1 = content_rect
    stream = DecodedStreamObject()
    stream.set_data(
        f"q\n0 0 0 rg\n{cx0} {cy0} {cx1 - cx0} {cy1 - cy0} re\nf\nQ\n".encode()
    )
    page = PageObject.create_blank_page(width=width, height=height)
    page.mediabox = RectangleObject(mediabox)
    page[NameObject("/Contents")] = stream
    if rotate:
        page[NameObject("/Rotate")] = NumberObject(rotate)
    writer = PdfWriter()
    writer.add_page(page)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _composed_ink_ratio(pdf_bytes: bytes) -> float:
    from pdf2image import convert_from_bytes

    pdf_norm, box = load_input_as_pdf_and_box(pdf_bytes, "label.pdf", "application/pdf")
    slot = Slot(
        source_index=0,
        x=50,
        y=50,
        width=box.width,
        height=box.height,
        scale=1.0,
        crop_llx=box.llx,
        crop_lly=box.lly,
        crop_urx=box.urx,
        crop_ury=box.ury,
    )
    out = render_a4({0: pdf_norm}, [slot])
    img = convert_from_bytes(out, dpi=72, first_page=1, last_page=1)[0].convert("RGB")
    # getdata() is deprecated in Pillow 14; flatten via tobytes + frombytes-sized walk.
    raw = img.tobytes()
    nonwhite = 0
    total = img.size[0] * img.size[1]
    for i in range(0, len(raw), 3):
        if raw[i] < 250 or raw[i + 1] < 250 or raw[i + 2] < 250:
            nonwhite += 1
    return nonwhite / total


def test_normalize_clears_page_rotate():
    raw = _make_ink_pdf(rotate=90)
    assert int(PdfReader(io.BytesIO(raw)).pages[0].get("/Rotate") or 0) == 90
    normalized = normalize_pdf_for_compose(raw)
    page = PdfReader(io.BytesIO(normalized)).pages[0]
    assert int(page.get("/Rotate") or 0) % 360 == 0
    # Visual page after 90° is portrait relative to the original landscape MediaBox.
    assert float(page.mediabox.width) == 100.0
    assert float(page.mediabox.height) == 200.0


def test_normalize_shifts_nonzero_mediabox_origin():
    raw = _make_ink_pdf(
        mediabox=[1000.0, 2000.0, 1200.0, 2100.0],
        content_rect=(1020.0, 2020.0, 1120.0, 2070.0),
    )
    mb = PdfReader(io.BytesIO(raw)).pages[0].mediabox
    assert float(mb.left) == 1000.0
    normalized = normalize_pdf_for_compose(raw)
    page = PdfReader(io.BytesIO(normalized)).pages[0]
    assert abs(float(page.mediabox.left)) < 1e-6
    assert abs(float(page.mediabox.bottom)) < 1e-6
    assert float(page.mediabox.width) == 200.0
    assert float(page.mediabox.height) == 100.0


def test_compose_preserves_ink_for_rotated_carrier_pdf():
    baseline = _composed_ink_ratio(_make_ink_pdf(rotate=0))
    assert baseline > 0.005
    for rotate in (90, 180, 270):
        ratio = _composed_ink_ratio(_make_ink_pdf(rotate=rotate))
        assert ratio > baseline * 0.85, f"rotate={rotate} lost ink ({ratio} vs {baseline})"


def test_compose_preserves_ink_for_nonzero_mediabox_origin():
    baseline = _composed_ink_ratio(_make_ink_pdf(rotate=0))
    ratio = _composed_ink_ratio(
        _make_ink_pdf(
            mediabox=[1000.0, 2000.0, 1200.0, 2100.0],
            content_rect=(1020.0, 2020.0, 1120.0, 2070.0),
        )
    )
    assert ratio > baseline * 0.85, f"nonzero MediaBox origin blanked label ({ratio})"
