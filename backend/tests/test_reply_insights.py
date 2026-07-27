"""Tests for reply insight fingerprinting / kind heuristic / thresholds."""
from app.services.reply_insights import (
    MIN_OCCURRENCES,
    _classify_kind_heuristic,
    _clean_candidate_body,
    fingerprint_for,
    normalize_instruction_text,
)


def test_min_occurrences_is_three():
    assert MIN_OCCURRENCES == 3


def test_normalize_collapses_whitespace():
    assert normalize_instruction_text("  Stop  using  , and  ") == "stop using , and"


def test_fingerprint_stable():
    a = fingerprint_for("Don't use , and in replies")
    b = fingerprint_for("don't use , and in replies")
    assert a == b


def test_classify_policy_vs_playbook():
    assert _classify_kind_heuristic("do not use comma before and") == "policy"
    assert _classify_kind_heuristic("suggest customer check a different socket before return") == "playbook"


def test_clean_candidate_keeps_short_rules():
    body = _clean_candidate_body("do not use dashes in replies")
    assert "dash" in body.lower()
    assert len(body) < 80


def test_already_reviewed_docstring_contract():
    from app.services import reply_insights as m

    assert callable(m._already_reviewed)
    assert callable(m.run_weekly_prompt_insight_scan)
    assert callable(m.run_seller_style_insight_scan)


def test_seller_style_fingerprint_namespaced():
    a = fingerprint_for("Prefer short warm closings", "seller_style_scan")
    b = fingerprint_for("Prefer short warm closings", "weekly_distill")
    assert a != b
