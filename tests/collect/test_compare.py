"""신·구본 비교 테스트 (Frontend B4). 사실만 나란히 놓는다 — 해석·신호는 Data."""
from src.collect.compare import compare_holdings, compare_people, person_key
from src.state import HoldingChange, PersonChange
from src.validate import validate


def _h(cusip, value, shares, issuer=None, ticker=None):
    return {"cusip": cusip, "issuer": issuer or f"CO {cusip}", "title_of_class": "COM", "value_usd": value,
            "shares": shares, "ticker": ticker, "issuer_cik": None, "sic": None, "shares_outstanding": None,
            "shares_outstanding_partial": False, "is_etf": False}


def _q(period, *holdings):
    return {"period": period, "report_date": "2026-06-30", "filed_date": "2026-08-14", "accession": "a",
            "url": "https://x/", "holdings": list(holdings)}


# ---------- 13F 비교표 ----------
def test_holdings_new_exit_held_with_weights():
    old = _q("2026Q1", _h("A", 600, 6, ticker="AAA"), _h("B", 400, 4))
    new = _q("2026Q2", _h("A", 300, 3, ticker="AAA"), _h("C", 700, 7, ticker="CCC"))
    rows, unavailable = compare_holdings([old, new])
    for r in rows:
        validate(r, HoldingChange)
    by = {r["cusip"]: r for r in rows}
    assert {c: r["kind"] for c, r in by.items()} == {"A": "held", "B": "exit", "C": "new"}
    assert (by["A"]["weight_before"], by["A"]["weight_after"]) == (0.6, 0.3)
    assert (by["B"]["shares_after"], by["B"]["value_after"], by["B"]["weight_after"]) == (0.0, 0.0, 0.0)
    assert (by["C"]["value_before"], by["C"]["ticker"]) == (0.0, "CCC")
    assert [r["cusip"] for r in rows] == ["C", "B", "A"]          # 비중 변화가 큰 순 (0.7, 0.4, 0.3)
    assert unavailable == []


def test_holdings_need_two_consecutive_quarters():
    assert compare_holdings([_q("2026Q2", _h("A", 1, 1))]) == ([], ["13F 비교표: 확인 불가 (분기가 2개 미만)"])
    rows, unavailable = compare_holdings([_q("2025Q4", _h("A", 1, 1)), _q("2026Q2", _h("A", 1, 1))])
    assert rows == [] and "2026Q1" in unavailable[0]               # 빠진 분기를 건너뛰어 비교하지 않는다
    rows, unavailable = compare_holdings([_q("2025Q4", _h("A", 1, 1)), _q("2026Q1", _h("A", 1, 1))])
    assert rows and unavailable == []                              # 해가 바뀌는 연속 분기


def test_holdings_zero_total_is_unavailable():
    rows, unavailable = compare_holdings([_q("2026Q1", _h("A", 0, 0)), _q("2026Q2", _h("A", 5, 1))])
    assert rows == [] and "2026Q1" in unavailable[0]


def test_no_13f_means_no_table_and_nothing_to_report():
    assert compare_holdings([]) == ([], [])                        # 13F 를 쓰지 않는 운용사(Warburg)


# ---------- 임원·소유주 ----------
def _p(name, title="CEO", since="2012-01", own="NA", kind="I", control=True):
    return {"name": name, "entity_type": kind, "title": title, "since": since, "ownership_code": own,
            "is_control_person": control}


def _adv1(filed, *people, url=None):
    return {"filed_date": filed, "url": url or f"https://x/{filed}.zip#FilingID=1", "crd": "1", "aum_usd": 1.0,
            "employees": 1, "private_funds": 0, "people": list(people)}


def test_person_key_normalizes_names():
    assert person_key(_p("LEE, KEITH, ALLISON")) == person_key(_p("Keith Allison Lee"))
    assert person_key(_p("AKRE, CHARLES, THOMAS, JR.")) == person_key(_p("Charles Thomas Akre"))
    assert person_key(_p("BROWN CAPITAL MANAGEMENT HOLDINGS, INC.", kind="DE")) == \
        person_key(_p("Brown Capital Management Holdings Inc", kind="DE"))
    assert person_key(_p("SMITH, JOHN")) != person_key(_p("SMITH, JOHN", kind="DE"))   # 개인과 법인은 따로


