# Returns — multi-label A4 composer

Compose any number of shipping label PDFs/PNGs onto a single A4 sheet for printing
(Returns nav → `/returns`).

## Pipeline

1. **Detect content bbox** — Rasterise each input at 72 DPI (`pdf2image` + Poppler for PDF;
   Pillow for PNG). Treat pixels with all RGB channels above ~245 as background. Keep
   connected components larger than a few pixels; pad the tight box by ~2.5mm so barcode
   quiet zones survive.
2. **Fingerprint** — Hash the sorted tuple of content sizes rounded to 2mm. Same mix of
   sizes → same cache key regardless of upload order.
3. **Layout** — Sort by content area descending. Place the largest near the top of a fresh
   A4 (595×842pt) with a **3cm minimum margin on all sides**, then the packed
   label group is **centered** so leftover space is equal on opposite edges.
   Pack with shelf
   and column variants; downscale only when needed (never upscale). If nothing fits even
   after aggressive downscale, the API returns 422.
4. **Cache** — On a miss, persist slots + arrangement index in `label_compose_templates`.
   On a hit (arrangement index 0), reuse stored coordinates and skip fitting. Slots are
   rebound to the current upload by matching rounded content sizes (not upload index), so
   reordering the same size mix does not stretch labels into the wrong slot.
5. **Render** — Apply the detected box as a CropBox and place with pypdf
   `Transformation().scale().translate()` so PDF barcodes stay vector. PNGs are converted
   to a single-page PDF first (raster page).
6. **UI** — Preview the PDF, drag slot overlays to adjust, **Save layout** (overwrites
   cache), **Regenerate** (unbounded next packing variant), **PDF** / **PNG** download.

## Safety valves

- Max 100 files / ~80MB per request (not a product limit of “3 or 4”).
- Always one A4 page — no multi-page spill in v1.

## Ops

Backend image needs `poppler-utils` and Python packages `pypdf`, `Pillow`, `pdf2image`.
After pulling this feature:

```bash
cd /Users/marius/evamp-ops && docker compose build backend && docker compose up -d && docker compose exec -T backend alembic upgrade head
```
