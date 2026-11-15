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
