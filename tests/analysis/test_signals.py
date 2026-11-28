"""신호 판정·설명·전략·조립 테스트 (Data 문서 B4, C장 테스트 목록). LLM·네트워크 없음."""
import importlib
import json

import pytest

from src import analysis as A

E = importlib.import_module("src.analysis.explain")       # 패키지가 같은 이름의 함수를 내보내서 모듈로 직접 가져온다
S = importlib.import_module("src.analysis.signals")
ST = importlib.import_module("src.analysis.strategy")
from src.report.format import unknown_numbers

# 분포 기준값: 0~100 백분위 값이 0.00~1.00 → pct 가 변화폭과 같아져서 읽기 쉽다
DIST = {"metrics": {"turnover": {"mode": "distribution", "quantiles": [i / 100 for i in range(101)],
                                 "p90": 0.9, "p95": 0.95, "n": 1000}}}
PLACE = {"metrics": {"turnover": {"mode": "placeholder", "p90": 0.20, "p95": 0.30, "quantiles": None, "n": None}}}


def q(period):
    return {"period": period, "report_date": "2026-09-30", "filed_date": "2026-11-14", "accession": "a",
            "url": f"https://sec.gov/{period}", "holdings": []}


def data(**kw):
    d = {"manager_id": "m1", "manager_name": "Test LLC", "cik": None, "crd": None, "quarters": [],
         "holding_changes": [], "adv1_new": None, "adv1_old": None, "adv2a_new": None, "adv2a_old": None,
         "person_changes": [], "text_changes": [], "item2_declares_no_change": None, "has_new_filing": True,
         "notes": [], "unavailable": [], "fetched_at": "2026-11-28"}
    d.update(kw)
    return d


def fake_series(monkeypatch, turnovers):
    """회전율 변화폭 목록(마지막이 이번 분기)으로 compute_series 결과를 흉내 낸다."""
    rows = []
    for i, t in enumerate(turnovers):
        rows.append({"period": f"P{i}", "sector_shift": None, "size_shift": None, "concentration_change": None,
                     "turnover": {"metric": "turnover", "before": None if i == 0 else turnovers[i - 1],
                                  "after": t, "change": None, "active_change": None, "magnitude": t},
                     "data_checks": [], "unavailable": []})
    monkeypatch.setattr(S, "compute_series", lambda quarters: rows)
    return data(quarters=[q("2026Q2"), q("2026Q3")])


# ---------- C장: 경보·관찰 판정 ----------
def test_alert_at_96(monkeypatch):
    d = fake_series(monkeypatch, [0.1] * 12 + [0.96])
    s = S.detect(d, DIST).signals
    assert [x["level"] for x in s] == ["alert"]
    assert s[0]["percentile"] == pytest.approx(0.96)


def test_watch_at_92_above_own(monkeypatch):
    d = fake_series(monkeypatch, [0.5] * 12 + [0.92])
    s = S.detect(d, DIST).signals
    assert [x["level"] for x in s] == ["watch"] and s[0]["exceeds_own_3y_max"] is True


def test_none_at_92_below_own(monkeypatch):
    d = fake_series(monkeypatch, [0.5] * 11 + [0.93, 0.92])
    assert S.detect(d, DIST).signals == []


def test_92_with_three_history_unavailable(monkeypatch):
    d = fake_series(monkeypatch, [0.1, 0.1, 0.1, 0.92])
    det = S.detect(d, DIST)
    assert det.signals == []
    assert any("자기 3년 최대치 판정 불가" in u for u in det.unavailable)


def test_96_with_three_history_still_alert(monkeypatch):
    d = fake_series(monkeypatch, [0.1, 0.1, 0.1, 0.96])
    assert [x["level"] for x in S.detect(d, DIST).signals] == ["alert"]


def test_placeholder_thresholds(monkeypatch):
    d = fake_series(monkeypatch, [0.1] * 12 + [0.31])
    s = S.detect(d, PLACE).signals
    assert s[0]["level"] == "alert" and s[0]["percentile"] is None
    assert s[0]["summary"].endswith("(임시 기준)")


def test_missing_threshold_is_unavailable(monkeypatch):
    d = fake_series(monkeypatch, [0.1] * 13)
    det = S.detect(d, {"metrics": {}})
    assert det.signals == [] and any("기준값 없음" in u for u in det.unavailable)


def test_13f_summary_and_evidence(monkeypatch):
    d = fake_series(monkeypatch, [0.1] * 12 + [0.96])
    s = S.detect(d, DIST).signals[0]
    assert s["summary"] == "분기 회전율 96% (직전 10%), 전체 13F 운용사 분기 변화폭 상위 4%"
    assert [e["source"] for e in s["evidence"]] == ["Form 13F 2026Q3", "Form 13F 2026Q2"]
    assert unknown_numbers(s["summary"], [s]) == []


