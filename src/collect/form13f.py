"""13F 수집 (Frontend · 조재연).
지금 있는 것: 정보표 XML 읽기(parse_infotable), 정리 규칙(clean_rows), 금액 단위(to_usd), 정정본(amendment_type, apply_amendments), 분기 조립(collect_13f). Frontend 문서 B3.
"""
import statistics
import xml.etree.ElementTree as ET

from src.analysis.securities import enrich_cusips
from src.collect.sec_client import sec_get
from src.config import HISTORY_QUARTERS


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


def amendment_type(primary_doc: bytes) -> str | None:
    """13F 표지(primary_doc.xml)의 정정 유형. "RESTATEMENT" / "NEW HOLDINGS" / 원본이면 None."""
    el = ET.fromstring(primary_doc).find(".//{*}amendmentType")
    return el.text.strip().upper() if el is not None and el.text else None


def apply_amendments(filings: list[dict]) -> tuple[list[dict], dict | None, list[str]]:
    """한 분기의 원본·정정본들을 제출일 순으로 적용한다(B3-4).
    filings: {"accession", "form", "filed_date", "amendment_type", "rows"} — rows 는 공시마다 to_usd 를 거친 것
    (정정본 단위는 정정본 제출일 기준, verified.md 2026-11-21).
    돌려주는 값: (합친 행, 대표 공시 = 마지막 원본 또는 전체 대체 정정본, notes 문장들).
    대표 공시가 없으면(원본을 못 받고 종목 추가 정정본만 있음) base=None → 그 분기는 쓰지 않는다."""
    rows: list[dict] = []
    base = None
    notes = []
    for f in sorted(filings, key=lambda f: (f["filed_date"], f["accession"])):
        kind, acc = f["amendment_type"], f["accession"]
        if f["form"] == "13F-HR":
            rows, base = list(f["rows"]), f
        elif kind == "RESTATEMENT" and f["rows"]:
            rows, base = list(f["rows"]), f
            notes.append(f"13F 정정본 반영(전체 대체): {acc}, 제출일 {f['filed_date']}")
        elif kind == "NEW HOLDINGS":
            # 원본 종목을 다시 적는 '종목 추가' 정정본이 있다(Akre 2024-03-31, verified.md) → 새 CUSIP만 더한다
            have = {r["cusip"] for r in rows}
            new = [r for r in f["rows"] if r["cusip"] not in have]
            rows = rows + new
            dup = len(f["rows"]) - len(new)
            notes.append(f"13F 정정본 반영(종목 추가 {len(new)}건" + (f", 겹친 {dup}건 제외" if dup else "")
                         + f"): {acc}, 제출일 {f['filed_date']}")
        else:
            # 빈 전체 대체를 따르면 보유 종목이 통째로 사라지므로 건너뛴다
            notes.append(f"13F 정정본 건너뜀(유형 {kind or '읽지 못함'}, 정보표 {len(f['rows'])}행): {acc}")
    return rows, base, notes


SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
FOLDER_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}"


def pick_quarters(recent: dict, n: int) -> dict[str, list[dict]]:
    """submissions 의 filings.recent → {보고 기준일: [공시]} 최신 n개 분기, 오래된 → 최신 순 (B3-1)."""
    by: dict[str, list[dict]] = {}
    for i, form in enumerate(recent["form"]):
        if form in ("13F-HR", "13F-HR/A") and recent["reportDate"][i]:
            by.setdefault(recent["reportDate"][i], []).append(
                {"accession": recent["accessionNumber"][i], "form": form, "filed_date": recent["filingDate"][i]})
    return {d: by[d] for d in sorted(by)[-n:]}


def _period(report_date: str) -> str:
    return f"{report_date[:4]}Q{(int(report_date[5:7]) - 1) // 3 + 1}"


