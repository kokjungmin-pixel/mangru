"""make_plan: 데모 운용사 3곳을 이름·별칭으로 찾는다 (PM)"""
import re
from datetime import date

from src.config import DEMO_MANAGERS
from src.plan import make_plan
from src.state import Plan
from src.validate import validate

TODAY = date(2026, 11, 16)


def test_three_demo_managers_with_valid_ids():
    assert len(DEMO_MANAGERS) == 3
    assert sum(not m["has_13f"] for m in DEMO_MANAGERS.values()) == 1  # 대체 1곳
    for m in DEMO_MANAGERS.values():
        assert re.fullmatch(r"\d{10}", m["cik"]) and re.fullmatch(r"\d+", m["crd"])
        assert date.fromisoformat(m["last_check_date"]) < TODAY


def test_find_by_alias_case_insensitive():
    cases = {"akre 점검해줘": "demo1", "Brown Capital 반기 점검": "demo2",
             "WARBURG 봐줘": "demo3"}
    for req, mid in cases.items():
        p = make_plan(req, TODAY)
        validate(p, Plan)
        assert p["manager_id"] == mid and p["period"] == "2026H2"
        assert p["has_13f"] == DEMO_MANAGERS[mid]["has_13f"]


def test_unknown_manager_returns_none():
    assert make_plan("Example Capital 점검해줘", TODAY) is None
