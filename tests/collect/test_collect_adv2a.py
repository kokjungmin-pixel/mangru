"""ADV Part 2A 브로셔 받기·AdvPart2A 조립 테스트 (B3). 네트워크 없이 주소별 가짜 응답으로."""
import io
import json
import zipfile

from src.collect import form_adv
from src.state import AdvPart2A
from src.validate import validate
from tests.collect.test_form_adv import BODY_4, BODY_8, BODY_9, COVER

CRD = "105633"
Z = "https://reports.adviserinfo.sec.gov/reports/foia/advBrochures/{y}/ADV_Brochures_{y}_{m}.zip"
IAPD = form_adv.IAPD_FIRM_URL.format(crd=CRD)
PAGES = [COVER, "Item 2. Material Changes\nItem 4.E was amended.", BODY_4 + "\n" + BODY_8 + "\n" + BODY_9]


def _zip(*names):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in names:
            z.writestr(n, f"%PDF {n}".encode())
    return buf.getvalue()


def _fake(monkeypatch, zips, web=None):
    asked = []

    def sec_zip(url):
        asked.append(url)
        return zipfile.ZipFile(io.BytesIO(zips[url])) if url in zips else None
    monkeypatch.setattr(form_adv, "sec_zip", sec_zip)
    monkeypatch.setattr(form_adv, "sec_get", lambda url, kind="json", refresh=False: (web or {}).get(url))
    monkeypatch.setattr(form_adv, "_pdf_pages", lambda pdf: PAGES)
    return asked


def test_brochure_before_picks_latest_on_or_before_as_of(monkeypatch):
    zips = {Z.format(y=2026, m="June"): _zip("999999_1_1_20260601.pdf"),
            Z.format(y=2026, m="May"): _zip("1056330_1_1_20260512.pdf"),          # CRD 앞자리만 같은 다른 회사
            Z.format(y=2026, m="April"): _zip(f"{CRD}_77_2_20260410.pdf", f"{CRD}_77_1_20260402.pdf"),
            Z.format(y=2026, m="March_1_of_2"): _zip(f"{CRD}_77_1_20260328.pdf")}
    asked = _fake(monkeypatch, zips)
    got, notes, unavailable = form_adv.brochure_before(CRD, "2026-06-30")
    assert got["filed_date"] == "2026-04-10" and got["pdf"] == f"%PDF {CRD}_77_2_20260410.pdf".encode()
    assert got["url"] == Z.format(y=2026, m="April") + f"#{CRD}_77_2_20260410.pdf"
    assert unavailable == [] and not any("March" in u for u in asked)    # 찾으면 더 거슬러 가지 않는다
    assert any("2개" in s for s in notes)                                 # 같은 달에 다시 낸 브로셔


def test_brochure_before_skips_files_after_as_of_in_same_month(monkeypatch):
    _fake(monkeypatch, {Z.format(y=2026, m="June"): _zip(f"{CRD}_77_3_20260620.pdf", f"{CRD}_77_2_20260605.pdf")})
    got, _, _ = form_adv.brochure_before(CRD, "2026-06-15")
    assert got["filed_date"] == "2026-06-05"


def test_brochure_before_reads_split_march(monkeypatch):
    zips = {Z.format(y=2026, m="March_1_of_2"): _zip("1_1_1_20260301.pdf"),
            Z.format(y=2026, m="March_2_of_2"): _zip(f"{CRD}_77_1_20260330.pdf")}
    _fake(monkeypatch, zips)
    got, _, _ = form_adv.brochure_before(CRD, "2026-03-31")
    assert got["filed_date"] == "2026-03-30"
    assert got["url"] == Z.format(y=2026, m="March_2_of_2") + f"#{CRD}_77_1_20260330.pdf"   # 실제로 들어 있던 묶음


def test_unreachable_month_stops_with_unavailable(monkeypatch):
    # 5월 묶음을 못 받았는데 4월 것을 쓰면, 5월에 낸 직전본을 건너뛴 채 더 오래된 걸 비교하게 된다
    zips = {Z.format(y=2026, m="June"): _zip("1_1_1_20260601.pdf"),
            Z.format(y=2026, m="April"): _zip(f"{CRD}_77_1_20260410.pdf")}
    _fake(monkeypatch, zips)
    got, _, unavailable = form_adv.brochure_before(CRD, "2026-06-30")
    assert got is None and any("2026-05" in u for u in unavailable)


def test_before_2025_is_unavailable(monkeypatch):
    _fake(monkeypatch, {Z.format(y=2025, m="February"): _zip("1_1_1_20250210.pdf"),
                        Z.format(y=2025, m="January"): _zip("1_1_1_20250110.pdf")})
    got, _, unavailable = form_adv.brochure_before(CRD, "2025-02-28")
    assert got is None and any("2025년 1월" in u for u in unavailable)
    got, _, unavailable = form_adv.brochure_before(CRD, "2024-12-31")
    assert got is None and len(unavailable) == 1


