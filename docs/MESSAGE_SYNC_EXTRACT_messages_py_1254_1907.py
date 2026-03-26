# Extracted from backend/app/api/messages.py lines 1254-1907
# DO NOT EDIT BY HAND — regenerate with: sed -n "1254,1907p" backend/app/api/messages.py

@router.post("/sync")
async def sync_messages(
    db: AsyncSession = Depends(get_db),
    full: bool = Query(False, description="If true, fetch all member conversations (no start_time filter) to backfill older threads; messages are always retained indefinitely."),
):
    """
    Sync messages from eBay Message API (commerce/message). All synced messages are stored
    in the DB and retained indefinitely (no purge) for warranty and history. Incremental:
    only fetches conversations with activity since last sync unless full=1. Only one sync
    runs at a time; concurrent calls receive 503.
    """
    global _sync_in_progress
    if _sync_lock.locked():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sync already in progress.",
        )
    async with _sync_lock:
        _sync_in_progress = True
        try:
            return await _do_sync_messages(db, full_sync=full)
        finally:
            _sync_in_progress = False


async def _sync_from_members_full(
    db: AsyncSession,
    access_token: str,
    limit: int,
    seller_username: str,
) -> tuple[int, int]:
    """Run FROM_MEMBERS full sync (no start_time): paginate all conversations, fetch messages, upsert. Returns (threads_added, messages_added). Commits once at end."""
    threads_added = 0
    messages_added = 0
    messages_with_media: List[tuple] = []
    offset = 0
    while True:
        try:
            conv_page = await fetch_message_conversations_page(
                access_token,
                conversation_type="FROM_MEMBERS",
                start_time=None,
                limit=limit,
                offset=offset,
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="eBay denied access to messages. Reconnect eBay in Settings so the app requests the message scope (commerce.message).",
                ) from e
            raise
        conversations = conv_page.get("conversations") or []
        if not conversations:
            break
        sem = asyncio.Semaphore(10)

        async def fetch_messages_full(cid: str):
            async with sem:
                return await fetch_all_conversation_messages(
                    access_token, cid, conversation_type="FROM_MEMBERS"
                )

        conv_ids = [c.get("conversationId") for c in conversations if c.get("conversationId")]
        msg_results = await asyncio.gather(
            *[fetch_messages_full(cid) for cid in conv_ids],
            return_exceptions=True,
        )
        id_to_msgs = dict(zip(conv_ids, msg_results))
        page_msg_ids = []
        for cid in conv_ids:
            msgs_result = id_to_msgs.get(cid)
            if isinstance(msgs_result, BaseException):
                continue
            for m in msgs_result or []:
                mid = m.get("messageId")
                if mid:
                    page_msg_ids.append(mid)
        existing_by_id = {}
        if page_msg_ids:
            existing_result = await db.execute(select(Message).where(Message.message_id.in_(page_msg_ids)))
            for msg_row in existing_result.scalars().all():
                existing_by_id[msg_row.message_id] = msg_row
        for conv in conversations:
            conversation_id = conv.get("conversationId")
            if not conversation_id:
                continue
            msgs_result = id_to_msgs.get(conversation_id)
            if isinstance(msgs_result, BaseException):
                logger.warning("Messages fetch failed for %s: %s", conversation_id, msgs_result)
                continue
            msgs = msgs_result
            ref_id = conv.get("referenceId")
            ref_type = conv.get("referenceType")
            created_date = _parse_iso_to_naive_utc(conv.get("createdDate"))
            buyer_name = _buyer_username_from_conversation(conv, seller_username)
            if _is_seller_username(buyer_name):
                buyer_name = None
            thread = await db.get(MessageThread, conversation_id)
            if not thread:
                thread = MessageThread(
                    thread_id=conversation_id,
                    buyer_username=buyer_name,
                    ebay_item_id=ref_id if ref_type == "LISTING" else None,
                    ebay_order_id=None,
                    sku=None,
                    created_at=created_date or datetime.utcnow(),
                )
                db.add(thread)
                await db.flush()
                threads_added += 1
            else:
                if not thread.buyer_username and buyer_name:
                    thread.buyer_username = buyer_name
            for m in msgs:
                try:
                    msg_id = m.get("messageId")
                    if not msg_id:
                        continue
                    existing = existing_by_id.get(msg_id)
                    sender_raw = (m.get("senderUsername") or "").strip()
                    sender_type = _member_message_sender_type(
                        m.get("senderUsername"), m.get("recipientUsername"), seller_username
                    )
                    display_username = _member_message_display_username(
                        sender_type, sender_raw, buyer_name
                    )
                    if existing:
                        existing.is_read = bool(m.get("readStatus", False))
                        media_list = _normalize_message_media(m.get("messageMedia") or [])
                        existing.media = media_list if media_list else None
                        existing.sender_type = sender_type
                        existing.sender_username = display_username
                        if media_list:
                            messages_with_media.append((msg_id, media_list))
                        continue
                    body = m.get("messageBody") or ""
                    media = m.get("messageMedia") or []
                    media_list = _normalize_message_media(media)
                    if media:
                        attachment_strs = []
                        for i, x in enumerate(media):
                            if isinstance(x, dict):
                                name = x.get("mediaName") or x.get("name") or f"file_{i+1}"
                                mtype = x.get("mediaType") or x.get("type") or "FILE"
                                attachment_strs.append(f"[{mtype}: {name}]")
                            else:
                                attachment_strs.append(f"[Attachment {i+1}]")
                        if attachment_strs:
                            body = body + "\n" + " ".join(attachment_strs) if body else " ".join(attachment_strs)
                    ebay_created = _parse_iso_to_naive_utc(m.get("createdDate")) or datetime.utcnow()
                    new_msg = Message(
                        message_id=msg_id,
                        thread_id=conversation_id,
                        sender_type=sender_type,
                        sender_username=display_username,
                        subject=(m.get("subject") or "").strip() or None,
                        content=body,
                        media=media_list if media_list else None,
                        is_read=bool(m.get("readStatus", False)),
                        ebay_created_at=ebay_created,
                    )
                    db.add(new_msg)
                    messages_added += 1
                    if media_list:
                        messages_with_media.append((msg_id, media_list))
                except Exception as e:
                    logger.warning("Sync: skip message in conversation %s (msg %s): %s", conversation_id, m.get("messageId"), e)
            if msgs:
                last_msg = max(msgs, key=lambda m: m.get("createdDate") or "")
                thread.last_message_at = _parse_iso_to_naive_utc(last_msg.get("createdDate"))
                body_preview = (last_msg.get("messageBody") or "").strip()
                thread.last_message_preview = (body_preview[:500] + "…") if len(body_preview) > 500 else (body_preview or None)
                thread.message_count = len(msgs)
                thread.unread_count = sum(1 for m in msgs if not m.get("readStatus", False))
        total = conv_page.get("total") or 0
        offset += limit
        if offset >= total or not conv_page.get("next"):
            break
    await db.commit()
    for mid, mlist in messages_with_media:
        await _store_message_media_blobs(db, mid, mlist)
    return (threads_added, messages_added)


