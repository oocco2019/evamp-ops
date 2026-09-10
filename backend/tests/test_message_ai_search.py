"""Unit tests for AI message search helpers (no live LLM)."""
from app.services.message_ai_search import (
    batch_thread_blocks,
    parse_matching_thread_ids,
    build_batch_user_prompt,
)


def test_batch_thread_blocks_respects_max_chars():
    blocks = [("a", "x" * 100), ("b", "y" * 100), ("c", "z" * 50)]
    batches = batch_thread_blocks(blocks, max_chars=150)
    assert len(batches) == 3
    assert [tid for tid, _ in batches[0]] == ["a"]
    assert [tid for tid, _ in batches[1]] == ["b"]
    assert [tid for tid, _ in batches[2]] == ["c"]


def test_batch_thread_blocks_packs_small_threads():
    blocks = [("a", "aa"), ("b", "bb"), ("c", "cc")]
    batches = batch_thread_blocks(blocks, max_chars=20)
    assert len(batches) == 1
    assert [tid for tid, _ in batches[0]] == ["a", "b", "c"]


def test_batch_oversized_single_thread_alone():
    blocks = [("big", "Z" * 500), ("small", "ok")]
    batches = batch_thread_blocks(blocks, max_chars=100)
    assert batches[0] == [("big", "Z" * 500)]
    assert batches[1] == [("small", "ok")]


def test_parse_matching_thread_ids_json_array():
    valid = {"t1", "t2", "t3"}
    raw = 'Here you go:\n["t2", "t1"]\n'
    assert parse_matching_thread_ids(raw, valid) == ["t2", "t1"]


def test_parse_matching_thread_ids_markdown_fence():
    valid = {"abc", "def"}
    raw = '```json\n["abc"]\n```'
    assert parse_matching_thread_ids(raw, valid) == ["abc"]


def test_parse_matching_thread_ids_filters_unknown():
    valid = {"real"}
    assert parse_matching_thread_ids('["real","fake"]', valid) == ["real"]


def test_parse_matching_thread_ids_empty():
    assert parse_matching_thread_ids("[]", {"a"}) == []
    assert parse_matching_thread_ids("", {"a"}) == []


def test_build_batch_user_prompt_includes_query_and_ids():
    prompt = build_batch_user_prompt(
        "forgot phone number on return",
        [("tid1", "thread_id=tid1\n[buyer] hello")],
        1,
        2,
    )
    assert "forgot phone number on return" in prompt
    assert "tid1" in prompt
    assert "batch 1/2" in prompt


def test_ai_search_thread_ids_merges_batches():
    import asyncio
    from app.services.message_ai_search import ai_search_thread_ids

    blocks = [("t1", "AAA"), ("t2", "BBB"), ("t3", "CCC")]

    async def fake_complete(user_prompt: str, *, system: str, max_tokens: int = 4000, temperature: float = 0):
        if "AAA" in user_prompt:
            return '["t1"]'
        if "BBB" in user_prompt:
            return "[]"
        return '["t3"]'

    ids = asyncio.get_event_loop().run_until_complete(
        ai_search_thread_ids("return phone", blocks, fake_complete, max_batch_chars=5)
    )
    assert ids == ["t1", "t3"]
