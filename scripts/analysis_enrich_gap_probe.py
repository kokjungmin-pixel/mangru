"""enrich_cusips 빈칸 원인 확인 (Data · 김지유, 2026-11-23).

데모 저장본(Akre·Brown)에서 비어 있던 두 가지를 실제로 조회해 본다.
  1) 영문자로 시작하는 해외 발행사 번호(CINS)  → OpenFIGI 에서 idType 을 바꾸면 찾아지는가
  2) 주식 종류가 여러 개인 회사(A주·B주)       → SEC XBRL 의 어느 항목에 발행주식 수가 있는가

결과는 화면에 출력하고, 원본은 data_cache/raw/enrich_gap_probe.json 에 저장한다(GitHub에 안 올라감).
실행:  python scripts/analysis_enrich_gap_probe.py
필요:  .env 의 OPENFIGI_API_KEY, SEC_CONTACT_EMAIL
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.analysis import securities as sec  # noqa: E402
from src.config import RAW_DIR  # noqa: E402

AS_OF = "2026-09-30"

FOREIGN = {
    "M20791105": "Camtek (Brown 6.3%)",
    "M5216V106": "Global-E Online (Brown 5.7%)",
    "M2197Q107": "Cellebrite (Brown 2.3%)",
    "G25457105": "Credo Technology (Brown 1.5%)",
    "H82027105": "Sophia Genetics (Akre 0.7%)",
}
MULTI_CLASS = {
    "0001141391": "Mastercard (Akre 22.0%)",
    "0001403161": "Visa (Akre 7.6%)",
    "0001001085": "Brookfield Corp (Akre 8.7%)",
    "0001561550": "Datadog (Brown 4.9%)",
    "0001657573": "Xometry (Brown 4.8%)",
    "0001433195": "AppFolio (Brown 3.8%)",
}
CONCEPTS = [
    ("dei", "EntityCommonStockSharesOutstanding"),
    ("us-gaap", "CommonStockSharesOutstanding"),
    ("us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic"),
]


def probe_foreign(raw: dict) -> None:
    print("\n" + "=" * 70)
    print("1) 해외 발행사 번호: idType 별 OpenFIGI 결과")
    key = sec._openfigi_key()
    headers = {"Content-Type": "application/json"}
    if key:
        headers["X-OPENFIGI-APIKEY"] = key
    for id_type in ("ID_CUSIP", "ID_CINS"):
        body = [{"idType": id_type, "idValue": c} for c in FOREIGN]
        try:
            resp = sec._post(sec.OPENFIGI_URL, json=body, headers=headers, timeout=sec.TIMEOUT_SEC)
            rows = resp.json() if resp.status_code == 200 else None
            status = resp.status_code
        except Exception as e:
            rows, status = None, type(e).__name__
        raw[f"openfigi_{id_type}"] = rows
        print(f"\n  [{id_type}] HTTP {status}")
        for i, (c, label) in enumerate(FOREIGN.items()):
            row = rows[i] if isinstance(rows, list) and i < len(rows) else None
            if not row or "data" not in row:
                print(f"    {c} {label:30} → 없음 {('(' + str(row.get('warning') or row.get('error')) + ')') if row else ''}")
                continue
            p = sec.choose_figi(row)
            print(f"    {c} {label:30} → ticker={p.get('ticker')!r} exch={p.get('exchCode')!r} "
                  f"type={p.get('securityType')!r}/{p.get('securityType2')!r} 결과 {len(row['data'])}개")


def probe_multi_class(raw: dict) -> None:
    print("\n" + "=" * 70)
    print(f"2) 주식 종류가 여러 개인 회사: XBRL 항목별 {AS_OF} 근처 값")
    for cik, label in MULTI_CLASS.items():
        print(f"\n  {label}  CIK {cik}")
        for taxonomy, tag in CONCEPTS:
            url = sec.SEC_CONCEPT_URL.format(cik=cik, taxonomy=taxonomy, tag=tag)
            resp = sec._safe_sec_get(url)
            raw[f"{cik}|{tag}"] = resp
            if resp is None:
                print(f"    {tag:46} → 응답 없음(404 또는 실패)")
                continue
            units = resp.get("units") or {}
            facts = units.get("shares") or []
            value, partial = sec.pick_shares_outstanding(facts, AS_OF)
            latest = sorted({f.get("end") for f in facts if f.get("end")})[-3:]
            print(f"    {tag:46} → 단위 {list(units)} 값 {len(facts)}개, 최근 기준일 {latest}, "
                  f"선택값 {value} (partial={partial})")


def main() -> None:
    print("OpenFIGI 키:", "있음" if sec._openfigi_key() else "없음")
    raw: dict = {}
    probe_foreign(raw)
    probe_multi_class(raw)
    out = RAW_DIR / "enrich_gap_probe.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n원본 저장:", out)


if __name__ == "__main__":
    main()
