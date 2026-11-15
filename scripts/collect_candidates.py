"""데모 운용사 후보 정리 (Frontend · 조재연, Frontend 문서 B2·C4).

후보마다 SEC에서 실제로 받아 B2 조건을 판단할 재료를 표로 뽑는다. 판정(고르기)은 사람이 한다.
- 13F: submissions API → 13F-HR(/A) 보고 기준일 수, 최신 분기부터 끊김 없이 이어진 분기 수
- 최신 13F 원본: 보유 종목 수(옵션·원금 제외, CUSIP 합침), 예탁증서 비중(titleOfClass 글자 기준 추정),
  주가 중앙값(금액 단위 확인용), 표지의 CRD 번호
- IAPD: 회사명, SEC 등록일, 최신 ADV 제출일, PDF 제공 여부

실행:  python scripts/collect_candidates.py [--out 파일.md]
모든 SEC 요청은 sec_get(초당 5회, 원본 저장)으로 보낸다. 같은 주소는 data_cache/raw/http/ 저장본을 다시 쓴다.
"""
import argparse
import json
import re
import statistics
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.collect.form13f import clean_rows, parse_infotable  # noqa: E402
from src.collect.sec_client import sec_get  # noqa: E402

# 후보 목록. cik/crd 는 EDGAR 회사 검색·IAPD 검색으로 찾은 값(2026-11-15). cik=None 이면 13F 없음으로 본다.
CANDIDATES = [
    {"name": "Polen Capital Management", "type": "주식", "cik": "0001034524", "crd": "106093"},
    {"name": "Akre Capital Management", "type": "주식", "cik": "0001112520", "crd": "109242"},
    {"name": "Jensen Investment Management", "type": "주식", "cik": "0001106129", "crd": "105281"},
    {"name": "Sands Capital Management", "type": "주식", "cik": "0001020066", "crd": "137610"},
    {"name": "Fiduciary Management Inc (FMI)", "type": "주식", "cik": "0000764532", "crd": "109149"},
    {"name": "Wedgewood Partners", "type": "주식", "cik": "0000859804", "crd": "21923"},
    {"name": "Pershing Square Capital Management", "type": "대체(헤지)", "cik": "0001336528", "crd": "132982"},
    {"name": "Thoma Bravo", "type": "대체(PE)", "cik": None, "crd": "157041"},
]

HISTORY_QUARTERS = 14          # config.HISTORY_QUARTERS 와 같은 값 (B2: 최근 14개 분기)
MIN_QUARTERS = 6               # B2: 최소 6개 분기는 있어야 판정 가능
MAX_HOLDINGS = 1500            # B2: 인덱스형 제외
MAX_ADR_SHARE = 0.10           # B2: 예탁증서 비중 10% 미만
ADV_BEFORE = date(2024, 1, 1)  # B2: 2024년 이전부터 등록
_ADR = re.compile(r"\bADRS?\b|\bADS\b|SPONSORED|SPON\b|DEPOSITARY|DEPOSITORY", re.IGNORECASE)


def _quarter_index(d: str) -> int:
    y, m, _ = map(int, d.split("-"))
    return y * 4 + (m - 1) // 3


def consecutive_quarters(report_dates: set[str]) -> int:
    """최신 보고 기준일부터 거꾸로 끊김 없이 이어진 분기 수."""
    if not report_dates:
        return 0
    idx = {_quarter_index(d) for d in report_dates}
    cur, n = max(idx), 0
    while cur in idx:
        n, cur = n + 1, cur - 1
    return n


