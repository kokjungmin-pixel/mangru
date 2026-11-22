"""데모 운용사(Akre·Brown)의 종목 식별 결과 security_master.json 을 새로 만든다 (Data · 김지유).

data_cache/demo/demo*/manager_data.json 에 들어 있는 분기별 CUSIP 으로 enrich_cusips 를 돌린다.
기존 security_master.json 이 있으면 .bak 으로 옮기고 처음부터 다시 만든다(예전 "못 찾음"이 남지 않게).
끝나면 분기별 매핑률·발행주식 수 비율과, 최신 분기에 아직 빈 종목을 출력한다.

실행:  python scripts/analysis_build_security_master.py
필요:  .env 의 OPENFIGI_API_KEY, SEC_CONTACT_EMAIL. 처음 실행은 SEC 요청이 많아 몇 분 걸린다.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.analysis import securities as sec  # noqa: E402
from src.config import DEMO_DIR, MIN_MAPPING_RATE, MIN_SIZE_COVERAGE  # noqa: E402


def load_demos() -> list[dict]:
    out = []
    for p in sorted(DEMO_DIR.glob("demo*/manager_data.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        out.append(data.get("result", data))
    return out


def main() -> None:
    if sec.MASTER_PATH.exists():
        bak = sec.MASTER_PATH.with_suffix(".json.bak")
        sec.MASTER_PATH.replace(bak)
        print("기존 파일을 옮김:", bak.name)

    for m in load_demos():
        if not m.get("quarters"):
            continue                         # 13F 가 없는 데모(예: demo3)는 건너뜀
        name = m.get("manager_name", "?")
        print("\n" + "=" * 70)
        print(name)
        print(f"  {'분기':8} {'종목':>4} {'매핑률':>7} {'발행주식수':>9}   (기준: 매핑 {MIN_MAPPING_RATE:.0%}, 발행주식수 {MIN_SIZE_COVERAGE:.0%})")
        last = None
        for q in m["quarters"]:
            h = q["holdings"]
            cusips = [x["cusip"] for x in h]
            info = sec.enrich_cusips(cusips, q["report_date"])
            V = sum(x["value_usd"] for x in h) or 1
            mapped = sum(x["value_usd"] for x in h if info.get(x["cusip"], {}).get("issuer_cik")) / V
            shares = sum(x["value_usd"] for x in h if info.get(x["cusip"], {}).get("shares_outstanding")) / V
            flag = "" if mapped >= MIN_MAPPING_RATE and shares >= MIN_SIZE_COVERAGE else "  ← 기준 미달"
            print(f"  {q['period']:8} {len(h):>4} {mapped:>7.1%} {shares:>9.1%}{flag}")
            last = (q, info, V)

        q, info, V = last
        print(f"\n  {q['period']} 아직 빈 종목 (비중 큰 순, 최대 10개):")
        shown = 0
        for x in sorted(q["holdings"], key=lambda x: -x["value_usd"]):
            i = info.get(x["cusip"], {})
            miss = [k for k in ("issuer_cik", "shares_outstanding") if not i.get(k)]
            if miss and not i.get("is_etf") and shown < 10:
                shown += 1
                print(f"    {x['value_usd'] / V:6.1%} {x['cusip']} {x['issuer'][:28]:28} ticker={i.get('ticker')} 빈칸={miss}")

    size = sec.MASTER_PATH.stat().st_size // 1024 if sec.MASTER_PATH.exists() else 0
    print(f"\n저장: {sec.MASTER_PATH} ({size}KB)")


if __name__ == "__main__":
    main()
