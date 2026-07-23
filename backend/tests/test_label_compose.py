"""Unit tests for label compose detect / layout / fingerprint (no poppler required)."""

from app.services.label_compose.detect import ContentBox, content_box_from_rgb
from app.services.label_compose.fingerprint import fingerprint_from_boxes
from app.services.label_compose.layout import LabelInput, generate_arrangements
from PIL import Image, ImageDraw


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
