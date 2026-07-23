"""Shared constants for A4 label composition."""

# PDF points (1/72 inch)
A4_WIDTH_PT = 595.0
A4_HEIGHT_PT = 842.0

PT_PER_MM = 72.0 / 25.4

# Detection
RASTER_DPI = 72
BG_THRESHOLD = 245
MIN_COMPONENT_PX = 4
CONTENT_PAD_MM = 2.5

# Layout — equal minimum clearance on all sides (sticky tape), then center the group
SIDE_MARGIN_MM = 30.0  # 3cm
VERTICAL_MARGIN_MM = 30.0  # 3cm — match sides so leftover whitespace centers evenly
LAYOUT_FINGERPRINT_TAG = "center30axis"
INTER_LABEL_GAP_MM = 4.0
MIN_SCALE = 0.05
ROUND_MM = 2.0

# Safety valves (not product limits of 3–4)
MAX_FILES = 100
MAX_UPLOAD_BYTES = 80 * 1024 * 1024