def test_percentile_interpolation():
    qs = [i * 2 for i in range(101)]            # 0, 2, ..., 200
    assert S.percentile_of(101, qs) == pytest.approx(0.505)
    assert S.percentile_of(-1, qs) == 0.0 and S.percentile_of(999, qs) == 1.0


# ---------- ADV ----------
EV = [{"source": "Form ADV Part 1A Schedule A", "url": "u", "as_of": "2026-03-30", "page": None, "quote": None}]


def person(name, title, et="I"):
    return {"name": name, "entity_type": et, "title": title, "since": None, "ownership_code": None,
            "is_control_person": None}


def test_people_grouped_by_kind_alert():
    d = data(person_changes=[
        {"kind": "removed", "name": "A", "before": person("A", "CO-CIO"), "after": None, "evidence": EV},
        {"kind": "removed", "name": "B", "before": person("B", "COO"), "after": None, "evidence": EV},
        {"kind": "added", "name": "HOLDCO", "before": None, "after": person("HOLDCO", "OWNER", "DE"), "evidence": EV},
        {"kind": "ownership_changed", "name": "C", "before": person("C", "CEO"), "after": person("C", "CEO"),
         "evidence": EV},
    ])
    s = {x["metric"]: x for x in S.detect(d, {"metrics": {}}).signals}
    assert set(s) == {"officer_removed", "owner_changed"}
    assert s["officer_removed"]["summary"] == "임원 2명 제외: A(CO-CIO), B(COO)"
    assert all(x["level"] == "alert" and x["kind"] == "key_person" for x in s.values())
    assert len(s["officer_removed"]["evidence"]) == 1                 # 같은 근거는 하나로


def test_text_change_and_item2_count_as_one_watch():
    tc = {"item": "8", "before": "old", "after": "new", "material": True,
          "evidence": [{"source": "Form ADV Part 2A Item 8", "url": "u", "as_of": "2026-03-30", "page": 12,
                        "quote": None}]}
    d = data(text_changes=[tc], item2_declares_no_change=True,
             adv2a_new={"filed_date": "2026-03-30", "url": "u2", "items": {"2": "x", "8": "y"}, "pages": {"2": 2}})
    det = S.detect(d, {"metrics": {}})
    assert sorted(x["metric"] for x in det.signals) == ["item2_mismatch", "strategy_text_changed"]
    assert det.debate_required is False                               # 관찰 2개지만 같은 변경 → 1개


def test_item2_none_gives_no_mismatch():
    tc = {"item": "8", "before": "o", "after": "n", "material": True, "evidence": EV}
    det = S.detect(data(text_changes=[tc], item2_declares_no_change=None), {"metrics": {}})
    assert [x["metric"] for x in det.signals] == ["strategy_text_changed"]


def adv1(date, aum, emp, pf):
    return {"filed_date": date, "url": "u" + date, "crd": "1", "aum_usd": aum, "employees": emp,
            "private_funds": pf, "people": []}


def test_adv1_rules():
    d = data(adv1_old=adv1("2025-03-28", 12e9, 40, 4), adv1_new=adv1("2026-03-30", 7.8e9, 28, 7))
    s = {x["metric"]: x for x in S.detect(d, {"metrics": {}}).signals}
    assert s["aum_change"]["summary"] == "운용자산 $12B → $7.8B (-35%), ADV 제출일 2025-03-28 → 2026-03-30"
    assert s["employee_drop"]["summary"] == "직원 40명 → 28명 (-30%), ADV 제출일 2025-03-28 → 2026-03-30"
    assert s["private_fund_change"]["summary"] == "사모펀드 4개 → 7개, ADV 제출일 2025-03-28 → 2026-03-30"
    assert s["employee_drop"]["kind"] == "key_person"
    for x in s.values():
        assert unknown_numbers(x["summary"], [x]) == []


def test_adv1_small_changes_no_signal():
    d = data(adv1_old=adv1("a", 10e9, 10, 4), adv1_new=adv1("b", 8e9, 8, 5))   # -20%, 2명, 1개
    assert S.detect(d, {"metrics": {}}).signals == []


def test_adv1_zero_old_skipped():
    d = data(adv1_old=adv1("a", 0, 0, 0), adv1_new=adv1("b", 5e9, 10, 1))
    assert S.detect(d, {"metrics": {}}).signals == []


def test_debate_required_rules():
    w = {"level": "watch", "metric": "aum_change"}
    assert S.debate_required([{"level": "alert", "metric": "x"}]) is True
    assert S.debate_required([w]) is False
    assert S.debate_required([w, dict(w, metric="employee_drop")]) is True


