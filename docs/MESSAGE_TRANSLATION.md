# Message translation (German ↔ English)

EvampOps stores English subtitles for German buyer/seller messages in PostgreSQL (`messages.translated_content`, `messages.detected_language`). Translations are **local** (no LLM) for display; outbound German **composition** still uses the AI draft stack.

## Architecture

| Path | Engine | When |
|------|--------|------|
| Inbound display (de→en) | `Helsinki-NLP/opus-mt-de-en` via Marian + `langdetect` | Sync backfill, Translate Thread, send (seller DE→en subtitle) |
| Outbound German reply | AI translate (`POST /api/messages/threads/{id}/draft-german`) | **DE** button — translates **reply box text only** (ignores Instructions for AI, global/SKU rules, thread history) |
| Single-text LLM translate | Legacy `POST /api/messages/translate` | Not used by thread translate-all |

Implementation: `backend/app/services/local_translation.py`.

The Marian model loads **lazily** on first use (~300MB from HuggingFace on cold start) and unloads after **5 minutes** idle to free RAM.

## Automatic translation

After message sync completes, the backend schedules `schedule_translation_backfill()` — batches of up to 250 messages missing `translated_content` where `detected_language` is null or `de`.

When a seller sends a reply detected as German, the same service stores an English `translated_content` on that outbound row.

Empty body and `(attachment)`-only rows are skipped (no infinite retry).

## DE button vs Generate draft

| Control | Uses Instructions for AI? | Uses thread / global rules? | Output |
|---------|---------------------------|-----------------------------|--------|
| **Generate draft** | Yes | Yes | New English (or mixed) draft from full context |
| **DE** | No | No | German translation of **reply box text only** |

If Instructions for AI say “write in English”, **Generate draft** follows that. **DE** ignores it so you can translate an English draft before sending to a German buyer.

---

## Manual: Translate Thread

`POST /api/messages/threads/{thread_id}/translate-all` runs the local engine on every message in the thread that lacks `translated_content`. Already-translated rows are skipped.

## One-off backfill (existing DB)

If messages were imported before this feature, run once:

```bash
docker compose exec backend python scripts/backfill_message_translations.py
```

Script: `backend/scripts/backfill_message_translations.py`. Processes all eligible messages in batches of 100; safe to re-run (skips rows that already have `translated_content`).

## Docker / dependencies

- Python deps: `langdetect`, `transformers`, `sentencepiece`, `sacremoses` in `backend/requirements.txt`.
- **PyTorch CPU** is installed in `backend/Dockerfile`, not `requirements.txt`: `torch==2.4.1+cpu` has no wheel on **Apple Silicon (aarch64)**; the image uses `torch==2.6.0+cpu` from the PyTorch CPU index.

Rebuild after dependency changes:

```bash
docker compose build backend && docker compose up -d backend
```

## Tests

```bash
docker compose exec backend pytest tests/test_local_translation.py -q
```

Covers language detection helpers and attachment-marker stripping (`strip_attachment_markers`, `detect_language`).

## Data retention

Translations are persisted on the message row and are not pruned. See [DATA_RETENTION.md](DATA_RETENTION.md).
