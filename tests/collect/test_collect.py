"""collect() 조립과 그래프 호출부 테스트 (B3 "조립"). 수집기는 가짜로 바꿔 끼워 네트워크 없이 본다."""
import json

import pytest

import src.collect as C
import src.graph as G
from src.state import ManagerData
from src.validate import validate


def _adv1(filed, tag):
    return {"filed_date": filed, "url": f"https://x/{tag}.zip#FilingID=1", "crd": "?", "aum_usd": 1e9,
            "employees": 10, "private_funds": 0,
            "people": [{"name": tag, "entity_type": "I", "title": "CEO", "since": "2020-01",
                        "ownership_code": "NA", "is_control_person": True}]}


def _adv2a(filed, item2="There have been no material changes."):
    return {"filed_date": filed, "url": "https://x/b.pdf", "items": {"2": item2, "8": "Strategy."},
            "pages": {"2": 2, "8": 5}}


def _quarter(filed):
    return {"period": "2026Q2", "report_date": "2026-06-30", "filed_date": filed, "accession": "a", "url": "https://x/",
            "holdings": []}


@pytest.fixture
def fake(monkeypatch):
    calls = {"13f": [], "adv1": [], "adv2a": []}
    state = {"adv1": ("2026-07-13", "2026-03-31"), "adv2a": ("2026-07-13", "2026-03-31"), "13f": "2026-08-14"}

    def c13f(cik):
        calls["13f"].append(cik)
        return [_quarter(state["13f"])], ["13F 기록"], []

    def c1(crd, last):
        calls["adv1"].append((crd, last))
        new, old = state["adv1"]
        return (_adv1(new, f"new-{crd}") if new else None), (_adv1(old, f"old-{crd}") if old else None), \
            ["P1 기록"], ([] if new else ["ADV Part 1 최신본: 확인 불가"])

    def c2(crd, last):
        calls["adv2a"].append((crd, last))
        new, old = state["adv2a"]
        return (_adv2a(new) if new else None), (_adv2a(old) if old else None), [], []
    monkeypatch.setattr("src.collect.form13f.collect_13f", c13f)
    monkeypatch.setattr(C, "collect_adv1", c1)
    monkeypatch.setattr(C, "collect_adv2a", c2)
    return calls, state


def test_live_collect_fills_the_selected_manager(fake):
    calls, _ = fake
    data = C.collect_live("demo2")
    validate(data, ManagerData)
    assert (data["manager_id"], data["manager_name"], data["cik"], data["crd"]) == \
        ("demo2", "Brown Capital Management, LLC", "0000885062", "105633")
    assert calls == {"13f": ["0000885062"], "adv1": [("105633", "2026-06-30")], "adv2a": [("105633", "2026-06-30")]}
    assert data["adv1_new"]["people"][0]["name"] == "new-105633" and data["adv1_old"]["people"][0]["name"] == "old-105633"
    assert data["item2_declares_no_change"] is True and data["has_new_filing"] is True
    assert "P1 기록" in data["notes"] and C.NOT_COMPARED in data["unavailable"]


def test_warburg_skips_13f_and_has_no_new_filing(fake):
    calls, state = fake
    state.update(adv1=("2026-03-31", "2026-03-31"), adv2a=("2026-03-31", "2026-03-31"))
    data = C.collect_live("demo3")
    assert calls["13f"] == [] and data["quarters"] == [] and data["holding_changes"] == []
    assert data["has_new_filing"] is False
    assert any("13F" in n and "has_13f=False" in n for n in data["notes"])


def test_missing_source_does_not_early_exit(fake):
    _, state = fake
    state.update(adv1=(None, "2026-03-31"), adv2a=("2026-03-31", "2026-03-31"))
    data = C.collect_live("demo3")
    assert data["has_new_filing"] is True                         # Part 1 최신본을 몰라 새 공시가 있을 수 있다
    assert any("새 공시 여부" in u and "ADV Part 1" in u for u in data["unavailable"])


def test_has_new_filing_rules():
    assert C._has_new_filing(None, {"ADV": "2020-01-01"}) == (True, [])
    assert C._has_new_filing("2026-06-30", {"13F": "2026-08-14", "ADV": None})[0] is True   # 하나라도 뒤면 새 공시
    assert C._has_new_filing("2026-06-30", {"13F": "2026-05-15", "ADV": "2026-06-30"}) == (False, [])


# ---------- 데모 저장본 ----------
def test_demo_save_and_load(fake, tmp_path, monkeypatch):
    monkeypatch.setattr(C, "DEMO_DIR", tmp_path)
    data = C.collect_live("demo2")
    path = C.save_demo(data)
    assert json.loads(open(path, encoding="utf-8").read())["fingerprint"] is None     # A9 형식
    plan = {"manager_id": "demo2", "manager_name": "Brown", "has_13f": True, "checks": [], "period": "2026H2"}
    assert C.collect(plan, demo_mode=True) == data


def test_demo_missing_file_says_which(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "DEMO_DIR", tmp_path)
    with pytest.raises(FileNotFoundError, match="demo3"):
        C.load_demo("demo3")


def test_demo_file_for_another_manager_is_rejected(fake, tmp_path, monkeypatch):
    monkeypatch.setattr(C, "DEMO_DIR", tmp_path)
    data = C.collect_live("demo1")
    (tmp_path / "demo2").mkdir()
    (tmp_path / "demo2" / "manager_data.json").write_text(json.dumps({"fingerprint": None, "result": data}),
                                                         encoding="utf-8")
    with pytest.raises(ValueError, match="demo1"):
        C.load_demo("demo2")


# ---------- 그래프 호출부: 실제 수집 결과가 상태에 들어가는가 ----------
def test_graph_live_mode_calls_collect_adv1_for_selected_manager(fake):
    calls, _ = fake
    evs = list(G.stream_run("Brown Capital 점검해줘", demo_mode=False))
    collect_state = next(e["state"] for e in evs if e["step"] == "collect")
    assert calls["adv1"] == [("105633", "2026-06-30")]
    d = collect_state["data"]
    assert d["manager_id"] == "demo2" and d["adv1_new"]["people"][0]["name"] == "new-105633"
    assert d["adv1_old"]["filed_date"] == "2026-03-31"


def test_graph_warburg_early_exit_without_13f(fake):
    calls, state = fake
    state.update(adv1=("2026-03-31", "2026-03-31"), adv2a=("2026-03-31", "2026-03-31"))
    evs = list(G.stream_run("Warburg Pincus 점검", demo_mode=False))
    assert [e["step"] for e in evs] == ["plan", "collect", "done"]
    last = evs[-1]["state"]
    assert last["status"] == "early_exit" and last["data"]["manager_id"] == "demo3" and calls["13f"] == []