def test_ids_stable_and_sorted():
    d = data(adv1_old=adv1("a", 12e9, 40, 4), adv1_new=adv1("b", 7.8e9, 28, 7))
    ids1 = [x["id"] for x in S.detect(d, {"metrics": {}}).signals]
    ids2 = [x["id"] for x in S.detect(d, {"metrics": {}}).signals]
    assert ids1 == ids2 == ["m1-key_person-1", "m1-strategy_drift-1", "m1-strategy_drift-2"]


def test_no_13f_manager_runs():
    assert S.detect(data(quarters=[]), {"metrics": {}}).signals == []


# ---------- 설명 ----------
def sig(id_, summary="운용자산 $12B → $7.8B (-35%), ADV 제출일 2025-03-28 → 2026-03-30"):
    return {"id": id_, "manager_id": "m1", "kind": "strategy_drift", "level": "watch", "source_form": "ADV",
            "metric": "aum_change", "unit": "usd", "before": 12e9, "after": 7.8e9, "change": -4.2e9,
            "active_change": None, "percentile": None, "exceeds_own_3y_max": None, "peer_median": None,
            "summary": summary, "explanation": summary, "evidence": EV}


def test_explain_keeps_good_drops_unknown_numbers(monkeypatch):
    monkeypatch.setattr(E, "call_llm", lambda *a, **k: {"explanations": [
        {"signal_id": "s1", "text": "운용자산이 $12B에서 $7.8B로 줄었습니다."},
        {"signal_id": "s2", "text": "운용자산이 40% 줄었습니다."}]})                    # 40% 는 없는 숫자
    out, checks = E.explain([sig("s1"), sig("s2")], "Test")
    assert out[0]["explanation"] == "운용자산이 $12B에서 $7.8B로 줄었습니다."
    assert out[1]["explanation"] == out[1]["summary"]
    assert checks and "s2" in checks[0]


def test_explain_llm_failure_falls_back(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(E, "call_llm", boom)
    out, checks = E.explain([sig("s1")], "Test")
    assert out[0]["explanation"] == out[0]["summary"] and checks


# ---------- 전략 ----------
ITEM8 = ("Our strategy focuses on   high-quality U.S. companies with durable competitive advantages.\n"
         "We hold a concentrated portfolio and seek to own businesses for the long term.")
ADV2A = {"filed_date": "2026-03-30", "url": "u", "items": {"8": ITEM8}, "pages": {"8": 14}}


def test_strategy_keeps_only_real_quotes(monkeypatch):
    monkeypatch.setattr(ST, "_search", lambda mid: [])
    monkeypatch.setattr(ST, "call_llm", lambda *a, **k: {
        "quotes": ["Our strategy focuses on high-quality U.S. companies with durable competitive advantages.",
                   "We invest only in Japanese small caps and never hold cash at all."],
        "summary": "경쟁우위가 있는 미국 우량 기업에 장기 집중 투자"})
    s, ev, un = ST.stated_strategy(data(adv2a_new=ADV2A))
    assert s == "경쟁우위가 있는 미국 우량 기업에 장기 집중 투자" and un == []
    assert len(ev) == 1 and ev[0]["page"] == 14 and ev[0]["source"] == "Form ADV Part 2A Item 8"


def test_strategy_no_valid_quote_unavailable(monkeypatch):
    monkeypatch.setattr(ST, "_search", lambda mid: [])
    monkeypatch.setattr(ST, "call_llm", lambda *a, **k: {"quotes": ["made up sentence that is not there"],
                                                         "summary": "x"})
    assert ST.stated_strategy(data(adv2a_new=ADV2A)) == (None, [], [ST.UNAVAILABLE])


def test_strategy_without_part2a():
    assert ST.stated_strategy(data()) == (None, [], [ST.UNAVAILABLE])


# ---------- 조립·저장본 ----------
def test_analyze_validates_and_uses_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "DEMO_DIR", tmp_path)
    monkeypatch.setattr(A, "explain", lambda s, n: (s, []))
    monkeypatch.setattr(A, "stated_strategy", lambda d: (None, [], [ST.UNAVAILABLE]))
    d = data(adv1_old=adv1("a", 12e9, 40, 4), adv1_new=adv1("b", 7.8e9, 28, 7))

    monkeypatch.setenv("LLM_MOCK", "1")
    r = A.analyze(d, {})
    assert r["debate_required"] is True and not (tmp_path / "m1" / "analysis.json").exists()   # mock 결과는 저장 안 함

    monkeypatch.setenv("LLM_MOCK", "0")
    r = A.analyze(d, {})
    saved = json.loads((tmp_path / "m1" / "analysis.json").read_text(encoding="utf-8"))
    assert saved["fingerprint"] == A.fingerprint(d) and saved["result"] == r

    monkeypatch.setattr(A, "build", lambda d: (_ for _ in ()).throw(AssertionError("저장본을 써야 함")))
    assert A.analyze(d, {}) == r
