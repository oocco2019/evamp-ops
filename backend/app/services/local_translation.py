"""
Offline German↔English translation for message display (OPUS-MT via Marian).

Model is loaded lazily on first use and unloaded after an idle period to free RAM.
Used for inbound sync, sent-message subtitles, and manual thread translate — not for
outbound German composition (that uses the AI draft path).
"""
from __future__ import annotations

import asyncio
import gc
import logging
import re
from typing import List, Optional

from langdetect import LangDetectException, detect
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_maker
from app.models.messages import Message

logger = logging.getLogger(__name__)

MODEL_ID = "Helsinki-NLP/opus-mt-de-en"
UNLOAD_IDLE_SECONDS = 300
_MAX_CHARS_PER_CHUNK = 400

_attachment_marker_re = re.compile(r"\[(?:IMAGE|DOC|PDF|TXT|Attachment)[^\]]*\]", re.I)


def strip_attachment_markers(text: str) -> str:
    """Remove synced attachment placeholders before language detect / translate."""
    cleaned = _attachment_marker_re.sub(" ", text or "")
    return re.sub(r"\s+", " ", cleaned).strip()


def detect_language(text: str) -> str:
    """ISO 639-1 code; returns 'en' when unknown or empty."""
    cleaned = strip_attachment_markers(text)
    if not cleaned:
        return "en"
    try:
        return detect(cleaned[:5000]).lower()
    except LangDetectException:
        return "en"


class _DeEnTranslator:
    """Sync Marian OPUS-MT de→en (loaded in thread pool)."""

    def __init__(self) -> None:
        self._tokenizer = None
        self._model = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        if self._model is not None:
            return
        from transformers import MarianMTModel, MarianTokenizer

        logger.info("Local translation: loading %s", MODEL_ID)
        self._tokenizer = MarianTokenizer.from_pretrained(MODEL_ID)
        self._model = MarianMTModel.from_pretrained(MODEL_ID)
        self._model.eval()
        logger.info("Local translation: model ready")

    def unload(self) -> None:
        if self._model is None:
            return
        logger.info("Local translation: unloading model")
        self._model = None
        self._tokenizer = None
        gc.collect()

    def translate_de_to_en(self, text: str) -> str:
        self.load()
        assert self._tokenizer is not None and self._model is not None
        import torch

        cleaned = text.strip()
        if not cleaned:
            return ""
        chunks: List[str] = []
        if len(cleaned) <= _MAX_CHARS_PER_CHUNK:
            chunks = [cleaned]
        else:
            # Split on paragraph boundaries, then hard-split long blocks.
            parts = re.split(r"\n\s*\n", cleaned)
            buf = ""
            for part in parts:
                p = part.strip()
                if not p:
                    continue
                if len(p) <= _MAX_CHARS_PER_CHUNK:
                    if len(buf) + len(p) + 2 <= _MAX_CHARS_PER_CHUNK:
                        buf = f"{buf}\n\n{p}".strip() if buf else p
                    else:
                        if buf:
                            chunks.append(buf)
                        buf = p
                else:
                    if buf:
                        chunks.append(buf)
                        buf = ""
                    for i in range(0, len(p), _MAX_CHARS_PER_CHUNK):
                        chunks.append(p[i : i + _MAX_CHARS_PER_CHUNK])
            if buf:
                chunks.append(buf)

        out_parts: List[str] = []
        for chunk in chunks:
            batch = self._tokenizer([chunk], return_tensors="pt", padding=True, truncation=True, max_length=512)
            with torch.no_grad():
                generated = self._model.generate(**batch, max_length=512)
            out_parts.append(self._tokenizer.decode(generated[0], skip_special_tokens=True))
        return "\n\n".join(p for p in out_parts if p.strip())


class LocalTranslationService:
    def __init__(self) -> None:
        self._translator = _DeEnTranslator()
        self._lock = asyncio.Lock()
        self._unload_task: Optional[asyncio.Task] = None

    def _cancel_unload_timer(self) -> None:
        if self._unload_task and not self._unload_task.done():
            self._unload_task.cancel()
        self._unload_task = None

    def _schedule_unload(self) -> None:
        self._cancel_unload_timer()

        async def _idle_unload() -> None:
            try:
                await asyncio.sleep(UNLOAD_IDLE_SECONDS)
                async with self._lock:
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, self._translator.unload)
            except asyncio.CancelledError:
                return

        self._unload_task = asyncio.create_task(_idle_unload())

    async def translate_de_to_en(self, text: str) -> str:
        async with self._lock:
            self._cancel_unload_timer()
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, self._translator.translate_de_to_en, text)
            self._schedule_unload()
            return result

    async def translate_message_row(self, msg: Message) -> bool:
        """Detect language and set translated_content when German. Returns True if translated."""
        if msg.translated_content:
            return False
        content = (msg.content or "").strip()
        if not content or content == "(attachment)":
            return False
        lang = detect_language(content)
        msg.detected_language = lang
        if lang != "de":
            return False
        msg.translated_content = await self.translate_de_to_en(content)
        return True


_service: Optional[LocalTranslationService] = None


def get_local_translation_service() -> LocalTranslationService:
    global _service
    if _service is None:
        _service = LocalTranslationService()
    return _service


async def _process_messages_in_session(db: AsyncSession, message_ids: List[str]) -> int:
    if not message_ids:
        return 0
    svc = get_local_translation_service()
    result = await db.execute(select(Message).where(Message.message_id.in_(message_ids)))
    rows = result.scalars().all()
    count = 0
    dirty = False
    for msg in rows:
        try:
            before_lang = msg.detected_language
            before_trans = msg.translated_content
            if await svc.translate_message_row(msg):
                count += 1
            if msg.detected_language != before_lang or msg.translated_content != before_trans:
                dirty = True
        except Exception:
            logger.exception("Local translation failed for message %s", msg.message_id)
    if dirty:
        await db.commit()
    return count


async def translate_message_ids(message_ids: List[str]) -> int:
    """Background-safe: own DB session."""
    if not message_ids:
        return 0
    async with async_session_maker() as db:
        try:
            return await _process_messages_in_session(db, message_ids)
        except Exception:
            await db.rollback()
            logger.exception("translate_message_ids failed")
            return 0


async def translate_untranslated_batch(limit: int = 250) -> int:
    """Find messages missing translated_content and attempt German de→en."""
    async with async_session_maker() as db:
        stmt = (
            select(Message.message_id)
            .where(Message.translated_content.is_(None))
            .where(Message.content.isnot(None))
            .where(Message.content != "(attachment)")
            .where(Message.content != "")
            .where(
                or_(
                    Message.detected_language.is_(None),
                    Message.detected_language == "de",
                )
            )
            .limit(limit)
        )
        result = await db.execute(stmt)
        ids = [r[0] for r in result.all()]
    return await translate_message_ids(ids)


def schedule_translate_message_ids(message_ids: List[str]) -> None:
    if not message_ids:
        return

    async def _run() -> None:
        n = await translate_message_ids(message_ids)
        if n:
            logger.info("Local translation: translated %d message(s)", n)

    asyncio.create_task(_run())


def schedule_translation_backfill(limit: int = 250) -> None:
    async def _run() -> None:
        n = await translate_untranslated_batch(limit=limit)
        if n:
            logger.info("Local translation backfill: translated %d message(s)", n)

    asyncio.create_task(_run())
