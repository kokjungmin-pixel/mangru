"""13F 분기 수집 조립 테스트 (B3-1·2·6). 네트워크 없이 주소별 가짜 응답으로."""
from src.collect import form13f
from src.state import QuarterHoldings
from src.validate import validate
from tests.collect.test_form13f import NS, _cover, _row

CIK = "0001112520"
SUB = f"https://data.sec.gov/submissions/CIK{CIK}.json"


def _folder(acc):
    return f"https://www.sec.gov/Archives/edgar/data/1112520/{acc.replace('-', '')}"


def _table(*rows):
    return (f'<?xml version="1.0"?><informationTable xmlns="{NS}">' + "".join(rows)
            + "</informationTable>").encode("utf-8")


def _cover_n(amend, n):
    return _cover(amend).replace(b"</coverPage>", f"</coverPage><summaryPage><tableEntryTotal>{n}"
                                 "</tableEntryTotal></summaryPage>".encode())


def _filing(web, acc, cover, table, xml_name="infotable.xml"):
    web[_folder(acc) + "/index.json"] = {"directory": {"item": [{"name": "primary_doc.xml"}, {"name": xml_name}]}}
    web[_folder(acc) + "/primary_doc.xml"] = cover
    web[_folder(acc) + "/" + xml_name] = table


def _web():
    web = {SUB: {"filings": {"recent": {
        "form":            ["13F-HR",     "13F-HR/A",   "13F-HR",     "13F-NT",     "13F-HR",     "10-K"],
        "reportDate":      ["2024-06-30", "2024-03-31", "2024-03-31", "2023-12-31", "2023-12-31", ""],
        "filingDate":      ["2024-08-14", "2024-05-23", "2024-05-13", "2024-02-14", "2024-02-14", "2024-03-01"],
        "accessionNumber": ["a-24-3",     "a-24-2",     "a-24-1",     "a-24-0",     "a-23-9",     "x"],
    }}}}
    a, b = _row("AAA INC", "000000AA1", 1000, 10), _row("BBB CORP", "000000BB2", 3000, 30)
    _filing(web, "a-24-1", _cover_n(None, 1), _table(a))
    _filing(web, "a-24-2", _cover_n("NEW HOLDINGS", 2), _table(a, b), xml_name="inftable3.xml")  # 원본 재기재 + 1종목
    _filing(web, "a-24-3", _cover_n(None, 3), _table(a, b))                                       # 표지 3행인데 2행
    return web


def _run(monkeypatch, web, n=2):
    calls = []
    monkeypatch.setattr(form13f, "sec_get", lambda url, kind="json": web.get(url))
    monkeypatch.setattr(form13f, "enrich_cusips", lambda cusips, as_of: (calls.append((tuple(cusips), as_of)) or {
        "000000AA1": {"ticker": "AAA", "issuer_cik": "0000000001", "sic": "3571", "shares_outstanding": 1e6,
                      "shares_outstanding_partial": False, "is_etf": False}}))
    return form13f.collect_13f(CIK, n), calls


def test_picks_latest_quarters_and_builds_quarter_holdings(monkeypatch):
    (quarters, notes, unavailable), calls = _run(monkeypatch, _web())
    assert [q["period"] for q in quarters] == ["2024Q1", "2024Q2"]          # 오래된 → 최신, 13F-NT·10-K 제외
    q1 = quarters[0]
    assert (q1["report_date"], q1["filed_date"], q1["accession"]) == ("2024-03-31", "2024-05-13", "a-24-1")
    assert q1["url"] == _folder("a-24-1") + "/"
    assert [h["cusip"] for h in q1["holdings"]] == ["000000AA1", "000000BB2"]
    assert q1["holdings"][0]["value_usd"] == 1000.0                         # 2023-01-03 이후 제출 → 달러 그대로
    assert q1["holdings"][0]["ticker"] == "AAA" and q1["holdings"][0]["sic"] == "3571"
    assert q1["holdings"][1]["ticker"] is None and q1["holdings"][1]["is_etf"] is False   # 못 찾은 종목
    for q in quarters:
        validate(q, QuarterHoldings)
    assert calls[0] == (("000000AA1", "000000BB2"), "2024-03-31")           # 분기 말일로 종목 식별
    assert any("겹친 1건 제외" in s for s in notes)
    assert any("a-24-3" in s and "3" in s and "2" in s for s in notes)       # 표지 행 수와 다름
    assert unavailable == []


def test_quarter_with_unreachable_filing_is_unavailable(monkeypatch):
    web = _web()
    del web[_folder("a-24-3") + "/index.json"]
    (quarters, notes, unavailable), _ = _run(monkeypatch, web)
    assert [q["period"] for q in quarters] == ["2024Q1"]
    assert any("2024Q2" in s for s in unavailable)


def test_no_submissions_is_unavailable_and_fewer_quarters_noted(monkeypatch):
    (quarters, _, unavailable), _ = _run(monkeypatch, {})
    assert quarters == [] and len(unavailable) == 1
    (quarters, notes, _), _ = _run(monkeypatch, _web(), n=14)
    assert len(quarters) == 2 and any("3개" in s for s in notes)          # 목록엔 3개, 2023Q4 는 응답 없음


def test_missing_original_with_only_new_holdings_is_unavailable(monkeypatch):
    web = _web()
    del web[_folder("a-24-1") + "/index.json"]                 # 2024Q1 원본을 못 받음, 정정본만 받음
    (quarters, _, unavailable), _ = _run(monkeypatch, web)
    assert [q["period"] for q in quarters] == ["2024Q2"]
    assert any("2024Q1" in s and "원본" in s for s in unavailable)


def test_unreachable_info_table_drops_filing(monkeypatch):
    web = _web()
    del web[_folder("a-24-3") + "/infotable.xml"]               # 표지는 받았는데 정보표를 못 받음
    (quarters, notes, unavailable), _ = _run(monkeypatch, web)
    assert [q["period"] for q in quarters] == ["2024Q1"]
    assert any("2024Q2" in s for s in unavailable)
    assert any("a-24-3" in s and "정보표" in s for s in notes)
