"""지표 계산 테스트 (Data 문서 B2 손 계산 예시, B3, C장 테스트 목록). 정답은 docs/metrics.md 5장."""
import json
from pathlib import Path

import pytest

from src.analysis import metrics as m
from src.analysis.sectors import sector_of
from src.analysis.splits import adjust_splits

TOL = 1e-6
BIG_SO = 1e12        # 시가총액이 충분히 커서 "대형"
SMALL_SO = 1e6       # 시가총액이 작아서 "소형"


def h(cusip, shares, price, so=BIG_SO, cik="0000000001", sic="7372", etf=False, partial=False, ticker=None):
    return {"cusip": cusip, "issuer": cusip, "title_of_class": "COM", "value_usd": shares * price,
            "shares": shares, "ticker": ticker or cusip, "issuer_cik": cik, "sic": sic,
            "shares_outstanding": so, "shares_outstanding_partial": partial, "is_etf": etf}


def q(period, holdings):
    return {"period": period, "report_date": "2026-06-30", "filed_date": "2026-08-14",
            "accession": "x", "url": "", "holdings": holdings}


# ---------- 손 계산 예시 (B2) ----------
PREV = q("2026Q1", [h("A", 100, 10), h("B", 50, 20)])
CURR = q("2026Q2", [h("A", 100, 12), h("B", 25, 20), h("C", 10, 40, so=SMALL_SO)])


def test_hand_example_active_change_per_stock():
    P, C = m.prepare(PREV), m.prepare(CURR)
    P_adj, _ = adjust_splits(P, C)
    t = m._joined(P, P_adj, C)
    active = t["w_now"] - t["w_passive"]
    assert active["A"] == pytest.approx(0.0259740, abs=TOL)
    assert active["B"] == pytest.approx(-0.2164502, abs=TOL)
    assert active["C"] == pytest.approx(0.1904762, abs=TOL)
    assert active.sum() == pytest.approx(0.0, abs=TOL)


def test_hand_example_turnover():
    r = m.compute_changes(PREV, CURR)
    assert r["turnover"]["after"] == pytest.approx(0.1951220, abs=TOL)


def test_hand_example_size_shift_small_wins_tie():
    r = m.compute_changes(PREV, CURR)
    s = r["size_shift"]
    assert s["metric"] == "small_cap_weight"
    assert s["active_change"] == pytest.approx(0.1904762, abs=TOL)
    assert s["magnitude"] == pytest.approx(0.1904762, abs=TOL)
    assert s["before"] == pytest.approx(0.0, abs=TOL)
    assert s["after"] == pytest.approx(0.1904762, abs=TOL)


def test_hand_example_concentration_all_in_top10():
    c = m.compute_changes(PREV, CURR)["concentration_change"]
    assert c["before"] == pytest.approx(1.0) and c["after"] == pytest.approx(1.0)
    assert c["magnitude"] == pytest.approx(0.0, abs=TOL)


# ---------- 분할 보정 (C장 테스트 목록) ----------
def test_two_for_one_split_is_not_trading():
    prev = q("p", [h("S", 100, 10, so=1e9), h("Z", 100, 10)])
    curr = q("c", [h("S", 200, 5.5, so=2e9), h("Z", 100, 10)])
    r = m.compute_changes(prev, curr)
    assert r["turnover"]["after"] == pytest.approx(0.0, abs=TOL)
    assert "분할 보정: S ×2" in r["data_checks"]


def test_price_jump_without_shares_outstanding_excluded():
    prev = q("p", [h("J", 100, 10, so=None), h("Z", 100, 10)])
    curr = q("c", [h("J", 300, 4, so=None), h("Z", 100, 10)])
    r = m.compute_changes(prev, curr)
    assert "가격 급변으로 매매 계산 제외: J" in r["data_checks"]
    assert r["turnover"]["after"] == pytest.approx(0.0, abs=TOL)


# ---------- 데이터 검사 ----------
def test_low_mapping_rate_makes_sector_and_size_unavailable():
    prev = q("p", [h("A", 100, 10), h("X", 10, 10, cik=None)])
    curr = q("c", [h("A", 100, 12), h("X", 10, 10, cik=None)])          # 매핑률 약 91~92%
    r = m.compute_changes(prev, curr)
    assert r["sector_shift"] is None and r["size_shift"] is None
    assert any(u.startswith("업종·규모 지표: 매핑률 ") for u in r["unavailable"])
    assert r["concentration_change"] is not None and r["turnover"] is not None


