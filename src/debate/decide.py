"""코드 판정 — 심판 점수로 설명됨/미설명, 권고, 선택지 3개를 정한다 (Backend · 임동욱).
LLM을 쓰지 않는다. 규칙은 docs/parts/3_Backend 문서 B3 "코드 판정", 기준값은 src/config.py.
"""
from src import config
from src.state import Argument, ChangeVerdict, Option, Signal, SideScore

OPTION_ORDER = ("maintain", "conditional", "review_termination")


def total(s: SideScore) -> int:
    return s["numbers"] + s["grounds"] + s["rebuttal"] + s["limits"]


def status_of(keep: SideScore, terminate: SideScore) -> str:
    """유지 측이 EXPLAINED_MARGIN 점 이상 앞서야 설명됨. 동점은 미설명."""
    if total(keep) - total(terminate) >= config.EXPLAINED_MARGIN:
        return "explained"
    return "unexplained"


def recommend(verdicts: list[ChangeVerdict], signals: list[Signal]) -> str:
    unexplained = [v for v in verdicts if v["status"] == "unexplained"]
    n = len(unexplained)
    if n == 0:
        rec = "maintain"
    elif n <= config.CONDITIONAL_MAX_UNEXPLAINED:
        rec = "conditional"
    else:
        rec = "review_termination"
    # 기획서 규칙: 13F 신호만으로는 해지 검토를 권고하지 않는다
    form = {s["id"]: s["source_form"] for s in signals}
    if rec == "review_termination" and all(form.get(v["signal_id"]) == "13F" for v in unexplained):
        rec = "conditional"
    return rec


def _grounds(verdicts: list[ChangeVerdict], status: str, args: list[Argument], field: str) -> list[str]:
    """판정 순서대로, 해당 상태인 변화의 논거 문장을 그대로 골라 끝에 [signal_id]를 붙인다."""
    by_id = {a["signal_id"]: a for a in args}
    out = []
    for v in verdicts:
        a = by_id.get(v["signal_id"])
        if v["status"] == status and a is not None:
            out.append(f"{a[field]} [{v['signal_id']}]")
    return out


def _options(rec: str, grounds: dict[str, list[str]]) -> list[Option]:
    return [{"name": name, "recommended": name == rec, "grounds": grounds[name]} for name in OPTION_ORDER]


def build_options(rec: str, verdicts: list[ChangeVerdict],
                  keep_args: list[Argument], terminate_args: list[Argument]) -> list[Option]:
    """선택지 3개. maintain=설명됨 변화의 유지 측 논거, conditional=미설명 변화의 유지 측 반증 조건,
    review_termination=미설명 변화의 해지 측 논거. 해당 변화가 없으면 근거는 []."""
    return _options(rec, {
        "maintain": _grounds(verdicts, "explained", keep_args, "claim"),
        "conditional": _grounds(verdicts, "unexplained", keep_args, "falsifier"),
        "review_termination": _grounds(verdicts, "unexplained", terminate_args, "claim"),
    })


def no_debate_options(signals: list[Signal]) -> list[Option]:
    """debate_required=False 일 때의 선택지: maintain 만 권고, 근거는 경보·관찰 개수."""
    alerts = sum(1 for s in signals if s["level"] == "alert")
    watches = sum(1 for s in signals if s["level"] == "watch")
    return _options("maintain", {
        "maintain": [f"토론 개시 기준 미달: 경보 {alerts}건, 관찰 {watches}건"],
        "conditional": [],
        "review_termination": [],
    })
