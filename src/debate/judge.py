"""토론 4단계: 심판 (Backend · 임동욱). 규칙은 docs/parts/3_Backend 문서 B3 "심판", B4.

6-1 심판 입력 만들기 (LLM 호출 없음):
- 작성자를 가린다: 측 이름을 A측/B측으로 바꾸고(어느 쪽이 A인지는 토론마다 무작위), 모델 이름은 주지 않는다.
  글의 내용에서 입장이 드러나는 것은 막지 않는다.
- 순서를 섞는다: 신호 순서를 무작위로 바꾼다. 한 신호 안에서는 항상 A측 → B측.
- A/B 대응표(sides)와 신호 순서(order)는 코드가 보관해 결과를 되돌릴 때 쓴다.
- 무작위는 random.Random 을 받아 쓴다(테스트에서 seed 로 고정).
"""
import random

from src.debate.rounds import DATA_LIMITS, PROMPT_DIR, signal_lines, strategy_lines
from src.state import AnalysisResult, Argument, Rebuttal

REBUTTAL_ROUNDS = (1, 2)
NONE = "(없음)"


def _prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


def _side_lines(label: str, arg: Argument | None, rebuttals: dict[int, Rebuttal]) -> list[str]:
    lines = [f"{label}측 논거: {arg['claim'] if arg else NONE}"]
    if arg:
        lines.append(f"{label}측 근거 번호: {arg['evidence_idx']}")
    lines.append(f"{label}측 반증 조건: {arg['falsifier'] if arg else NONE}")
    for rnd in REBUTTAL_ROUNDS:
        r = rebuttals.get(rnd)
        lines.append(f"{label}측 반박 {rnd}회차: {r['text'] if r else NONE}")
    return lines


def blind_input(analysis: AnalysisResult, keep_args: list[Argument], terminate_args: list[Argument],
                rebuttals: list[Rebuttal], rng: random.Random) -> dict:
    """심판에게 보낼 글. 돌려주는 값:
    {"system": 시스템 프롬프트, "user": 사용자 글, "sides": {"A": "keep"|"terminate", "B": ...},
     "order": 글에 실린 신호 id 순서}
    """
    first = rng.choice(["keep", "terminate"])
    sides = {"A": first, "B": "terminate" if first == "keep" else "keep"}
    signals = list(analysis["signals"])
    rng.shuffle(signals)

    args = {"keep": {a["signal_id"]: a for a in keep_args},
            "terminate": {a["signal_id"]: a for a in terminate_args}}
    rebs: dict[tuple[str, str], dict[int, Rebuttal]] = {}
    for r in rebuttals:
        rebs.setdefault((r["side"], r["signal_id"]), {})[r["round"]] = r

    lines, _ = strategy_lines(analysis)     # 밝힌 전략이 없다는 경고는 토론 단계에서 이미 남긴다
    lines += ["", "[데이터 한계]", DATA_LIMITS, "", "[신호별 토론 기록]"]
    for s in signals:
        lines += signal_lines(s)
        for label in ("A", "B"):
            side = sides[label]
            lines += _side_lines(label, args[side].get(s["id"]), rebs.get((side, s["id"]), {}))
        lines.append("")

    user = _prompt("judge_user.md").replace("{{body}}", "\n".join(lines).rstrip())
    return {"system": _prompt("judge_system.md"), "user": user,
            "sides": sides, "order": [s["id"] for s in signals]}
