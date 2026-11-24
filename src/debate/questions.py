"""토론 6단계: 미팅 질문 (Backend · 임동욱). 규칙은 docs/parts/3_Backend 문서 B3 "미팅 질문 3개".

6-4 재료 고르기 (LLM 호출 없음):
- 미설명 변화는 모두 쓴다(원래 신호 순서).
- 미설명 변화가 3개보다 적으면 설명됨 변화를 |유지 측 총점 − 해지 측 총점| 이 작은 순으로 더해
  변화 3개를 채운다(차이가 같으면 원래 신호 순서). 변화가 3개보다 적으면 있는 만큼만.
- 고른 변화마다 양측의 반증 조건이 재료다(유지 측 → 해지 측 순). 검사에서 삭제된 논거는 재료가 없다.
- 재료마다 신호 종류 표시(예: 핵심 인력)를 붙여 둔다. 6-5에서 질문 앞의 [종류] 표시와 실패 시 대체 질문에 쓴다.

6-5 질문 생성:
- 유지 측(keep) 모델 1번 호출(B4 표). 프롬프트에는 미설명 재료를 먼저 싣고 "미설명 먼저"를 적는다.
- 응답 검사: 정확히 N개(N = min(3, 재료 수)), 각 질문 앞에 재료에 있는 [종류] 표시, 질문 내용이 비지 않음,
  신호에 없는 숫자 없음(그 운용사 신호 전체 기준). 틀리면 1회 재요청.
- 또 틀리면 반증 조건 문장을 그대로 질문으로 쓴다: 미설명 재료부터 N개, 앞에 [종류] 표시. warnings 에 남긴다.
- 결정 3(2026-11-23, PM 확인 요청): N이 3보다 작으면 있는 만큼만 내고 warnings 에 "미팅 질문 N개만 생성".
  재료가 없으면 LLM을 부르지 않는다.
- LLMUnavailable 은 여기서 잡지 않는다.
"""
from src.debate.decide import total
from src.debate.rounds import KIND_LABEL, PROMPT_DIR, _retry_user
from src.llm import call_llm
from src.report.format import unknown_numbers
from src.state import Argument, ChangeVerdict, Signal

QUESTION_COUNT = 3
FALLBACK_WARNING = "미팅 질문 생성 실패: 반증 조건을 그대로 질문으로 사용"


def _chosen(verdicts: list[ChangeVerdict], signals: list[Signal]) -> list[ChangeVerdict]:
    pos = {s["id"]: i for i, s in enumerate(signals)}
    in_order = sorted(verdicts, key=lambda v: pos.get(v["signal_id"], len(pos)))
    unexplained = [v for v in in_order if v["status"] == "unexplained"]
    if len(unexplained) >= QUESTION_COUNT:
        return unexplained
    explained = [v for v in in_order if v["status"] != "unexplained"]
    explained.sort(key=lambda v: abs(total(v["keep"]) - total(v["terminate"])))   # 안정 정렬: 동점은 신호 순서
    return unexplained + explained[:QUESTION_COUNT - len(unexplained)]


def question_materials(verdicts: list[ChangeVerdict], signals: list[Signal],
                       keep_args: list[Argument], terminate_args: list[Argument]) -> list[dict]:
    """미팅 질문 재료 목록. 항목: {"signal_id", "kind"(한글 종류), "side", "falsifier", "unexplained"}."""
    kind = {s["id"]: KIND_LABEL[s["kind"]] for s in signals}
    by_side = {"keep": {a["signal_id"]: a for a in keep_args},
               "terminate": {a["signal_id"]: a for a in terminate_args}}
    out = []
    for v in _chosen(verdicts, signals):
        sid = v["signal_id"]
        for side in ("keep", "terminate"):
            arg = by_side[side].get(sid)
            if arg is not None:
                out.append({"signal_id": sid, "kind": kind[sid], "side": side,
                            "falsifier": arg["falsifier"], "unexplained": v["status"] == "unexplained"})
    return out


# ---------- 6-5 질문 생성 ----------
def _prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


def _unexplained_first(materials: list[dict]) -> list[dict]:
    return sorted(materials, key=lambda m: not m["unexplained"])     # 안정 정렬: 같은 묶음 안에서는 받은 순서


def _check(resp: dict, n: int, kinds: list[str], signals: list[Signal]) -> tuple[list[str], list[str]]:
    """(다듬은 질문 목록, 문제 목록). 문제가 없으면 문제 목록이 빈다."""
    qs = resp.get("questions")
    if not isinstance(qs, list) or not all(isinstance(x, str) for x in qs):
        return [], ["questions 는 문자열 목록이어야 합니다"]
    qs = [x.strip() for x in qs]
    problems = []
    if len(qs) != n:
        problems.append(f"질문은 정확히 {n}개여야 합니다 (받은 개수 {len(qs)})")
    for i, x in enumerate(qs, 1):
        tag = next((k for k in kinds if x.startswith(f"[{k}]")), None)
        if tag is None:
            problems.append(f"{i}번 질문 앞에 종류 표시가 없습니다 (쓸 수 있는 표시: {', '.join(kinds)})")
        elif not x[len(tag) + 2:].strip():
            problems.append(f"{i}번 질문에 내용이 없습니다")
        bad = unknown_numbers(x, signals)
        if bad:
            problems.append(f"{i}번 질문: 재료에 없는 숫자 {', '.join(bad)}")
    return qs, problems


def make_questions(materials: list[dict], signals: list[Signal]) -> dict:
    """미팅 질문. 돌려주는 값: {"questions": [...], "warnings": [...]}."""
    ordered = _unexplained_first(materials)
    n = min(QUESTION_COUNT, len(ordered))
    warnings: list[str] = []
    questions: list[str] = []

    if n:
        kinds = list(dict.fromkeys(m["kind"] for m in ordered))
        lines = [f"- ({'미설명' if m['unexplained'] else '설명됨'}) [{m['kind']}] {m['falsifier']}" for m in ordered]
        user = (_prompt("questions_user.md").replace("{{materials}}", "\n".join(lines))
                .replace("{{count}}", str(n)).replace("{{kinds}}", ", ".join(f"[{k}]" for k in kinds)))
        system = _prompt("questions_system.md")

        qs, problems = _check(call_llm("keep", system, user, json_keys=["questions"]), n, kinds, signals)
        if problems:
            qs, problems = _check(call_llm("keep", system, _retry_user(user, problems), json_keys=["questions"]),
                                  n, kinds, signals)
        if problems:
            qs = [f"[{m['kind']}] {m['falsifier']}" for m in ordered[:n]]
            warnings.append(FALLBACK_WARNING)
        questions = qs

    if len(questions) < QUESTION_COUNT:
        warnings.append(f"미팅 질문 {len(questions)}개만 생성")
    return {"questions": questions, "warnings": warnings}
