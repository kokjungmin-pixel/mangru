"""ADV Part 1(운용자산·직원·사모펀드 수·Schedule A) 수집 테스트 (B3). 월별 Part 1 묶음(CSV)을 가짜로 만든다.
열 이름·값 모양은 실제 2026-03·06·07 묶음 그대로 (docs/verified.md 2026-11-22)."""
import csv
import io
import json
import zipfile

import pytest

from src.collect import form_adv
from src.state import AdvPart1
from src.validate import validate

CRD = "105633"
BASE_COLS = ["FilingID", "DateSubmitted", "1A", "1E1", "5A", "5F2a", "5F2b", "5F2c"]
SCHA_COLS = ["FilingID", "SchA-3", "Schedule", "Full Legal Name", "DE/FE/I", "Entity in Which", "Title or Status",
             "Status Acquired", "Ownership Code", "Control Person", "PR", "OwnerID"]
D7_COLS = ["FilingID", "Fund Name", "Fund ID"]


def _url(y, m, last):
    return f"https://reports.adviserinfo.sec.gov/reports/foia/advFilingData/{y}/ADV_Filing_Data_{y}{m:02d}01_{y}{m:02d}{last}.zip"


def _csv(cols, rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    w.writerows(rows)
    return buf.getvalue().encode("utf-8")


def _month(y, m, last, base, scha=(), d7=(), skip=(), base_cols=BASE_COLS, scha_cols=SCHA_COLS, d7_cols=D7_COLS):
    tag = f"{y}{m:02d}01_{y}{m:02d}{last}"
    files = {f"IA_ADV_Base_A_{tag}.csv": _csv(base_cols, base),
             f"IA_ADV_Base_B_{tag}.csv": _csv(["FilingID"], []),
             f"IA_Schedule_A_B_{tag}.csv": _csv(scha_cols, scha),
             f"IA_Schedule_D_7B1_{tag}.csv": _csv(d7_cols, d7),
             f"IA_Schedule_D_7B1A17b_{tag}.csv": _csv(D7_COLS, [("9", "가짜", "x")] * 5)}   # 이름이 비슷한 다른 표
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            if not any(name.startswith(s) for s in skip):
                z.writestr(name, data)
    return buf.getvalue()


def _base(fid, submitted, crd=CRD, emp="37", aum="4536497889"):
    return (fid, submitted, "BROWN CAPITAL MANAGEMENT, LLC", crd, emp, aum, "0", aum)


def _a(fid, name, kind="I", title="CEO", since="01/2012", own="NA", control="Y", sched="A"):
    return (fid, "Y", sched, name, kind, "", title, since, own, control, "N", "1")


def _simple(y, m, last, *filings, **kw):
    """제출분마다 Schedule A 1행씩 붙인 달 묶음. filings: (FilingID, DateSubmitted[, 직원 수])"""
    base = [_base(f[0], f[1], emp=f[2] if len(f) > 2 else "37") for f in filings]
    return _month(y, m, last, base, scha=[_a(f[0], "LEE, KEITH") for f in filings], **kw)


def _fake(monkeypatch, zips, iapd_date=None):
    asked, refreshed = [], []

    def sec_zip(url):
        asked.append(url)
        return zipfile.ZipFile(io.BytesIO(zips[url])) if url in zips else None

    def sec_get(url, kind="json", refresh=False):
        refreshed.append(refresh)
        return web.get(url)
    web = {}
    if iapd_date:
        ia = {"basicInformation": {"advFilingDate": iapd_date}, "brochures": {"brochuredetails": []}}
        web[form_adv.IAPD_FIRM_URL.format(crd=CRD)] = {"hits": {"hits": [{"_source": {"iacontent": json.dumps(ia)}}]}}
    monkeypatch.setattr(form_adv, "sec_zip", sec_zip)
    monkeypatch.setattr(form_adv, "sec_get", sec_get)
    return asked, refreshed


def _july():
    return _month(2026, 7, 31,
                  base=[_base("20", "07/13/2026 01:27:02 PM", emp="30", aum="3000000000"),
                        _base("19", "07/02/2026 09:00:00 AM"), _base("99", "07/14/2026 10:00:00 AM", crd="1056330")],
                  scha=[_a("20", "BROWN, EDDIE, CARL", title="FOUNDER"),
                        _a("20", "BROWN CAPITAL MANAGEMENT HOLDINGS, INC.", kind="DE", title="MEMBER",
                           since="10/2016", own="E"),
                        _a("20", "BROWN CAPITAL MANAGEMENT ESOP TRUST", kind="DE", sched="B"),       # Schedule B 는 뺀다
                        _a("20", "SOMEONE, NEW", since="", own="", control=""),
                        _a("19", "OLD, FILING")],
                  d7=[("20", "Fund A", "805-1"), ("20", "Fund B", "805-2"), ("19", "Fund C", "805-3")])


# ---------- 읽기·매핑 ----------
def test_part1_before_picks_latest_filing_and_maps_schedule_a(monkeypatch):
    _fake(monkeypatch, {_url(2026, 7, 31): _july()})
    got, notes, unavailable = form_adv.part1_before(CRD, "2026-07-31")
    validate(got, AdvPart1)
    assert (got["filed_date"], got["crd"]) == ("2026-07-13", CRD)            # 07-14 는 CRD 앞자리만 같은 다른 회사
    assert got["url"] == _url(2026, 7, 31) + "#FilingID=20"
    assert (got["aum_usd"], got["employees"], got["private_funds"]) == (3_000_000_000.0, 30, 2)
    assert [p["name"] for p in got["people"]] == ["BROWN, EDDIE, CARL", "BROWN CAPITAL MANAGEMENT HOLDINGS, INC.",
                                                  "SOMEONE, NEW"]
    eddie, holdings, new = got["people"]
    assert (eddie["entity_type"], eddie["title"], eddie["since"], eddie["ownership_code"], eddie["is_control_person"]) \
        == ("I", "FOUNDER", "2012-01", "NA", True)
    assert (holdings["entity_type"], holdings["since"], holdings["ownership_code"]) == ("DE", "2016-10", "E")
    assert (new["since"], new["ownership_code"], new["is_control_person"]) == (None, None, None)
    assert unavailable == []


def test_same_day_filings_use_time_and_mixed_date_formats(monkeypatch):
    # 실제로 하루에 두 번 내기도 하고(Akre 2026-03-31 09:46 AM, 06:22 PM), 날짜 형식이 섞여 있다 ("3/17/2025 10:02")
    _fake(monkeypatch, {_url(2026, 3, 31): _simple(2026, 3, 31, ("31", "3/31/2026 18:22"),
                                                   ("30", "03/31/2026 09:46:32 AM"))})
    got, notes, unavailable = form_adv.part1_before(CRD, "2026-03-31")
    assert got["url"].endswith("#FilingID=31") and unavailable == []
    assert any("2건" in s for s in notes)


def test_part1_before_goes_back_month_by_month(monkeypatch):
    zips = {_url(2026, 6, 30): _simple(2026, 6, 30) ,
            _url(2026, 5, 31): _simple(2026, 5, 31, ("5", "05/20/2026 01:00:00 PM"))}
    asked, _ = _fake(monkeypatch, zips)
    got, _, unavailable = form_adv.part1_before(CRD, "2026-06-30")
    assert got["filed_date"] == "2026-05-20" and unavailable == []
    assert asked == [_url(2026, 6, 30), _url(2026, 5, 31)]


def test_unreachable_month_is_unavailable(monkeypatch):
    _fake(monkeypatch, {_url(2026, 5, 31): _simple(2026, 5, 31, ("5", "05/20/2026 01:00:00 PM"))})
    got, _, unavailable = form_adv.part1_before(CRD, "2026-06-30")
    assert got is None and any("2026-06" in u for u in unavailable)           # 6월을 건너뛰고 5월 것을 쓰지 않는다


def test_before_2025_is_unavailable(monkeypatch):
    _fake(monkeypatch, {})
    got, _, unavailable = form_adv.part1_before(CRD, "2024-12-31")
    assert got is None and any("2025년 1월" in u for u in unavailable)


# ---------- CSV 검증: 실제 0 과 확인 불가를 구분 ----------
def test_zero_private_funds_and_zero_employees_are_real_zero(monkeypatch):
    z = _month(2026, 7, 31, base=[_base("20", "07/13/2026 01:27:02 PM", emp="0")], scha=[_a("20", "LEE, KEITH")])
    _fake(monkeypatch, {_url(2026, 7, 31): z})
    got, _, unavailable = form_adv.part1_before(CRD, "2026-07-31")
    assert got["private_funds"] == 0 and got["employees"] == 0 and unavailable == []


@pytest.mark.parametrize("emp,aum,bad", [("", "4536497889", "직원 수"), ("37", "", "운용자산"),
                                         ("-3", "4536497889", "직원 수"), ("37", "nan", "운용자산"),
                                         ("37", "inf", "운용자산"), ("37", "-1", "운용자산"), ("3.5", "1", "직원 수")])
def test_blank_or_invalid_numbers_are_unavailable(monkeypatch, emp, aum, bad):
    z = _month(2026, 7, 31, base=[_base("20", "07/13/2026 01:27:02 PM", emp=emp, aum=aum)], scha=[_a("20", "LEE, K")])
    _fake(monkeypatch, {_url(2026, 7, 31): z})
    got, _, unavailable = form_adv.part1_before(CRD, "2026-07-31")
    validate(got, AdvPart1)
    field = "employees" if bad == "직원 수" else "aum_usd"
    assert got[field] is None and any(bad in u and "확인 불가" in u for u in unavailable)


def test_missing_fund_column_is_unavailable_not_zero(monkeypatch):
    z = _month(2026, 7, 31, base=[_base("20", "07/13/2026 01:27:02 PM")], scha=[_a("20", "LEE, KEITH")],
               d7=[("Fund A", "1")], d7_cols=["Fund Name", "Fund ID"])                  # FilingID 열이 빠짐
    _fake(monkeypatch, {_url(2026, 7, 31): z})
    got, _, unavailable = form_adv.part1_before(CRD, "2026-07-31")
    assert got["private_funds"] is None and any("사모펀드" in u and "FilingID" in u for u in unavailable)


def test_missing_fund_table_is_unavailable(monkeypatch):
    z = _month(2026, 7, 31, base=[_base("20", "07/13/2026 01:27:02 PM")], scha=[_a("20", "LEE, KEITH")],
               skip=("IA_Schedule_D_7B1_",))
    _fake(monkeypatch, {_url(2026, 7, 31): z})
    got, _, unavailable = form_adv.part1_before(CRD, "2026-07-31")
    assert got["private_funds"] is None and any("사모펀드" in u for u in unavailable)


@pytest.mark.parametrize("drop", ["Full Legal Name", "Title or Status", "Schedule", "FilingID"])
def test_missing_schedule_a_column_is_unavailable(monkeypatch, drop):
    cols = [c for c in SCHA_COLS if c != drop]
    rows = [tuple(v for c, v in zip(SCHA_COLS, _a("20", "LEE, KEITH")) if c != drop)]
    z = _month(2026, 7, 31, base=[_base("20", "07/13/2026 01:27:02 PM")], scha=rows, scha_cols=cols)
    _fake(monkeypatch, {_url(2026, 7, 31): z})
    got, _, unavailable = form_adv.part1_before(CRD, "2026-07-31")
    assert got["people"] == [] and any("Schedule A" in u and drop in u for u in unavailable)


def test_old_schedule_column_name_is_accepted(monkeypatch):
    # 2011~2024 묶음은 'Schedule(A/B)' (verified.md 2026-11-15)
    cols = ["Schedule(A/B)" if c == "Schedule" else c for c in SCHA_COLS]
    z = _month(2026, 7, 31, base=[_base("20", "07/13/2026 01:27:02 PM")], scha=[_a("20", "LEE, KEITH")], scha_cols=cols)
    _fake(monkeypatch, {_url(2026, 7, 31): z})
    got, _, unavailable = form_adv.part1_before(CRD, "2026-07-31")
    assert [p["name"] for p in got["people"]] == ["LEE, KEITH"] and unavailable == []


def test_blank_name_makes_whole_list_unavailable(monkeypatch):
    # 이름 없는 사람을 섞어 돌려주면 비교에서 가짜 추가·삭제가 생긴다 → 명단 전체를 확인 불가로
    z = _month(2026, 7, 31, base=[_base("20", "07/13/2026 01:27:02 PM")],
               scha=[_a("20", "LEE, KEITH"), _a("20", "  ")])
    _fake(monkeypatch, {_url(2026, 7, 31): z})
    got, _, unavailable = form_adv.part1_before(CRD, "2026-07-31")
    assert got["people"] == [] and any("이름" in u for u in unavailable)


def test_filing_without_schedule_a_rows_is_unavailable(monkeypatch):
    # 등록 운용사는 Schedule A 가 반드시 있다 → 0행이면 '임원 없음'이 아니라 읽지 못한 것
    _fake(monkeypatch, {_url(2026, 7, 31): _month(2026, 7, 31, base=[_base("20", "07/13/2026 01:27:02 PM")])})
    got, _, unavailable = form_adv.part1_before(CRD, "2026-07-31")
    assert got["people"] == [] and any("Schedule A" in u for u in unavailable)


@pytest.mark.parametrize("drop", ["FilingID", "DateSubmitted", "1E1"])
def test_base_table_missing_column_is_unavailable_without_keyerror(monkeypatch, drop):
    cols = [c for c in BASE_COLS if c != drop]
    rows = [tuple(v for c, v in zip(BASE_COLS, _base("20", "07/13/2026 01:27:02 PM")) if c != drop)]
    _fake(monkeypatch, {_url(2026, 7, 31): _month(2026, 7, 31, base=rows, base_cols=cols)})
    got, _, unavailable = form_adv.part1_before(CRD, "2026-07-31")
    assert got is None and any(drop in u for u in unavailable)


# ---------- 선택이 불확실하면 확인 불가 ----------
def test_unreadable_submitted_date_makes_choice_uncertain(monkeypatch):
    # 대상 운용사의 제출일을 못 읽은 행이 있으면 그게 더 늦은 제출분일 수 있다 → 더 오래된 것으로 확정하지 않는다
    _fake(monkeypatch, {_url(2026, 7, 31): _simple(2026, 7, 31, ("20", "07/13/2026 01:27:02 PM"), ("21", "곧 냄"))})
    got, _, unavailable = form_adv.part1_before(CRD, "2026-07-31")
    assert got is None and any("21" in u and "확인 불가" in u for u in unavailable)


def test_unreadable_row_in_newer_month_stops_going_back(monkeypatch):
    zips = {_url(2026, 7, 31): _simple(2026, 7, 31, ("21", "")),
            _url(2026, 6, 30): _simple(2026, 6, 30, ("15", "06/10/2026 01:00:00 PM"))}
    _fake(monkeypatch, zips)
    got, _, unavailable = form_adv.part1_before(CRD, "2026-07-31")
    assert got is None and unavailable


def test_blank_filing_id_is_uncertain(monkeypatch):
    _fake(monkeypatch, {_url(2026, 7, 31): _simple(2026, 7, 31, ("20", "07/13/2026 01:27:02 PM"),
                                                   ("", "07/20/2026 01:00:00 PM"))})
    got, _, unavailable = form_adv.part1_before(CRD, "2026-07-31")
    assert got is None and any("FilingID" in u for u in unavailable)


def test_same_timestamp_tie_is_uncertain(monkeypatch):
    _fake(monkeypatch, {_url(2026, 7, 31): _simple(2026, 7, 31, ("20", "7/13/2026 13:27"), ("21", "7/13/2026 13:27"))})
    got, _, unavailable = form_adv.part1_before(CRD, "2026-07-31")
    assert got is None and any("같은 시각" in u for u in unavailable)


# ---------- collect_adv1: 최신본·직전본 ----------
def test_collect_adv1_new_from_iapd_date_and_old_before_last_check(monkeypatch):
    zips = {_url(2026, 7, 31): _july(),
            _url(2026, 6, 30): _simple(2026, 6, 30, ("15", "06/10/2026 01:00:00 PM", "40"))}
    _, refreshed = _fake(monkeypatch, zips, iapd_date="07/13/2026")
    new, old, notes, unavailable = form_adv.collect_adv1(CRD, "2026-06-30")
    validate(new, AdvPart1)
    validate(old, AdvPart1)
    assert new["filed_date"] == "2026-07-13" and new["url"] == _url(2026, 7, 31) + "#FilingID=20"   # 실제로 읽은 묶음
    assert (old["filed_date"], old["employees"]) == ("2026-06-10", 40)
    assert old["url"] == _url(2026, 6, 30) + "#FilingID=15" and unavailable == []
    assert refreshed == [True]                                    # IAPD 제출 목록은 저장본이 있어도 새로 받는다


def test_collect_adv1_latest_before_last_check_is_its_own_previous(monkeypatch):
    asked, _ = _fake(monkeypatch, {_url(2026, 3, 31): _simple(2026, 3, 31, ("3", "03/31/2026 09:00:00 AM"))},
                     iapd_date="03/31/2026")
    new, old, _, unavailable = form_adv.collect_adv1(CRD, "2026-06-30")
    assert old == new and old is not new and old["people"] is not new["people"]
    assert unavailable == []
    assert asked == [_url(2026, 3, 31), _url(2026, 4, 30)]       # 최신본 확인용으로 다음 달까지만 본다(없음 = 아직 미공개)


def test_no_last_check_picks_previous_filing_even_same_day(monkeypatch):
    z = _simple(2026, 3, 31, ("2087577", "03/30/2026 03:14:12 PM"), ("2088634", "03/31/2026 09:46:32 AM"),
                ("2089978", "03/31/2026 06:22:16 PM"))
    _fake(monkeypatch, {_url(2026, 3, 31): z}, iapd_date="03/31/2026")
    new, old, _, unavailable = form_adv.collect_adv1(CRD, None)
    assert new["url"].endswith("#FilingID=2089978") and old["url"].endswith("#FilingID=2088634")
    assert old["filed_date"] == new["filed_date"] == "2026-03-31" and unavailable == []


def test_missing_latest_month_still_returns_previous(monkeypatch):
    # 최신 제출(11월)의 월별 자료가 아직 없어도, 직전 점검일 기준 직전본은 읽을 수 있으면 돌려준다
    _fake(monkeypatch, {_url(2026, 6, 30): _simple(2026, 6, 30, ("15", "06/10/2026 01:00:00 PM"))},
          iapd_date="11/05/2026")
    new, old, _, unavailable = form_adv.collect_adv1(CRD, "2026-06-30")
    assert new is None and old["filed_date"] == "2026-06-10"
    assert any("최신본" in u and "2026-11" in u for u in unavailable)


def test_stale_iapd_cache_uses_later_filing_in_monthly_data(monkeypatch):
    # IAPD 저장본은 06-04 라는데 월별 자료에 07-13 제출분이 있으면 저장본이 오래된 것
    zips = {_url(2026, 6, 30): _simple(2026, 6, 30, ("15", "06/04/2026 01:00:00 PM")),
            _url(2026, 7, 31): _simple(2026, 7, 31, ("20", "07/13/2026 01:27:02 PM"))}
    _fake(monkeypatch, zips, iapd_date="06/04/2026")
    new, old, notes, unavailable = form_adv.collect_adv1(CRD, "2026-06-30")
    assert new["filed_date"] == "2026-07-13" and old["filed_date"] == "2026-06-04"
    assert any("IAPD" in s and "2026-06-04" in s for s in notes) and unavailable == []


def test_iapd_date_missing_from_monthly_data_is_unavailable(monkeypatch):
    # IAPD 는 07-13 제출이라는데 7월 묶음에 없으면, 더 오래된 걸 최신본이라고 하지 않는다
    _fake(monkeypatch, {_url(2026, 7, 31): _simple(2026, 7, 31, ("19", "07/02/2026 09:00:00 AM"))},
          iapd_date="07/13/2026")
    new, old, _, unavailable = form_adv.collect_adv1(CRD, "2026-06-30")
    assert new is None and any("2026-07-13" in u for u in unavailable)


def test_collect_adv1_no_iapd_still_tries_previous(monkeypatch):
    _fake(monkeypatch, {_url(2026, 6, 30): _simple(2026, 6, 30, ("15", "06/10/2026 01:00:00 PM"))})
    new, old, _, unavailable = form_adv.collect_adv1(CRD, "2026-06-30")
    assert new is None and old["filed_date"] == "2026-06-10" and any("IAPD" in u for u in unavailable)


def test_no_iapd_and_no_last_check_is_unavailable(monkeypatch):
    _fake(monkeypatch, {})
    new, old, _, unavailable = form_adv.collect_adv1(CRD, None)
    assert new is None and old is None and len(unavailable) == 2
