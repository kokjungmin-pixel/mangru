"""④ 토론 — run_debate (Backend · 임동욱). 규칙은 docs/parts/3_Backend 문서 B3, B5.

흐름 (C장 6번 6-6):
- debate_required=False → LLM 없이 토론 안 함 결과 (B3 "토론을 하지 않을 때"). 데모 모드여도 같다.
- 데모 모드 → 저장본 읽기는 B6에서 한다. 지금은 저장본이 없으므로 계약 샘플 + warnings
  "저장된 토론 없음: 계약 샘플 사용" (결정 1, 2026-11-23, PM 확인 요청).
- 실제 → 독립 작성·반박 2회(rounds) → 심판(judge) → 판정·선택지(decide_all) → 미팅 질문(questions).
  정상이면 LLM 8번. warnings 는 단계 순서대로 모은다.
- 중간에 LLMUnavailable(API 오류·형식 오류 2회·호출 상한) → B5 "토론 실패": held=False, 권고 conditional,
  근거 ["토론을 완료하지 못함: 담당자 확인 필요"], warnings 에 사유. 저장본으로 대신하는 처리는 B6에서.
"""
import random

from src.debate.decide import OPTION_ORDER, decide_all, no_debate_options
from src.debate.judge import run_judge
from src.debate.questions import make_questions, question_materials
from src.debate.rounds import REBUTTAL_ROUNDS, run_rounds
from src.llm import LLMUnavailable, model_name
from src.mock_data import sample
from src.state import AnalysisResult, DebateResult, ManagerData
from src.validate import validate

NO_SAVED = "저장된 토론 없음: 계약 샘플 사용"
FAIL_GROUND = "토론을 완료하지 못함: 담당자 확인 필요"


def _models() -> dict[str, str]:
    return {role: model_name(role) for role in ("keep", "terminate", "judge")}


def _not_held(analysis: AnalysisResult, recommendation: str, options: list, warnings: list[str]) -> DebateResult:
    return {"manager_id": analysis["manager_id"], "held": False, "rounds": 0,
            "keep_args": [], "terminate_args": [], "rebuttals": [], "verdicts": [],
            "unexplained_count": 0, "recommendation": recommendation, "options": options,
            "questions": [], "warnings": warnings, "models": _models()}


def _failed(analysis: AnalysisResult, reason: str) -> DebateResult:
    options = [{"name": name, "recommended": name == "conditional",
                "grounds": [FAIL_GROUND] if name == "conditional" else []} for name in OPTION_ORDER]
    return _not_held(analysis, "conditional", options, [f"토론 실패: {reason}"])


def _debate(analysis: AnalysisResult, rng: random.Random) -> DebateResult:
    signals = analysis["signals"]
    r = run_rounds(analysis)
    j = run_judge(analysis, r["keep_args"], r["terminate_args"], r["rebuttals"], rng)
    d = decide_all(j["verdicts"], signals, r["keep_args"], r["terminate_args"])
    q = make_questions(question_materials(j["verdicts"], signals, r["keep_args"], r["terminate_args"]), signals)
    return {"manager_id": analysis["manager_id"], "held": True, "rounds": REBUTTAL_ROUNDS,
            "keep_args": r["keep_args"], "terminate_args": r["terminate_args"], "rebuttals": r["rebuttals"],
            "verdicts": j["verdicts"], "unexplained_count": d["unexplained_count"],
            "recommendation": d["recommendation"], "options": d["options"],
            "questions": q["questions"], "warnings": r["warnings"] + j["warnings"] + q["warnings"],
            "models": _models()}


def run_debate(analysis: AnalysisResult, data: ManagerData, demo_mode: bool = True,
               rng: random.Random | None = None) -> DebateResult:
    """rng: 심판의 A/B 배정·신호 순서용. 없으면 새로 만든다(테스트에서만 넘긴다)."""
    if not analysis["debate_required"]:
        result = _not_held(analysis, "maintain", no_debate_options(analysis["signals"]), [])
    elif demo_mode:
        result = sample("debate")
        result["warnings"] = result["warnings"] + [NO_SAVED]
    else:
        try:
            result = _debate(analysis, rng or random.Random())
        except LLMUnavailable as e:
            result = _failed(analysis, str(e))
    validate(result, DebateResult)
    return result