def thirteenf_summary(cik: str) -> dict:
    out: dict = {"source": f"https://data.sec.gov/submissions/CIK{cik}.json"}
    sub = sec_get(out["source"])
    if sub is None:
        return {**out, "error": "submissions 확인 불가"}
    out["edgar_name"] = sub.get("name")
    r = sub["filings"]["recent"]
    filings = [{"form": r["form"][i], "report": r["reportDate"][i], "filed": r["filingDate"][i],
                "acc": r["accessionNumber"][i]}
               for i in range(len(r["form"])) if r["form"][i] in ("13F-HR", "13F-HR/A") and r["reportDate"][i]]
    if sub["filings"].get("files"):
        out["note"] = "submissions 이전 페이지 있음(recent 만 셈)"
    reports = {f["report"] for f in filings}
    out["quarters_total"] = len(reports)
    out["quarters_consecutive"] = consecutive_quarters(reports)
    out["amendments"] = sum(f["form"] == "13F-HR/A" for f in filings)
    # 13F-NT: 보유 내역을 다른 운용사 보고에 넘긴 분기(이 운용사 13F로는 내역이 없다)
    nt = [r["reportDate"][i] for i in range(len(r["form"])) if r["form"][i] == "13F-NT" and r["reportDate"][i]]
    out["nt_after_latest"] = sorted(d for d in nt if not reports or d > max(reports))
    originals = [f for f in filings if f["form"] == "13F-HR"]
    if not originals:
        return out
    latest = max(originals, key=lambda f: (f["report"], f["filed"]))
    out["latest_report"], out["latest_filed"] = latest["report"], latest["filed"]
    folder = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{latest['acc'].replace('-', '')}"
    out["latest_url"] = folder + "/"
    idx = sec_get(folder + "/index.json")
    if idx is None:
        return {**out, "error": "공시 폴더 확인 불가"}
    names = [it["name"] for it in idx["directory"]["item"]]
    xmls = [n for n in names if n.lower().endswith(".xml") and n.lower() != "primary_doc.xml"]
    if "primary_doc.xml" in names:
        cover = sec_get(folder + "/primary_doc.xml", kind="bytes")
        m = re.search(rb"<(?:\w+:)?crdNumber>\s*(\d+)\s*<", cover or b"")
        out["crd_on_13f"] = str(int(m.group(1))) if m else None
    if not xmls:
        return {**out, "error": "정보표 XML 없음"}
    raw = parse_infotable(sec_get(f"{folder}/{xmls[0]}", kind="bytes") or b"<x/>")
    rows = clean_rows(raw)
    total = sum(x["value"] for x in rows)
    out["holdings"] = len(rows)
    out["dropped_rows"] = len(raw) - sum(1 for x in raw if not x["put_call"] and (x["share_type"] or "") == "SH")
    out["adr_share"] = (sum(x["value"] for x in rows if _ADR.search(x["title_of_class"] or "")) / total
                        if total else None)
    prices = [x["value"] / x["shares"] for x in rows if x["shares"]]
    out["median_price"] = statistics.median(prices) if prices else None
    out["total_value"] = total
    return out


def iapd_summary(crd: str) -> dict:
    url = f"https://api.adviserinfo.sec.gov/search/firm/{crd}?hl=true&nrows=12&query=&r=25&sort=score+desc&wt=json"
    d = sec_get(url)
    hits = (d or {}).get("hits", {}).get("hits") or []
    if not hits:
        return {"source": url, "error": "IAPD 확인 불가"}
    ia = json.loads(hits[0]["_source"]["iacontent"])
    b = ia.get("basicInformation", {})
    sec_reg = next((s for s in ia.get("registrationStatus", []) if s.get("secJurisdiction") == "SEC"), {})
    return {"source": url, "iapd_name": b.get("firmName"), "scope": b.get("iaScope"),
            "adv_filed": b.get("advFilingDate"), "has_pdf": b.get("hasPdf"),
            "sec_status": sec_reg.get("status"), "sec_registered": sec_reg.get("effectiveDate")}


def _mdy(s: str | None) -> date | None:
    try:
        m, d, y = map(int, s.split("/"))
        return date(y, m, d)
    except (AttributeError, ValueError):
        return None