def test_parse_brochure_builds_adv_part2a(monkeypatch):
    monkeypatch.setattr(form_adv, "_pdf_pages", lambda pdf: PAGES)
    part, unavailable = form_adv.parse_brochure(b"%PDF", "2026-07-13", "https://x/b.pdf")
    validate(part, AdvPart2A)
    assert set(part["items"]) == {"2", "8", "9"} and part["pages"] == {"2": 2, "8": 3, "9": 3}
    assert part["items"]["8"].startswith("We buy and hold") and unavailable == []
    monkeypatch.setattr(form_adv, "_pdf_pages", lambda pdf: PAGES[:2])     # Item 8·9 제목 없음
    part, unavailable = form_adv.parse_brochure(b"%PDF", "2026-07-13", "https://x/b.pdf")
    assert set(part["items"]) == {"2"} and any("Item 8" in u for u in unavailable)
    assert not any("Item 9" in u for u in unavailable)                        # 9는 찾으면 넣을 뿐


def test_parse_brochure_unreadable_pdf():
    part, unavailable = form_adv.parse_brochure(b"not a pdf", "2026-07-13", "https://x/b.pdf")
    assert part is None and any("PDF" in u for u in unavailable)


def _iapd(*details):
    return {"hits": {"hits": [{"_source": {"iacontent": json.dumps({"brochures": {"brochuredetails": list(details)}})}}]}}


def test_collect_adv2a_new_and_old(monkeypatch):
    new_url = form_adv.BROCHURE_URL.format(vid=1051519)
    web = {IAPD: _iapd({"brochureVersionID": 900, "brochureName": "OLD", "dateSubmitted": "3/28/2026"},
                       {"brochureVersionID": 1051519, "brochureName": "BCM", "dateSubmitted": "7/13/2026"}),
           new_url: b"%PDF new"}
    _fake(monkeypatch, {Z.format(y=2026, m="June"): _zip(f"{CRD}_77_1_20260605.pdf")}, web)
    new, old, notes, unavailable = form_adv.collect_adv2a(CRD, "2026-06-30")
    validate(new, AdvPart2A)
    validate(old, AdvPart2A)
    assert (new["filed_date"], new["url"]) == ("2026-07-13", new_url)
    assert old["filed_date"] == "2026-06-05" and unavailable == []
    assert any("IAPD 브로셔 2개" in s for s in notes)                         # 브로셔가 여럿이면 기록


def test_collect_adv2a_without_last_check_uses_version_before_latest(monkeypatch):
    new_url = form_adv.BROCHURE_URL.format(vid=5)
    web = {IAPD: _iapd({"brochureVersionID": 5, "brochureName": "B", "dateSubmitted": "6/5/2026"}), new_url: b"%PDF"}
    _fake(monkeypatch, {Z.format(y=2026, m="June"): _zip(f"{CRD}_77_2_20260605.pdf", f"{CRD}_77_1_20260601.pdf")}, web)
    new, old, _, _ = form_adv.collect_adv2a(CRD, None)
    assert new["filed_date"] == "2026-06-05" and old["filed_date"] == "2026-06-01"


def test_collect_adv2a_no_iapd(monkeypatch):
    _fake(monkeypatch, {})
    new, old, _, unavailable = form_adv.collect_adv2a(CRD, "2026-06-30")
    assert new is None and old is None and any("최신" in u for u in unavailable)


def test_latest_filed_before_last_check_is_its_own_previous(monkeypatch):
    # Akre·Warburg 06-30 기준: 최신본(03-31)이 직전 점검일 전 → 직전본은 최신본 그 자체. 묶음을 찾지 않는다
    new_url = form_adv.BROCHURE_URL.format(vid=7)
    web = {IAPD: _iapd({"brochureVersionID": 7, "brochureName": "B", "dateSubmitted": "3/31/2026"}), new_url: b"%PDF"}
    asked = _fake(monkeypatch, {}, web)                        # 묶음은 하나도 없음 (예: 아직 안 올라온 달)
    new, old, _, unavailable = form_adv.collect_adv2a(CRD, "2026-10-31")
    assert asked == [] and unavailable == []
    assert old == new and old is not new and old["items"] is not new["items"]   # B4 가 고쳐도 서로 안 번지게


def test_broken_member_in_zip_is_unavailable_not_exception(monkeypatch):
    class BadZip:
        def namelist(self):
            return [f"{CRD}_77_1_20260605.pdf"]

        def read(self, name):
            raise EOFError("Compressed file ended before the end-of-stream marker was reached")
    monkeypatch.setattr(form_adv, "_month_zips", lambda y, mo: [("https://z/June.zip", BadZip())])
    got, _, unavailable = form_adv.brochure_before(CRD, "2026-06-30")
    assert got is None and any("EOFError" in u for u in unavailable)


def test_same_day_brochures_compare_ids_as_numbers(monkeypatch):
    _fake(monkeypatch, {Z.format(y=2026, m="June"): _zip(f"{CRD}_99999_1_20260605.pdf", f"{CRD}_100000_1_20260605.pdf")})
    got, _, _ = form_adv.brochure_before(CRD, "2026-06-30")
    assert got["url"].endswith(f"{CRD}_100000_1_20260605.pdf")


def test_uppercase_pdf_extension_is_found(monkeypatch):
    _fake(monkeypatch, {Z.format(y=2026, m="June"): _zip(f"{CRD}_77_1_20260605.PDF", f"{CRD}_77_x_20260606.pdf")})
    got, _, unavailable = form_adv.brochure_before(CRD, "2026-06-30")
    assert got["filed_date"] == "2026-06-05" and unavailable == []        # 버전이 숫자가 아닌 이름은 건너뜀
