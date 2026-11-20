"""13F 수집 (Frontend · 조재연).
지금 있는 것: 정보표 XML 읽기(parse_infotable), 정리 규칙(clean_rows), 금액 단위(to_usd). Frontend 문서 B3.
TODO(조재연): 공시 목록 → 분기별 정보표 → 정정본 처리 → QuarterHoldings.
"""
import statistics
import xml.etree.ElementTree as ET


def parse_infotable(xml_bytes: bytes) -> list[dict]:
    """13F 정보표 XML → 행 목록. {*} 는 네임스페이스를 무시하라는 뜻(파이썬 3.8+, find/findall 에서 동작)."""
    root = ET.fromstring(xml_bytes)
    rows = []
    for it in root.findall(".//{*}infoTable"):
        def t(path):
            el = it.find(path)
            return el.text.strip() if el is not None and el.text else None
        rows.append({
            "issuer": t("{*}nameOfIssuer"),
            "title_of_class": t("{*}titleOfClass"),
            "cusip": (t("{*}cusip") or "").upper(),
            "value": float(t("{*}value") or 0),
            "shares": float(t("{*}shrsOrPrnAmt/{*}sshPrnamt") or 0),
            "share_type": t("{*}shrsOrPrnAmt/{*}sshPrnamtType"),
            "put_call": t("{*}putCall"),
        })
    return rows


def clean_rows(rows: list[dict]) -> list[dict]:
    """정리 규칙(B3-5): 옵션(putCall 있음)·원금(SH 아님) 행을 빼고, 같은 CUSIP은 금액·주식 수를 합친다.
    금액 단위 변환(2023-01-03 이전 제출본 ×1000)은 여기서 하지 않는다."""
    merged: dict[str, dict] = {}
    for r in rows:
        if r.get("put_call") or (r.get("share_type") or "").upper() != "SH":
            continue
        cur = merged.get(r["cusip"])
        if cur is None:
            merged[r["cusip"]] = dict(r)
        else:
            cur["value"] += r["value"]
            cur["shares"] += r["shares"]
    return list(merged.values())


USD_FROM = "2023-01-03"          # 이날부터 제출분은 달러, 그 전은 천 달러 단위 (B3-5)
PRICE_RANGE = (1.0, 1000.0)      # 변환 뒤 주가(금액÷주식 수) 중앙값이 이 범위 밖이면 단위를 의심


def to_usd(rows: list[dict], filed_date: str) -> tuple[list[dict], str | None]:
    """금액을 달러로 통일한다. 주가 중앙값이 범위 밖이면 notes 에 넣을 문장을 함께 돌려준다(값은 고치지 않음)."""
    k = 1000.0 if filed_date < USD_FROM else 1.0
    out = [{**r, "value": r["value"] * k} for r in rows]
    prices = [r["value"] / r["shares"] for r in out if r["shares"] > 0]
    if prices:
        med = statistics.median(prices)
        if not PRICE_RANGE[0] <= med <= PRICE_RANGE[1]:
            return out, f"13F 금액 단위 의심: 제출일 {filed_date}, 주가 중앙값 ${med:,.2f} (정상 범위 $1~$1,000)"
    return out, None