def test_low_size_coverage_only_size_unavailable():
    prev = q("p", [h("A", 100, 10), h("X", 15, 10, so=None)])
    curr = q("c", [h("A", 100, 12), h("X", 15, 10, so=None)])
    r = m.compute_changes(prev, curr)
    assert r["sector_shift"] is not None
    assert r["size_shift"] is None
    assert any(u.startswith("규모 지표: ") for u in r["unavailable"])


def test_partial_shares_outstanding_large_only():
    assert m.size_bucket(100, 2e8, partial=True) == "대형"         # 200억 ≥ 100억
    assert m.size_bucket(100, 5e7, partial=True) == "미분류"        # 50억, 하한값이라 판단 못 함
    assert m.size_bucket(100, 5e7, partial=False) == "중형"
    assert m.size_bucket(100, 1e7, partial=False) == "소형"
    assert m.size_bucket(100, None, partial=False) == "미분류"


def test_etf_excluded_from_weights():
    P = m.prepare(q("p", [h("A", 100, 10), h("SPY", 100, 10, etf=True)]))
    assert list(P.index) == ["A"]
    assert P.attrs["V"] == 1000


def test_sector_shift_picks_largest_active():
    prev = q("p", [h("T", 100, 10, sic="7372"), h("F", 100, 10, sic="6022")])
    curr = q("c", [h("T", 150, 10, sic="7372"), h("F", 50, 10, sic="6022")])
    s = m.compute_changes(prev, curr)["sector_shift"]
    assert s["metric"] in ("sector_weight:서비스", "sector_weight:금융·보험·부동산")
    assert s["magnitude"] == pytest.approx(0.25, abs=TOL)
    assert s["metric"] == "sector_weight:금융·보험·부동산"          # 동점이면 표에서 앞선 업종


@pytest.mark.parametrize("sic,name", [("0100", "농림어업"), ("1311", "광업"), ("3674", "제조"),
                                      ("4813", "운송·통신·전기가스"), ("5045", "도매"), ("5961", "소매"),
                                      ("6022", "금융·보험·부동산"), ("7372", "서비스"), ("9995", "공공·기타"),
                                      (None, "미분류"), ("", "미분류"), ("1900", "미분류"), (100, "농림어업")])
def test_sector_table(sic, name):
    assert sector_of(sic) == name


def test_series_fills_previous_turnover():
    q3 = q("2026Q3", [h("A", 100, 12), h("B", 50, 20), h("C", 10, 40, so=SMALL_SO)])
    res = m.compute_series([PREV, CURR, q3])
    assert [r["period"] for r in res] == ["2026Q2", "2026Q3"]
    assert res[0]["turnover"]["before"] is None
    assert res[1]["turnover"]["before"] == pytest.approx(res[0]["turnover"]["after"])


def test_empty_quarter_does_not_crash():
    r = m.compute_changes(q("p", []), CURR)
    assert all(r[k] is None for k in m.METRIC_KEYS)
    assert r["unavailable"]


# ---------- 실제 데모 저장본으로 혼자 돌아가는지 (11/24 마일스톤) ----------
DEMO = Path(__file__).resolve().parents[2] / "data_cache" / "demo"


@pytest.mark.parametrize("demo", ["demo1", "demo2"])
def test_runs_on_demo_data(demo):
    path = DEMO / demo / "manager_data.json"
    if not path.exists():
        pytest.skip("데모 저장본 없음")
    data = json.loads(path.read_text(encoding="utf-8"))
    quarters = data.get("result", data)["quarters"]
    res = m.compute_series(quarters)
    assert len(res) == len(quarters) - 1
    for r in res:
        assert r["turnover"] is not None and 0 <= r["turnover"]["after"] <= 1
        assert r["concentration_change"] is not None
        for k in m.METRIC_KEYS:
            if r[k] is not None:
                assert r[k]["magnitude"] is None or r[k]["magnitude"] >= 0
