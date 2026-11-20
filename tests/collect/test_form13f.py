"""13F 정보표 읽기·정리 테스트 (B7 첫 줄). 가짜 XML: 종목 5개 + 옵션 1줄 + PRN 1줄 + 같은 CUSIP 2줄."""
from src.collect.form13f import clean_rows, parse_infotable

NS = "http://www.sec.gov/edgar/document/thirteenf/informationtable"


def _row(name, cusip, value, shares, kind="SH", put_call=None, title="COM"):
    pc = f"<putCall>{put_call}</putCall>" if put_call else ""
    return (f"<infoTable><nameOfIssuer>{name}</nameOfIssuer><titleOfClass>{title}</titleOfClass>"
            f"<cusip>{cusip}</cusip><value>{value}</value>"
            f"<shrsOrPrnAmt><sshPrnamt>{shares}</sshPrnamt><sshPrnamtType>{kind}</sshPrnamtType></shrsOrPrnAmt>"
            f"{pc}</infoTable>")


FAKE_XML = (f'<?xml version="1.0"?><informationTable xmlns="{NS}">'
            + _row("AAA INC", "000000aa1", 1000, 10)
            + _row("BBB CORP", "000000BB2", 2000, 20)
            + _row("CCC CO", "000000CC3", 3000, 30)
            + _row("DDD INC", "000000DD4", 4000, 40, title="SPONSORED ADR")
            + _row("EEE INC", "000000EE5", 5000, 50)
            + _row("AAA INC", "000000AA1", 500, 5)                 # 같은 CUSIP 두 번째 줄
            + _row("BBB CORP", "000000BB2", 999, 9, put_call="Call")  # 옵션
            + _row("FFF NOTE", "000000FF6", 777, 7000, kind="PRN")  # 원금
            + "</informationTable>").encode("utf-8")


def test_parse_reads_namespaced_tags():
    rows = parse_infotable(FAKE_XML)
    assert len(rows) == 8
    assert rows[0] == {"issuer": "AAA INC", "title_of_class": "COM", "cusip": "000000AA1",
                       "value": 1000.0, "shares": 10.0, "share_type": "SH", "put_call": None}
    assert rows[6]["put_call"] == "Call"


def test_clean_drops_options_and_prn_and_merges_cusip():
    rows = clean_rows(parse_infotable(FAKE_XML))
    by = {r["cusip"]: r for r in rows}
    assert set(by) == {"000000AA1", "000000BB2", "000000CC3", "000000DD4", "000000EE5"}
    assert by["000000AA1"]["value"] == 1500.0 and by["000000AA1"]["shares"] == 15.0
    assert by["000000BB2"]["value"] == 2000.0          # 옵션 줄은 더하지 않음


# ---- 금액 단위 (B3-5, B7 둘째 줄): 2023-01-03 이후 제출은 달러, 그 전은 천 달러 ----
from src.collect.form13f import to_usd

_K_ROWS = [{"cusip": "A", "value": 50.0, "shares": 1000.0},     # 천 달러 단위: 50 → $50,000, 주가 $50
           {"cusip": "B", "value": 20.0, "shares": 100.0}]       # $20,000, 주가 $200


def test_to_usd_multiplies_before_2023_01_03():
    rows, note = to_usd(_K_ROWS, "2022-11-14")
    assert [r["value"] for r in rows] == [50000.0, 20000.0]
    assert note is None
    assert _K_ROWS[0]["value"] == 50.0                            # 입력은 바꾸지 않음


def test_to_usd_keeps_dollars_from_2023_01_03():
    usd = [{"cusip": "A", "value": 50000.0, "shares": 1000.0}]
    for filed in ("2023-01-03", "2023-02-14"):
        rows, note = to_usd(usd, filed)
        assert rows[0]["value"] == 50000.0 and note is None