def test_brown_06_30_shape_cco_replaced_only():
    # 실제 Brown 03-31 → 07-13 (verified.md 11/22): 같은 사람은 그대로, CCO 만 교체
    old = _adv1("2026-03-31", _p("BROWN, EDDIE, CARL", "FOUNDER"), _p("BURKS, ROBERT, E", "CHIEF COMPLIANCE OFFICER", "2019-02"))
    new = _adv1("2026-07-13", _p("BROWN, EDDIE, CARL", "FOUNDER"), _p("GARRISON, LISA, ANNE", "CHIEF COMPLIANCE OFFICER", "2026-06"))
    rows, unavailable = compare_people(new, old, "2026-06-30")
    for r in rows:
        validate(r, PersonChange)
    assert [(r["kind"], r["name"]) for r in rows] == [("added", "GARRISON, LISA, ANNE"), ("removed", "BURKS, ROBERT, E")]
    added, removed = rows
    assert added["before"] is None and added["after"]["since"] == "2026-06"
    assert [e["source"] for e in removed["evidence"]] == ["Form ADV Part 1A Schedule A",
                                                         "Form ADV Part 1A Schedule A (직전본)"]
    assert (removed["evidence"][0]["url"], removed["evidence"][1]["as_of"]) == (new["url"], "2026-03-31")
    assert unavailable == []


def test_title_and_ownership_changes_are_separate_rows():
    # Warburg 12-31: PERLMAN 지분 코드 NA → A, GLENN 직함 변경
    old = _adv1("2025-10-27", _p("PERLMAN, JEFFREY, DAVID", "CEO", own="NA"), _p("GLENN, STEVEN", "COO AND CFO"))
    new = _adv1("2026-03-31", _p("PERLMAN, JEFFREY, DAVID", "CEO", own="A"), _p("GLENN, STEVEN", "GLOBAL COO AND GLOBAL CFO"))
    rows, _ = compare_people(new, old, "2025-12-31")
    assert sorted((r["kind"], r["name"]) for r in rows) == [("ownership_changed", "PERLMAN, JEFFREY, DAVID"),
                                                            ("title_changed", "GLENN, STEVEN")]


def test_cosmetic_title_differences_are_not_changes():
    old = _adv1("2026-03-31", _p("LEE, KEITH", "CEO & SENIOR PORTFOLIO MANAGER"))
    new = _adv1("2026-07-13", _p("Lee, Keith", "CEO and Senior Portfolio  Manager"))
    assert compare_people(new, old, "2026-06-30") == ([], [])


def test_same_filing_on_both_sides_has_no_changes():
    a = _adv1("2026-03-31", _p("A, B"), _p("C, D"))
    assert compare_people(a, {**a, "people": [dict(p) for p in a["people"]]}, "2026-06-30") == ([], [])


def test_without_previous_uses_since_after_last_check():
    new = _adv1("2026-07-13", _p("OLD, HAND", since="2019-02"), _p("NEW, HIRE", since="2026-07"),
                _p("JUNE, HIRE", since="2026-06"))
    rows, unavailable = compare_people(new, None, "2026-06-30")
    assert [(r["kind"], r["name"]) for r in rows] == [("added", "NEW, HIRE")]   # 06-30 기준이면 6월 취임은 이전
    assert any("임원 제외 여부: 이전본 없음" in u for u in unavailable)


def test_without_previous_or_last_check_uses_six_month_window():
    new = _adv1("2026-07-13", _p("A, OLD", since="2025-12"), _p("B, NEW", since="2026-01"), _p("C, NONE", since=None))
    rows, _ = compare_people(new, None, None)
    assert [r["name"] for r in rows] == ["B, NEW"]                 # 07-13 기준 최근 6개월 = 2026-01 부터


def test_unreadable_people_list_is_not_compared():
    # Part 1 이 명단을 못 읽으면 people=[] + 확인 불가 → 비교하면 전원 추가·삭제가 된다
    old, new = _adv1("2026-03-31", _p("A, B")), _adv1("2026-07-13")
    rows, unavailable = compare_people(new, old, "2026-06-30")
    assert rows == [] and any("확인 불가" in u for u in unavailable)
    rows, unavailable = compare_people(None, old, "2026-06-30")
    assert rows == [] and any("최신본" in u for u in unavailable)


def test_duplicate_person_is_left_out_and_recorded():
    old = _adv1("2026-03-31", _p("A, B", "CEO"), _p("A, B", "CFO"), _p("C, D"))
    new = _adv1("2026-07-13", _p("A, B", "CEO"), _p("E, F"))
    rows, unavailable = compare_people(new, old, "2026-06-30")
    assert sorted((r["kind"], r["name"]) for r in rows) == [("added", "E, F"), ("removed", "C, D")]
    assert any("A, B" in u and "여러 번" in u for u in unavailable)
