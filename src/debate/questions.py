"""토론 6단계: 미팅 질문 (Backend · 임동욱). 규칙은 docs/parts/3_Backend 문서 B3 "미팅 질문 3개".

6-4 재료 고르기 (LLM 호출 없음):
- 미설명 변화는 모두 쓴다(원래 신호 순서).
- 미설명 변화가 3개보다 적으면 설명됨 변화를 |유지 측 총점 − 해지 측 총점| 이 작은 순으로 더해
  변화 3개를 채운다(차이가 같으면 원래 신호 순서). 변화가 3개보다 적으면 있는 만큼만.
- 고른 변화마다 양측의 반증 조건이 재료다(유지 측 → 해지 측 순). 검사에서 삭제된 논거는 재료가 없다.
- 재료마다 신호 종류 표시(예: 핵심 인력)를 붙여 둔다. 6-5에서 질문 앞의 [종류] 표시와 실패 시 대체 질문에 쓴다.
"""
from src.debate.decide import total
from src.debate.rounds import KIND_LABEL
from src.state import Argument, ChangeVerdict, Signal

QUESTION_COUNT = 3


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
