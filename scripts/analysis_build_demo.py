"""데모 운용사의 분석 저장본 data_cache/demo/<id>/analysis.json 을 실제 LLM 으로 만든다 (Data · 김지유).

실행:  python scripts/analysis_build_demo.py            # demo1~3 전부
       python scripts/analysis_build_demo.py demo2      # 하나만
필요:  .env 의 MODEL_ANALYST 와 그 회사 API 키. LLM 호출은 운용사당 최대 2번.
결과 화면의 신호·설명·전략을 읽어 보고 이상하면 저장본을 지우고 다시 돌린다.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["LLM_MOCK"] = "0"            # 이 스크립트는 항상 실제 LLM

from dotenv import load_dotenv  # noqa: E402

from src import analysis as A  # noqa: E402
from src import llm  # noqa: E402
from src.config import DEMO_DIR, DEMO_MANAGERS, ROOT  # noqa: E402
from src.llm import call_count, reset_call_count  # noqa: E402

load_dotenv(ROOT / ".env", override=False)        # MODEL_ANALYST 등을 .env 에서 읽는다


def llm_ready() -> bool:
    """모델 이름과 그 회사 API 키가 있는지 먼저 확인한다. 없으면 저장본을 만들지 않는다."""
    try:
        model = llm._model_for("analyst")
        llm._api_key(model)
    except Exception as e:
        print(f"실제 LLM 을 쓸 수 없어 멈춤: {e}")
        print(".env 에 MODEL_ANALYST 와 그 회사 API 키(OPENAI_API_KEY 등)를 넣고 다시 실행")
        return False
    print(f"분석 모델: {model}")
    return True


def main(ids: list[str]) -> None:
    if not llm_ready():
        return
    for mid in ids or sorted(DEMO_MANAGERS):
        path = DEMO_DIR / mid / "manager_data.json"
        if not path.exists():
            print(f"{mid}: manager_data.json 없음")
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        data = data.get("result", data)
        reset_call_count()
        result = A.build(data)
        A._save_cache(data, result)
        print("\n" + "=" * 78)
        print(f"{mid} {data.get('manager_name')}  LLM 호출 {call_count()}번, 토론 필요 {result['debate_required']}")
        for s in result["signals"]:
            print(f"  [{'경보' if s['level'] == 'alert' else '관찰'}] {s['id']}  {s['summary']}")
            if s["explanation"] != s["summary"]:
                print(f"      설명: {s['explanation']}")
        print(f"  밝힌 전략: {result['stated_strategy']}")
        for e in result["stated_strategy_evidence"]:
            print(f"      인용(p.{e['page']}): {e['quote']}")
        for line in result["data_checks"]:
            print("  [검사]", line)
        for line in result["unavailable"]:
            print("  [확인 불가]", line)
        print("  저장:", A._cache_path(mid))


if __name__ == "__main__":
    main(sys.argv[1:])