def fetch_filing(cik: str, meta: dict) -> tuple[dict | None, list[str]]:
    """공시 하나 → apply_amendments 입력 모양(정리·달러 변환까지) + notes. 받지 못하면 None (B3-2)."""
    acc = meta["accession"]
    folder = FOLDER_URL.format(cik=int(cik), acc=acc.replace("-", ""))
    idx = sec_get(folder + "/index.json")
    cover = sec_get(folder + "/primary_doc.xml", kind="bytes")
    if not idx or not cover:
        return None, [f"13F 공시를 받지 못함: {acc}"]
    notes = []
    raw = []
    try:
        for it in idx["directory"]["item"]:
            name = it["name"]
            if name.lower().endswith(".xml") and name != "primary_doc.xml":   # 정보표 이름은 제각각 (verified.md)
                body = sec_get(f"{folder}/{name}", kind="bytes")
                if not body:   # 종목이 빠진 채 넘어가지 않게 공시 전체를 받지 못한 것으로 본다
                    return None, [f"13F 정보표를 받지 못함: {acc} ({name})"]
                raw += parse_infotable(body)
        kind = amendment_type(cover)
        total = ET.fromstring(cover).find(".//{*}tableEntryTotal")
    except ET.ParseError as e:
        return None, [f"13F 공시 XML을 읽지 못함: {acc} ({e})"]
    if total is not None and total.text and total.text.strip().isdigit() and int(total.text) != len(raw):
        notes.append(f"13F 정보표 행 수가 표지와 다름: {acc}, 표지 {int(total.text)}행 / 읽은 {len(raw)}행")
    rows, unit_note = to_usd(clean_rows(raw), meta["filed_date"])
    notes += [unit_note] if unit_note else []
    return {**meta, "url": folder + "/", "amendment_type": kind, "rows": rows}, notes


def _holding(r: dict, e: dict) -> dict:
    return {"cusip": r["cusip"], "issuer": r["issuer"] or "", "title_of_class": r["title_of_class"] or "",
            "value_usd": r["value"], "shares": r["shares"],
            "ticker": e.get("ticker"), "issuer_cik": e.get("issuer_cik"), "sic": e.get("sic"),
            "shares_outstanding": e.get("shares_outstanding"),
            "shares_outstanding_partial": bool(e.get("shares_outstanding_partial")), "is_etf": bool(e.get("is_etf"))}


def collect_13f(cik: str, n: int = HISTORY_QUARTERS) -> tuple[list[dict], list[str], list[str]]:
    """운용사 CIK → (QuarterHoldings 목록 오래된 → 최신, notes, unavailable). 예외 없이 끝까지 간다."""
    sub = sec_get(SUBMISSIONS_URL.format(cik=cik))
    if not sub:
        return [], [], ["13F 공시 목록: 확인 불가 (SEC submissions 응답 없음)"]
    # shortcut: filings.recent 만 본다(최근 1,000건). 14개 분기가 안 잡히는 대형 제출자면 filings.files 도 읽을 것
    picked = pick_quarters(sub["filings"]["recent"], n)
    notes = [f"13F 분기 {len(picked)}개만 찾음 (목표 {n}개)"] if len(picked) < n else []
    quarters, unavailable = [], []
    for report_date, metas in picked.items():
        filings = []
        for m in metas:
            f, ns = fetch_filing(cik, m)
            notes += ns
            filings += [f] if f else []
        if not filings:
            unavailable.append(f"13F {_period(report_date)}: 확인 불가 (공시를 받지 못함)")
            continue
        rows, base, ns = apply_amendments(filings)
        notes += ns
        if base is None:
            unavailable.append(f"13F {_period(report_date)}: 확인 불가 (원본 공시를 받지 못함, 정정본만 있음)")
            continue
        info = enrich_cusips([r["cusip"] for r in rows], report_date)
        quarters.append({"period": _period(report_date), "report_date": report_date,
                         "filed_date": base["filed_date"], "accession": base["accession"], "url": base["url"],
                         "holdings": [_holding(r, info.get(r["cusip"]) or {}) for r in rows]})
    return quarters, notes, unavailable
