"""데모 운용사로 지표 계산을 혼자 돌려 본다 (Data · 김지유, 11/24 마일스톤 확인용).

실행:  python scripts/analysis_run_metrics.py
네트워크를 쓰지 않는다. data_cache/demo/demo*/manager_data.json 만 읽는다.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.analysis.metrics import compute_series  # noqa: E402
from src.config import DEMO_DIR  # noqa: E402
from src.report.format import fmt_pp, fmt_ratio  # noqa: E402


def _cell(x: dict | None, key: str = "magnitude") -> str:
    if x is None:
        return "확인 불가"
    v = x.get(key)
    return "-" if v is None else fmt_ratio(v)


def main() -> None:
    for p in sorted(DEMO_DIR.glob("demo*/manager_data.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        data = data.get("result", data)
        quarters = data.get("quarters") or []
        print("\n" + "=" * 78)
        print(f"{data.get('manager_name')}  ({p.parent.name}, 분기 {len(quarters)}개)")
        if len(quarters) < 2:
            print("  13F 분기가 2개 미만이라 계산할 수 없음")
            continue
        print(f"  {'분기':8} {'업종 변화폭':>10} {'규모 변화폭':>10} {'집중도 변화폭':>12} {'회전율':>8}   가장 크게 움직인 업종")
        for r in compute_series(quarters):
            sec = r["sector_shift"]
            top = f"{sec['metric'].split(':', 1)[1]} {fmt_pp(sec['active_change'])}" if sec else ""
            print(f"  {r['period']:8} {_cell(sec):>10} {_cell(r['size_shift']):>10} "
                  f"{_cell(r['concentration_change']):>12} {_cell(r['turnover'], 'after'):>8}   {top}")
        last = r
        for line in last["data_checks"]:
            print("  [검사]", line)
        for line in last["unavailable"]:
            print("  [확인 불가]", line)


if __name__ == "__main__":
    main()
