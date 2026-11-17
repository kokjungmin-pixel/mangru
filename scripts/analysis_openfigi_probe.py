"""OpenFIGI 실제 조회 시험 (Data · 김지유, Data 문서 B3-1 ③).

ETF·보통주·예탁증서를 하나씩 조회해 종목 유형이 어느 필드·어떤 값으로 다른지 확인한다.
결과는 화면에 출력하고, 원본 응답은 data_cache/raw/openfigi_probe.json 에 저장한다(GitHub에 안 올라감).

실행:  python scripts/analysis_openfigi_probe.py
키:    .env 의 OPENFIGI_API_KEY (없어도 돌아가지만 한도가 낮다). 키는 화면에 출력하지 않는다.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.analysis.securities import _openfigi_key, choose_figi, openfigi_map  # noqa: E402
from src.config import RAW_DIR  # noqa: E402

SAMPLES = {
    "78462F103": "ETF — SPDR S&P 500 ETF (Data 문서 지정)",
    "037833100": "보통주 — Apple (Data 문서 지정)",
    "874039100": "예탁증서 — TSMC ADR",
}
FIELDS = ("ticker", "exchCode", "name", "marketSector", "securityType", "securityType2",
          "securityDescription")


def main() -> None:
    print("OpenFIGI 키:", "있음" if _openfigi_key() else "없음 (키 없이 조회)")
    rows = openfigi_map(list(SAMPLES))

    out_path = RAW_DIR / "openfigi_probe.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

    for cusip, label in SAMPLES.items():
        row = rows.get(cusip)
        print("\n" + "=" * 60)
        print(f"{cusip}  {label}")
        if row is None:
            print("  요청 실패 (인터넷 연결이나 키를 확인)")
            continue
        if "data" not in row:
            print("  결과 없음:", row)
            continue
        data = row["data"]
        print(f"  결과 {len(data)}개. exchCode 목록: {sorted({d.get('exchCode') for d in data})}")
        picked = choose_figi(row)
        print("  고른 결과 (exchCode US 우선):")
        for f in FIELDS:
            print(f"    {f:20} = {picked.get(f)!r}")
        types = sorted({(d.get("securityType"), d.get("securityType2")) for d in data})
        print("  전체 결과의 (securityType, securityType2) 조합:", types)

    print("\n원본 응답 저장:", out_path)


if __name__ == "__main__":
    main()
