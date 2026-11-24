"""토론 4단계: 심판 (Backend · 임동욱). 규칙은 docs/parts/3_Backend 문서 B3 "심판", B4.

6-1 심판 입력 만들기 (LLM 호출 없음):
- 작성자를 가린다: 측 이름을 A측/B측으로 바꾸고(어느 쪽이 A인지는 토론마다 무작위), 모델 이름은 주지 않는다.
  글의 내용에서 입장이 드러나는 것은 막지 않는다.
- 순서를 섞는다: 신호 순서를 무작위로 바꾼다. 한 신호 안에서는 항상 A측 → B측.
- A/B 대응표(sides)와 신호 순서(order)는 코드가 보관해 결과를 되돌릴 때 쓴다.
- 무작위는 random.Random 을 받아 쓴다(테스트에서 seed 로 고정).

6-2 심판 호출·응답 검사·A/B 되돌리기:
- judge 1번 호출. check_judge(B4 코드 그대로)에 걸리면 문제를 붙여 1회 재요청.
- 재요청 뒤에도 점수가 틀리거나 없는 신호는 양측 0점, reason "심판 점수 확인 불가", warnings 에 남긴다
  (사용자 결정 2026-11-23, PM 확인 요청). 0-0 이라 decide.status_of 가 미설명으로 정한다.
- 설명됨/미설명은 코드(decide.status_of)가 정한다. 심판은 점수만 매긴다.
- LLMUnavailable 은 여기서 잡지 않는다.
"""
import random

from src.debate.decide import status_of
from src.debate.rounds import DATA_LIMITS, PROMPT_DIR, _retry_user, signal_lines, strategy_lines
from src.llm import call_llm
from src.state import AnalysisResult, Argument, ChangeVerdict, Rebuttal

SCORE_MAX = {"numbers": 3, "grounds": 3, "rebuttal": 2, "limits": 2}
ZERO_SCORE = {k: 0 for k in SCORE_MAX}
NO_SCORE = "심판 점수 확인 불가"

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


# ---------- 6-2 응답 검사 (B4 코드 그대로) ----------
def valid_score(sc) -> bool:
    return (isinstance(sc, dict) and set(sc) == set(SCORE_MAX)
            and all(type(sc[k]) is int and 0 <= sc[k] <= SCORE_MAX[k] for k in SCORE_MAX))


def check_judge(resp: dict, signal_ids: set[str]) -> list[str]:
    """빈 목록이면 통과. 문제가 있으면 무엇이 틀렸는지 문장 목록 (재요청 프롬프트에 붙인다).
    B4 코드에 더해: scores 가 목록이 아니거나 행이 객체가 아니어도 멈추지 않고 문제로 적는다."""
    problems, seen = [], set()
    rows = resp.get("scores", [])
    if not isinstance(rows, list):
        problems.append(f"scores 가 목록이 아님: {type(rows).__name__}")
        rows = []
    for row in rows:
        if not isinstance(row, dict):
            problems.append(f"scores 항목이 객체가 아님: {row}")
            continue
        sid = row.get("signal_id")
        if sid not in signal_ids:
            problems.append(f"모르는 signal_id: {sid}")
            continue
        seen.add(sid)
        for side in ("A", "B"):
            if not valid_score(row.get(side)):
                problems.append(f"{sid} {side}측 점수 형식 오류: {row.get(side)}")
    problems += [f"점수 없음: {sid}" for sid in sorted(signal_ids - seen)]
    return problems


def _rows(resp: dict) -> dict[str, dict]:
    """signal_id → 처음 나온 행. 형식이 틀린 행은 건너뛴다(모양 검사는 check_judge 가 한다)."""
    out = {}
    rows = resp.get("scores")
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and isinstance(row.get("signal_id"), str):
            out.setdefault(row["signal_id"], row)
    return out


def run_judge(analysis: AnalysisResult, keep_args: list[Argument], terminate_args: list[Argument],
              rebuttals: list[Rebuttal], rng: random.Random) -> dict:
    """심판 채점 → keep/terminate 로 되돌린 ChangeVerdict. 돌려주는 값: {"verdicts", "warnings"}.
    verdicts 는 원래 신호 순서(analysis["signals"])를 따른다."""
    inp = blind_input(analysis, keep_args, terminate_args, rebuttals, rng)
    ids = {s["id"] for s in analysis["signals"]}

    resp = call_llm("judge", inp["system"], inp["user"], json_keys=["scores"])
    problems = check_judge(resp, ids)
    if problems:
        resp = call_llm("judge", inp["system"], _retry_user(inp["user"], problems), json_keys=["scores"])

    label_of = {side: label for label, side in inp["sides"].items()}     # keep → "A" 등
    rows = _rows(resp)
    verdicts: list[ChangeVerdict] = []
    warnings: list[str] = []
    for s in analysis["signals"]:
        row = rows.get(s["id"])
        if row and valid_score(row.get("A")) and valid_score(row.get("B")):
            keep, term = dict(row[label_of["keep"]]), dict(row[label_of["terminate"]])
            reason = row.get("reason") if isinstance(row.get("reason"), str) else ""
        else:
            keep, term, reason = dict(ZERO_SCORE), dict(ZERO_SCORE), NO_SCORE
            warnings.append(f"{NO_SCORE}: {s['id']}")
        verdicts.append({"signal_id": s["id"], "keep": keep, "terminate": term,
                         "status": status_of(keep, term), "reason": reason})
    return {"verdicts": verdicts, "warnings": warnings}