async def _do_sync_messages(db: AsyncSession, full_sync: bool = False):
    """Inner sync logic; called with _sync_lock held. Messages are never purged; only stub-* threads are removed."""
    logger.info("=" * 80)
    logger.info("Messages sync: start (full_sync=%s)", full_sync)
    logger.info("=" * 80)
    from sqlalchemy import delete

    try:
        await db.execute(delete(Message).where(Message.thread_id.like("stub-%")))
        await db.execute(delete(MessageThread).where(MessageThread.thread_id.like("stub-%")))
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.exception("Messages sync: DB error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {e!s}. Run migrations.",
        )

    try:
        access_token = await get_ebay_access_token(db)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Messages sync: token error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get eBay token: {e!s}",
        )

    seller_username = (settings.EBAY_SELLER_USERNAME or "").strip().lower()
    sync_start_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    threads_synced = 0
    messages_synced = 0
    limit = 50
    sync_summary: dict[str, Any] = {"full_sync": full_sync}
    ran_full_sync = full_sync
    need_periodic_full = False
    try:
        if not full_sync:
            full_meta_result = await db.execute(
                select(SyncMetadata).where(SyncMetadata.key == "messages_last_full_sync_at")
            )
            full_meta = full_meta_result.scalar_one_or_none()
            last_full_at: Optional[datetime] = None
            if full_meta and full_meta.value:
                try:
                    last_full_at = datetime.fromisoformat(full_meta.value.replace("Z", "+00:00"))
                except ValueError:
                    pass
            need_periodic_full = last_full_at is None or (datetime.now(timezone.utc) - last_full_at) > timedelta(minutes=10)
            if need_periodic_full:
                logger.info("Messages sync: periodic full due (last full > 10 min), will run after incremental")

        if full_sync:
            logger.info("Messages sync: full_sync=True, FROM_MEMBERS only (no start_time)")
            t, m = await _sync_from_members_full(db, access_token, limit, seller_username)
            threads_synced += t
            messages_synced += m
        else:
            # Incremental: start_time from last sync; FROM_MEMBERS only (eBay getConversations supports only FROM_MEMBERS and FROM_EBAY).
            # With start_time, eBay returns only conversations with buyer activity since that time; seller-only replies are not included.
            member_sync_result = await db.execute(
                select(SyncMetadata).where(SyncMetadata.key == "messages_member_last_sync_at")
            )
            member_sync_meta = member_sync_result.scalar_one_or_none()
            start_time = member_sync_meta.value if (member_sync_meta and member_sync_meta.value) else None
            logger.info("Messages sync: incremental start_time=%r", start_time)

            if not start_time:
                logger.info("Messages sync: incremental but no start_time (first run), doing full FROM_MEMBERS to establish baseline")
                member_convs = await fetch_all_conversations(
                    access_token, "FROM_MEMBERS", start_time=None, limit=limit
                )
                logger.info("Incremental first-run: fetched %d FROM_MEMBERS conversations", len(member_convs))
            else:
                member_convs = await fetch_all_conversations(
                    access_token, "FROM_MEMBERS", start_time=start_time, limit=limit
                )
                logger.info("Incremental: FROM_MEMBERS returned %d conversations since start_time", len(member_convs))

            all_convs = {c.get("conversationId"): c for c in member_convs if c.get("conversationId")}
            fetch_list: List[tuple[str, str]] = [(cid, "FROM_MEMBERS") for cid in all_convs]
            sync_summary["start_time"] = start_time or "(none)"
            sync_summary["from_members"] = len(member_convs)
            sync_summary["fetch_list"] = len(fetch_list)
            if not fetch_list:
                logger.info("Incremental: 0 conversations with activity since start_time")
                logger.info("Incremental summary: start_time=%s, FROM_MEMBERS=%d, fetch_list=0", start_time or "(none)", len(member_convs))
                await db.commit()
            else:
                sem = asyncio.Semaphore(10)

                async def fetch_messages_for_cid_type(item: tuple[str, str]):
                    cid, ctype = item
                    async with sem:
                        return await fetch_all_conversation_messages(
                            access_token, cid, conversation_type=ctype
                        )

                msg_results = await asyncio.gather(
                    *[fetch_messages_for_cid_type(item) for item in fetch_list],
                    return_exceptions=True,
                )
                id_type_to_msgs = dict(zip(fetch_list, msg_results))
                id_to_msgs_merged: dict[str, list] = {}
                for (cid, ctype), result in id_type_to_msgs.items():
                    if isinstance(result, BaseException):
                        logger.warning("Messages fetch failed for %s (%s): %s", cid, ctype, result)
                        continue
                    seen_ids = {m.get("messageId") for m in id_to_msgs_merged.get(cid, [])}
                    for m in result or []:
                        mid = m.get("messageId")
                        if mid and mid not in seen_ids:
                            seen_ids.add(mid)
                            id_to_msgs_merged.setdefault(cid, []).append(m)
                for cid, msgs in id_to_msgs_merged.items():
                    msgs.sort(key=lambda x: x.get("createdDate") or "")

                page_msg_ids = []
                for msgs in id_to_msgs_merged.values():
                    for m in msgs:
                        mid = m.get("messageId")
                        if mid:
                            page_msg_ids.append(mid)
                existing_by_id = {}
                if page_msg_ids:
                    existing_result = await db.execute(select(Message).where(Message.message_id.in_(page_msg_ids)))
                    for msg_row in existing_result.scalars().all():
                        existing_by_id[msg_row.message_id] = msg_row

                incr_messages_with_media: List[tuple] = []
                for cid, conv in all_convs.items():
                    msgs = id_to_msgs_merged.get(cid, [])
                    ref_id = conv.get("referenceId")
                    ref_type = conv.get("referenceType")
                    created_date = _parse_iso_to_naive_utc(conv.get("createdDate"))
                    buyer_name = _buyer_username_from_conversation(conv, seller_username)
                    if _is_seller_username(buyer_name):
                        buyer_name = None
                    thread = await db.get(MessageThread, cid)
                    if not thread:
                        thread = MessageThread(
                            thread_id=cid,
                            buyer_username=buyer_name,
                            ebay_item_id=ref_id if ref_type == "LISTING" else None,
                            ebay_order_id=None,
                            sku=None,
                            created_at=created_date or datetime.utcnow(),
                        )
                        db.add(thread)
                        await db.flush()
                        threads_synced += 1
                    else:
                        if not thread.buyer_username and buyer_name:
                            thread.buyer_username = buyer_name
                    for m in msgs:
                        msg_id = m.get("messageId")
                        if not msg_id:
                            continue
                        existing = existing_by_id.get(msg_id)
                        sender_raw = (m.get("senderUsername") or "").strip()
                        sender_type = _member_message_sender_type(
                            m.get("senderUsername"), m.get("recipientUsername"), seller_username
                        )
                        display_username = _member_message_display_username(
                            sender_type, sender_raw, buyer_name
                        )
                        if existing:
                            existing.is_read = bool(m.get("readStatus", False))
                            media_list = _normalize_message_media(m.get("messageMedia") or [])
                            existing.media = media_list if media_list else None
                            existing.sender_type = sender_type
                            existing.sender_username = display_username
                            if media_list:
                                incr_messages_with_media.append((msg_id, media_list))
                            continue
                        body = m.get("messageBody") or ""
                        media = m.get("messageMedia") or []
                        media_list = _normalize_message_media(media)
                        if media:
                            attachment_strs = []
                            for i, x in enumerate(media):
                                if isinstance(x, dict):
                                    name = x.get("mediaName") or x.get("name") or f"file_{i+1}"
                                    mtype = x.get("mediaType") or x.get("type") or "FILE"
                                    attachment_strs.append(f"[{mtype}: {name}]")
                                else:
                                    attachment_strs.append(f"[Attachment {i+1}]")
                            if attachment_strs:
                                body = body + "\n" + " ".join(attachment_strs) if body else " ".join(attachment_strs)
                        ebay_created = _parse_iso_to_naive_utc(m.get("createdDate")) or datetime.utcnow()
                        new_msg = Message(
                            message_id=msg_id,
                            thread_id=cid,
                            sender_type=sender_type,
                            sender_username=display_username,
                            subject=(m.get("subject") or "").strip() or None,
                            content=body,
                            media=media_list if media_list else None,
                            is_read=bool(m.get("readStatus", False)),
                            ebay_created_at=ebay_created,
                        )
                        db.add(new_msg)
                        messages_synced += 1
                        if media_list:
                            incr_messages_with_media.append((msg_id, media_list))
                    if msgs:
                        last_msg = max(msgs, key=lambda x: x.get("createdDate") or "")
                        thread.last_message_at = _parse_iso_to_naive_utc(last_msg.get("createdDate"))
                        body_preview = (last_msg.get("messageBody") or "").strip()
                        thread.last_message_preview = (body_preview[:500] + "…") if len(body_preview) > 500 else (body_preview or None)
                        thread.message_count = len(msgs)
                        thread.unread_count = sum(1 for x in msgs if not x.get("readStatus", False))
                logger.info(
                    "Incremental summary: start_time=%s, FROM_MEMBERS=%d, fetch_list=%d",
                    start_time or "(none)",
                    len(member_convs),
                    len(fetch_list),
                )
                logger.info(
                    "Incremental done: convs=%d threads_synced=%d messages_synced=%d",
                    len(all_convs),
                    threads_synced,
                    messages_synced,
                )
                await db.commit()
                for mid, mlist in incr_messages_with_media:
                    await _store_message_media_blobs(db, mid, mlist)

            if need_periodic_full:
                logger.info("Messages sync: running periodic full (FROM_MEMBERS, no start_time)")
                t, m = await _sync_from_members_full(db, access_token, limit, seller_username)
                threads_synced += t
                messages_synced += m
                ran_full_sync = True

        # Sync FROM_EBAY (eBay system messages: returns, cases, promotions)
        # HTML content is stripped to plain text to reduce size
        # Commits after each page so progress is saved even if timeout occurs
        # Tracks offset to enable progressive historical sync across multiple runs
        ebay_threads_synced = 0
        ebay_messages_synced = 0
        
        # Load saved offset for progressive historical sync
        ebay_offset_result = await db.execute(
            select(SyncMetadata).where(SyncMetadata.key == "ebay_messages_offset")
        )
        ebay_offset_meta = ebay_offset_result.scalar_one_or_none()
        offset = int(ebay_offset_meta.value) if ebay_offset_meta else 0
        # Normal sync: 1 page per run so sync finishes quickly; full_sync: more pages to backfill
        max_pages = 5 if full_sync else 1
        pages_fetched = 0
        reached_end = False
        try:
            while pages_fetched < max_pages:
                conv_page = await fetch_message_conversations_page(
                    access_token,
                    conversation_type="FROM_EBAY",
                    limit=limit,
                    offset=offset,
                )
                pages_fetched += 1
                conversations = conv_page.get("conversations") or []
                if not conversations:
                    break
                ebay_sem = asyncio.Semaphore(10)

                async def fetch_ebay_messages(cid: str):
                    async with ebay_sem:
                        return await fetch_all_conversation_messages(
                            access_token, cid, conversation_type="FROM_EBAY"
                        )

                conv_ids = [c.get("conversationId") for c in conversations if c.get("conversationId")]
                ebay_msg_results = await asyncio.gather(
                    *[fetch_ebay_messages(cid) for cid in conv_ids],
                    return_exceptions=True,
                )
                id_to_ebay_msgs = dict(zip(conv_ids, ebay_msg_results))

                # Batch-load existing message IDs for this page
                page_msg_ids = []
                for cid in conv_ids:
                    msgs_result = id_to_ebay_msgs.get(cid)
                    if isinstance(msgs_result, BaseException):
                        continue
                    for m in msgs_result or []:
                        mid = m.get("messageId")
                        if mid:
                            page_msg_ids.append(mid)
                existing_ebay_by_id = {}
                if page_msg_ids:
                    existing_ebay_result = await db.execute(select(Message).where(Message.message_id.in_(page_msg_ids)))
                    for msg_row in existing_ebay_result.scalars().all():
                        existing_ebay_by_id[msg_row.message_id] = msg_row

                page_threads = 0
                page_messages = 0
                ebay_page_messages_with_media: List[tuple] = []
                for conv in conversations:
                    conversation_id = conv.get("conversationId")
                    if not conversation_id:
                        continue
                    msgs_result = id_to_ebay_msgs.get(conversation_id)
                    if isinstance(msgs_result, BaseException):
                        logger.warning("FROM_EBAY messages fetch failed for %s: %s", conversation_id, msgs_result)
                        continue
                    msgs = msgs_result
                    thread = await db.get(MessageThread, conversation_id)
                    if not thread:
                        ref_id = conv.get("referenceId")
                        ref_type = conv.get("referenceType")
                        created_date = _parse_iso_to_naive_utc(conv.get("createdDate"))
                        thread = MessageThread(
                            thread_id=conversation_id,
                            buyer_username="eBay",
                            ebay_item_id=ref_id if ref_type == "LISTING" else None,
                            ebay_order_id=ref_id if ref_type == "ORDER" else None,
                            sku=None,
                            created_at=created_date or datetime.utcnow(),
                        )
                        db.add(thread)
                        await db.flush()
                        page_threads += 1
                    for m in msgs:
                        msg_id = m.get("messageId")
                        if not msg_id:
                            continue
                        existing = existing_ebay_by_id.get(msg_id)
                        if existing:
                            existing.is_read = bool(m.get("readStatus", False))
                            media_list = _normalize_message_media(m.get("messageMedia") or [])
                            existing.media = media_list if media_list else None
                            if media_list:
                                ebay_page_messages_with_media.append((msg_id, media_list))
                            continue
                        raw_body = m.get("messageBody") or ""
                        body = _strip_html_to_text(raw_body) if "<" in raw_body else raw_body
                        media = m.get("messageMedia") or []
                        media_list = _normalize_message_media(media)
                        sender = (m.get("senderUsername") or "eBay").strip()
                        subject = (m.get("subject") or "").strip() or None
                        ebay_created = _parse_iso_to_naive_utc(m.get("createdDate")) or datetime.utcnow()
                        new_msg = Message(
                            message_id=msg_id,
                            thread_id=conversation_id,
                            sender_type="ebay",
                            sender_username=sender,
                            subject=subject,
                            content=body,
                            media=media_list if media_list else None,
                            is_read=bool(m.get("readStatus", False)),
                            ebay_created_at=ebay_created,
                        )
                        db.add(new_msg)
                        page_messages += 1
                        if media_list:
                            ebay_page_messages_with_media.append((msg_id, media_list))
                    if msgs:
                        last_m = max(msgs, key=lambda x: x.get("createdDate") or "")
                        thread.last_message_at = _parse_iso_to_naive_utc(last_m.get("createdDate"))
                        body_preview = (last_m.get("messageBody") or "").strip()
                        thread.last_message_preview = (_strip_html_to_text(body_preview)[:497] + "…") if len(body_preview) > 500 else (_strip_html_to_text(body_preview) if "<" in body_preview else body_preview or None)
                        thread.message_count = len(msgs)
                        thread.unread_count = sum(1 for x in msgs if not x.get("readStatus", False))
                # Commit after each page so progress is saved
                ebay_threads_synced += page_threads
                ebay_messages_synced += page_messages
                logger.info("FROM_EBAY page %d (offset %d): +%d threads, +%d messages", pages_fetched, offset, page_threads, page_messages)
                total = conv_page.get("total") or 0
                offset += limit
                
                # Save offset after each page so progress survives timeout
                if ebay_offset_meta:
                    ebay_offset_meta.value = str(offset)
                else:
                    ebay_offset_meta = SyncMetadata(key="ebay_messages_offset", value=str(offset))
                    db.add(ebay_offset_meta)
                await db.commit()
                for mid, mlist in ebay_page_messages_with_media:
                    await _store_message_media_blobs(db, mid, mlist)
                
                if offset >= total or not conv_page.get("next"):
                    reached_end = True
                    break
            threads_synced += ebay_threads_synced
            messages_synced += ebay_messages_synced
            
            # Reset offset to 0 if we reached the end (for future incremental syncs)
            if reached_end:
                if ebay_offset_meta:
                    ebay_offset_meta.value = "0"
                    await db.commit()
                logger.info("FROM_EBAY: reached end of historical data, offset reset to 0")
        except httpx.HTTPStatusError as e:
            logger.warning("FROM_EBAY HTTP error %s, partial progress saved", e.response.status_code)
        except Exception as e:
            logger.warning("FROM_EBAY sync error: %s, partial progress saved", e)

        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        meta_updates: list[tuple[str, str]] = [
            ("messages_last_sync_at", now_utc),
            ("messages_member_last_sync_at", sync_start_time),
        ]
        if ran_full_sync:
            meta_updates.append(("messages_last_full_sync_at", now_utc))
        for key, value in meta_updates:
            meta_result = await db.execute(select(SyncMetadata).where(SyncMetadata.key == key))
            meta_row = meta_result.scalar_one_or_none()
            if meta_row:
                meta_row.value = value
            else:
                db.add(SyncMetadata(key=key, value=value))
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.warning("Messages sync: duplicate key (concurrent sync or API overlap): %s", e)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Sync conflict (duplicate). Please try again.",
        ) from e
    except Exception as e:
        await db.rollback()
        logger.exception("Messages sync: eBay or DB error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Sync failed: {e!s}",
        )

    sync_summary["threads_synced"] = threads_synced
    sync_summary["messages_synced"] = messages_synced
    sync_summary["ebay_threads_synced"] = ebay_threads_synced
    sync_summary["ebay_messages_synced"] = ebay_messages_synced
    if ran_full_sync and not full_sync:
        sync_summary["periodic_full_run"] = True
    sync_summary["at"] = datetime.now(timezone.utc).isoformat()
    try:
        log_dir = Path(__file__).resolve().parent.parent.parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        summary_path = log_dir / "sync_summary.log"
        with open(summary_path, "a") as f:
            f.write(json.dumps(sync_summary) + "\n")
    except Exception as e:
        logger.warning("Could not write sync summary log: %s", e)

    logger.info(
        "Messages sync: done full_sync=%s threads_synced=%d messages_synced=%d (FROM_EBAY: +%d threads +%d msgs)",
        full_sync,
        threads_synced,
        messages_synced,
        ebay_threads_synced,
        ebay_messages_synced,
    )
    if threads_synced or messages_synced:
        msg = f"Synced {threads_synced} thread(s), {messages_synced} message(s)."
    else:
        msg = "No new conversations or messages to sync."
    return {
        "message": msg,
        "synced": messages_synced,
        "threads_synced": threads_synced,
        "ebay_threads_synced": ebay_threads_synced,
        "ebay_messages_synced": ebay_messages_synced,
    }
