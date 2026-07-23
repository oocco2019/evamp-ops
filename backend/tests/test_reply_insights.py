"""Tests for reply insight fingerprinting / kind heuristic."""
from app.services.reply_insights import (
    _classify_kind_heuristic,
    fingerprint_for,
    normalize_instruction_text,
)


def test_normalize_collapses_whitespace():
    assert normalize_instruction_text("  Stop  using  , and  ") == "stop using , and"


def test_fingerprint_stable():
    a = fingerprint_for("Don't use , and in replies")
    b = fingerprint_for("don't use , and in replies")
    assert a == b


def test_classify_policy_vs_playbook():
    assert _classify_kind_heuristic("do not use comma before and") == "policy"
    assert _classify_kind_heuristic("suggest customer check a different socket before return") == "playbook"


def test_already_reviewed_docstring_contract():
    """Ensure helper exists for promote/dismiss dedupe (integration covered via service)."""
    from app.services import reply_insights as m

    assert callable(m._already_reviewed)