def checks(c: dict, f: dict, a: dict) -> list[str]:
    """B2 조건 중 코드로 볼 수 있는 것만 표시. 단일 전략·CIO 교체 보도·Schedule A 읽기는 사람이 본다."""
    out = []
    if c["cik"]:
        q = f.get("quarters_consecutive", 0)
        out.append(f"{'OK' if q >= HISTORY_QUARTERS else ('부족' if q >= MIN_QUARTERS else 'X')} 연속 {q}분기")
        if f.get("holdings") is not None:
            out.append(f"{'OK' if f['holdings'] < MAX_HOLDINGS else 'X'} 종목 {f['holdings']}개")
        if f.get("adr_share") is not None:
            s = f["adr_share"]
            mark = "X" if s >= MAX_ADR_SHARE else ("경계" if s >= MAX_ADR_SHARE * 0.9 else "OK")
            out.append(f"{mark} 예탁증서 {s:.1%}")
        if f.get("nt_after_latest"):
            out.append(f"X 최신 분기 13F-NT({', '.join(f['nt_after_latest'])}: 보유 내역 없음)")
        if f.get("crd_on_13f") is None:
            out.append("? 13F 표지에 CRD 없음")
        elif f["crd_on_13f"] != c["crd"]:
            out.append(f"X CRD 불일치(13F 표지 {f['crd_on_13f']})")
        else:
            out.append("OK 13F 표지 CRD 일치")
    reg = _mdy(a.get("sec_registered"))
    out.append(f"{'OK' if reg and reg < ADV_BEFORE else 'X'} SEC 등록 {a.get('sec_registered') or '확인 불가'}")
    return out


def render(results: list[tuple[dict, dict, dict]]) -> str:
    lines = [f"# 데모 운용사 후보 (scripts/collect_candidates.py, {date.today().isoformat()} 실행)", "",
             "| 후보 | 유형 | CIK | CRD | 13F 분기(연속/전체) | 최신 13F 기준일 | 종목 수 | 예탁증서 비중 | 주가 중앙값 | SEC 등록일 | 최신 ADV | 확인 |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c, f, a in results:
        q = f"{f.get('quarters_consecutive', '-')}/{f.get('quarters_total', '-')}" if c["cik"] else "13F 없음"
        adr = f"{f['adr_share']:.1%}" if f.get("adr_share") is not None else "-"
        px = f"${f['median_price']:,.0f}" if f.get("median_price") is not None else "-"
        lines.append(f"| {a.get('iapd_name') or c['name']} | {c['type']} | {c['cik'] or '-'} | {c['crd']} | {q} | "
                     f"{f.get('latest_report', '-')} | {f.get('holdings', '-')} | {adr} | {px} | "
                     f"{a.get('sec_registered') or '확인 불가'} | {a.get('adv_filed') or '확인 불가'} | "
                     f"{' · '.join(checks(c, f, a))} |")
    lines += ["", "- 예탁증서 비중: 최신 13F 정보표의 titleOfClass 에 ADR/ADS/SPONSORED/DEPOSITARY 가 있는 행의 금액 비중(추정).",
              "- 종목 수: 옵션·원금 행을 빼고 같은 CUSIP을 합친 뒤. 13F는 운용사 전체 합산이라 단일 전략 여부는 따로 본다.",
              "- 코드로 못 보는 조건(사람이 확인): 단일 전략, 최근 1~2년 CIO 교체 보도, ADV Schedule A 표를 코드로 읽을 수 있는지(C5).",
              "", "## 출처"]
    for c, f, a in results:
        src = [f.get("latest_url"), f.get("source"), a.get("source")]
        errs = [x for x in (f.get("error"), a.get("error"), f.get("note")) if x]
        lines.append(f"- {c['name']}: " + " · ".join(s for s in src if s) + (f" ({'; '.join(errs)})" if errs else ""))
    return "\n".join(lines) + "\n"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", type=Path, help="결과 표를 저장할 .md 경로(없으면 화면에만)")
    args = p.parse_args()
    results = []
    for c in CANDIDATES:
        print(f"... {c['name']}", file=sys.stderr)
        f = thirteenf_summary(c["cik"]) if c["cik"] else {}
        results.append((c, f, iapd_summary(c["crd"])))
    md = render(results)
    print(md)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(md, encoding="utf-8")


if __name__ == "__main__":
    main()