def test_to_usd_notes_when_median_price_out_of_range():
    # 2023년 이후 제출인데 천 달러 단위로 적힌 경우 → 주가 중앙값 $0.05·$0.2 → 범위 밖
    rows, note = to_usd(_K_ROWS, "2023-02-14")
    assert rows[0]["value"] == 50.0
    assert note is not None and "2023-02-14" in note


def test_to_usd_empty_or_zero_shares_no_note():
    assert to_usd([], "2022-11-14") == ([], None)
    rows, note = to_usd([{"cusip": "A", "value": 5.0, "shares": 0.0}], "2022-11-14")
    assert rows[0]["value"] == 5000.0 and note is None


# ---- 정정본 (B3-4, B7 셋째 줄). 태그 모양은 docs/verified.md 2026-11-21 (실제 19건) ----
from src.collect.form13f import amendment_type, apply_amendments

_COVER_NS = "http://www.sec.gov/edgar/thirteenffiler"


def _cover(amend: str | None) -> bytes:
    info = (f"<amendmentInfo><amendmentType>{amend}</amendmentType>"
            "<confDeniedExpired>false</confDeniedExpired></amendmentInfo>") if amend else ""
    return (f'<edgarSubmission xmlns="{_COVER_NS}"><formData><coverPage>'
            f"<reportCalendarOrQuarter>12-31-2023</reportCalendarOrQuarter>"
            f"<isAmendment>{'true' if amend else 'false'}</isAmendment>{info}"
            "</coverPage></formData></edgarSubmission>").encode("utf-8")


def test_amendment_type_reads_cover():
    assert amendment_type(_cover("RESTATEMENT")) == "RESTATEMENT"
    assert amendment_type(_cover("NEW HOLDINGS")) == "NEW HOLDINGS"
    assert amendment_type(_cover(None)) is None


def _f(acc, filed, kind, cusips, form=None):
    form = form or ("13F-HR" if kind is None else "13F-HR/A")
    return {"accession": acc, "form": form, "filed_date": filed, "amendment_type": kind,
            "rows": [{"cusip": c, "value": 1.0, "shares": 1.0} for c in cusips]}


def test_restatement_replaces_original_and_is_noted():
    rows, base, notes = apply_amendments([_f("orig", "2024-02-10", None, ["A", "B"]),
                                          _f("amd1", "2024-02-20", "RESTATEMENT", ["A", "C"])])
    assert [r["cusip"] for r in rows] == ["A", "C"]
    assert base["accession"] == "amd1"
    assert len(notes) == 1 and "amd1" in notes[0] and "전체 대체" in notes[0]


def test_new_holdings_adds_to_original():
    rows, base, notes = apply_amendments([_f("orig", "2022-05-13", None, ["A"]),
                                          _f("amd1", "2022-05-16", "NEW HOLDINGS", ["B", "C"])])
    assert [r["cusip"] for r in rows] == ["A", "B", "C"]
    assert base["accession"] == "orig"
    assert len(notes) == 1 and "amd1" in notes[0] and "추가" in notes[0]


def test_several_amendments_apply_in_filing_order():
    # 순서를 섞어 넣어도 제출일 순으로: 원본 → #1 → #2 (Polen 2023-12-31 사례 모양)
    rows, base, _ = apply_amendments([_f("amd2", "2024-05-10", "RESTATEMENT", ["Z"]),
                                      _f("orig", "2024-02-14", None, ["A"]),
                                      _f("amd1", "2024-02-20", "RESTATEMENT", ["Y"])])
    assert [r["cusip"] for r in rows] == ["Z"] and base["accession"] == "amd2"


def test_empty_restatement_and_unknown_type_are_skipped_with_note():
    rows, base, notes = apply_amendments([_f("orig", "2024-02-14", None, ["A"]),
                                          _f("amd1", "2024-02-20", "RESTATEMENT", []),
                                          _f("amd2", "2024-03-01", None, ["X"], form="13F-HR/A")])   # 유형을 못 읽은 정정본
    assert [r["cusip"] for r in rows] == ["A"] and base["accession"] == "orig"
    assert len(notes) == 2
