"""Unit tests for reply policy / playbook helpers."""
import json

import pytest

from app.services.reply_compose import (
    _parse_adherence_json,
    playbook_matches_keywords,
    sku_matches_scope,
)


@pytest.mark.parametrize(
    "sku,scope,expected",
    [
        ("dee01", "*", True),
        (None, "*", True),
        ("dee01", "dee01", True),
        ("dee01", "DEE01", True),
        ("dee01", "dee*", True),
        ("dee01", "uke*", False),
        ("dee01", "dee02", False),
        (None, "dee*", False),
        ("", "dee*", False),
        ("dee01", "dee01, dee02, uke01", True),
        ("uke01", "dee01, dee02, uke01", True),
        ("uke02", "dee01, dee02, uke01", False),
        ("dee99", "dee*, uke01", True),
        ("uke01", "dee*, uke01", True),
        ("abc", "dee01, *", True),
    ],
)
def test_sku_matches_scope(sku, scope, expected):
    assert sku_matches_scope(sku, scope) is expected


@pytest.mark.parametrize(
    "text,keywords,expected",
    [
        ("hello wifi issue", None, True),
        ("hello wifi issue", [], True),
        ("hello wifi issue", ["wifi"], True),
        ("hello wifi issue", ["SSID"], False),
        ("rename the SSID please", ["ssid", "wifi"], True),
        ("nothing here", ["label", "a4"], False),
    ],
)
def test_playbook_matches_keywords(text, keywords, expected):
    assert playbook_matches_keywords(text, keywords) is expected


class _Pol:
    def __init__(self, id: int):
        self.id = id
        self.body = f"policy {id}"


def test_parse_adherence_json_happy():
    raw = json.dumps(
        {
            "results": [
                {"policy_id": 1, "pass": True, "reason": "ok"},
                {"policy_id": 2, "pass": False, "reason": "used a date"},
            ]
        }
    )
    out = _parse_adherence_json(raw, [_Pol(1), _Pol(2)])
    assert out["all_passed"] is False
    assert out["results"][0]["pass"] is True
    assert out["results"][1]["pass"] is False


def test_parse_adherence_json_markdown_wrapped():
    raw = 'Here you go:\n```json\n{"results":[{"policy_id":1,"pass":true,"reason":"ok"}]}\n```\n'
    out = _parse_adherence_json(raw, [_Pol(1)])
    assert out["all_passed"] is True


def test_parse_adherence_json_garbage_treats_as_pass():
    out = _parse_adherence_json("not json", [_Pol(9)])
    assert out["all_passed"] is True
    assert out["results"][0]["policy_id"] == 9
