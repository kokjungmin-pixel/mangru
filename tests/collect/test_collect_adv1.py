"""ADV Part 1(운용자산·직원·사모펀드 수·Schedule A) 수집 테스트 (B3). 월별 Part 1 묶음(CSV)을 가짜로 만든다.
열 이름·값 모양은 실제 2026-03·06·07 묶음 그대로 (docs/verified.md 2026-11-22)."""
import csv
import io
import json
import zipfile

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


def _month(y, m, last, base, scha=(), d7=(), skip=()):
    tag = f"{y}{m:02d}01_{y}{m:02d}{last}"
    files = {f"IA_ADV_Base_A_{tag}.csv": _csv(BASE_COLS, base),
             f"IA_ADV_Base_B_{tag}.csv": _csv(["FilingID"], []),
             f"IA_Schedule_A_B_{tag}.csv": _csv(SCHA_COLS, scha),
             f"IA_Schedule_D_7B1_{tag}.csv": _csv(D7_COLS, d7),
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


def _fake(monkeypatch, zips, iapd_date=None):
    asked = []

    def sec_zip(url):
        asked.append(url)
        return zipfile.ZipFile(io.BytesIO(zips[url])) if url in zips else None
    web = {}
    if iapd_date:
        ia = {"basicInformation": {"advFilingDate": iapd_date}, "brochures": {"brochuredetails": []}}
        web[form_adv.IAPD_FIRM_URL.format(crd=CRD)] = {"hits": {"hits": [{"_source": {"iacontent": json.dumps(ia)}}]}}
    monkeypatch.setattr(form_adv, "sec_zip", sec_zip)
    monkeypatch.setattr(form_adv, "sec_get", lambda url, kind="json": web.get(url))
    return asked


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
    z = _month(2026, 3, 31, base=[_base("31", "3/31/2026 18:22"), _base("30", "03/31/2026 09:46:32 AM"),
                                  _base("29", "날짜 없음")])
    _fake(monkeypatch, {_url(2026, 3, 31): z})
    got, notes, _ = form_adv.part1_before(CRD, "2026-03-31")
    assert got["url"].endswith("#FilingID=31")
    assert any("29" in s and "제출일" in s for s in notes)                    # 읽지 못한 제출일은 기록하고 뺀다


def test_part1_before_goes_back_month_by_month(monkeypatch):
    zips = {_url(2026, 6, 30): _month(2026, 6, 30, base=[_base("1", "06/01/2026 01:00:00 PM", crd="999")]),
            _url(2026, 5, 31): _month(2026, 5, 31, base=[_base("5", "05/20/2026 01:00:00 PM")],
                                      scha=[_a("5", "LEE, KEITH")])}
    asked = _fake(monkeypatch, zips)
    got, _, unavailable = form_adv.part1_before(CRD, "2026-06-30")
    assert got["filed_date"] == "2026-05-20" and unavailable == []
    assert asked == [_url(2026, 6, 30), _url(2026, 5, 31)]


def test_unreachable_month_is_unavailable(monkeypatch):
    _fake(monkeypatch, {_url(2026, 5, 31): _month(2026, 5, 31, base=[_base("5", "05/20/2026 01:00:00 PM")])})
    got, _, unavailable = form_adv.part1_before(CRD, "2026-06-30")
    assert got is None and any("2026-06" in u for u in unavailable)           # 6월을 건너뛰고 5월 것을 쓰지 않는다


def test_before_2025_is_unavailable(monkeypatch):
    _fake(monkeypatch, {})
    got, _, unavailable = form_adv.part1_before(CRD, "2024-12-31")
    assert got is None and any("2025년 1월" in u for u in unavailable)


def test_missing_schedule_tables_are_unavailable_not_empty(monkeypatch):
    z = _month(2026, 7, 31, base=[_base("20", "07/13/2026 01:27:02 PM")],
               skip=("IA_Schedule_A_B", "IA_Schedule_D_7B1_"))
    _fake(monkeypatch, {_url(2026, 7, 31): z})
    got, _, unavailable = form_adv.part1_before(CRD, "2026-07-31")
    validate(got, AdvPart1)
    assert got["people"] == [] and got["private_funds"] is None
    assert any("Schedule A" in u for u in unavailable) and any("사모펀드" in u for u in unavailable)


def test_filing_without_schedule_a_rows_is_unavailable(monkeypatch):
    # 등록 운용사는 Schedule A 가 반드시 있다 → 0행이면 '임원 없음'이 아니라 읽지 못한 것
    _fake(monkeypatch, {_url(2026, 7, 31): _month(2026, 7, 31, base=[_base("20", "07/13/2026 01:27:02 PM")])})
    got, _, unavailable = form_adv.part1_before(CRD, "2026-07-31")
    assert got["people"] == [] and any("Schedule A" in u for u in unavailable)


def test_blank_numbers_are_none(monkeypatch):
    z = _month(2026, 7, 31, base=[_base("20", "07/13/2026 01:27:02 PM", emp="", aum="")])
    _fake(monkeypatch, {_url(2026, 7, 31): z})
    got, _, _ = form_adv.part1_before(CRD, "2026-07-31")
    assert got["aum_usd"] is None and got["employees"] is None and got["private_funds"] == 0


def test_collect_adv1_new_from_iapd_date_and_old_before_last_check(monkeypatch):
    zips = {_url(2026, 7, 31): _july(),
            _url(2026, 6, 30): _month(2026, 6, 30, base=[_base("15", "06/10/2026 01:00:00 PM", emp="40")],
                                      scha=[_a("15", "LEE, KEITH")])}
    _fake(monkeypatch, zips, iapd_date="07/13/2026")
    new, old, notes, unavailable = form_adv.collect_adv1(CRD, "2026-06-30")
    validate(new, AdvPart1)
    validate(old, AdvPart1)
    assert new["filed_date"] == "2026-07-13" and new["url"] == form_adv.ADV_PDF_URL.format(crd=CRD)
    assert (old["filed_date"], old["employees"]) == ("2026-06-10", 40) and unavailable == []


def test_collect_adv1_latest_before_last_check_is_its_own_previous(monkeypatch):
    z = _month(2026, 3, 31, base=[_base("3", "03/31/2026 09:00:00 AM")], scha=[_a("3", "LEE, KEITH")])
    asked = _fake(monkeypatch, {_url(2026, 3, 31): z}, iapd_date="03/31/2026")
    new, old, _, unavailable = form_adv.collect_adv1(CRD, "2026-06-30")
    assert old == new and old is not new and old["people"] is not new["people"]
    assert asked == [_url(2026, 3, 31)] and unavailable == []


def test_iapd_date_missing_from_monthly_data_is_unavailable(monkeypatch):
    # IAPD 는 07-13 제출이라는데 7월 묶음에 없으면, 더 오래된 걸 최신본이라고 하지 않는다
    _fake(monkeypatch, {_url(2026, 7, 31): _month(2026, 7, 31, base=[_base("19", "07/02/2026 09:00:00 AM")])},
          iapd_date="07/13/2026")
    new, old, _, unavailable = form_adv.collect_adv1(CRD, "2026-06-30")
    assert new is None and old is None and any("2026-07-13" in u for u in unavailable)


def test_collect_adv1_no_iapd(monkeypatch):
    _fake(monkeypatch, {})
    new, old, _, unavailable = form_adv.collect_adv1(CRD, "2026-06-30")
    assert new is None and old is None and any("IAPD" in u for u in unavailable)
