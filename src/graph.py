"""LangGraph 연결과 stream_run (PM). docs/parts/1_PM 문서 B3 코드 그대로."""
from typing import Iterator
from langgraph.graph import StateGraph, START, END

from src.state import AgentState
from src.config import MAX_VERIFY_RETRIES
from src.plan import make_plan                      # 아래 'make_plan' 참고 (PM)
from src.collect import collect                     # Frontend
from src.analysis import analyze                    # Data
from src.analysis.verify import verify_report       # Data
from src.debate import run_debate                   # Backend
from src.llm import reset_call_count                # Backend
from src.report.draft import draft_report, apply_verify   # PM
from src.rag import build_index                     # PM


def initial_state(request: str, demo_mode: bool) -> AgentState:
    return {"request": request, "demo_mode": demo_mode, "plan": None, "data": None,
            "analysis": None, "debate": None, "draft": None, "verify": None,
            "retries": 0, "next_step": None, "removed_sentences": [], "notices": [],
            "unavailable": [], "status": "running"}


def safe_node(name, fn):
    """노드 안에서 예외가 나면 그래프를 죽이지 않고 status=failed 로 멈춘다."""
    def wrapped(state: AgentState) -> dict:
        try:
            return fn(state)
        except Exception as e:
            return {"status": "failed",
                    "notices": state["notices"] + [f"{name} 단계 오류: {type(e).__name__}: {e}"]}
    return wrapped


def n_plan(s):
    plan = make_plan(s["request"])
    if plan is None:
        return {"status": "failed", "notices": s["notices"] + ["요청에서 운용사를 찾지 못함"]}
    return {"plan": plan}


def n_collect(s):
    data = collect(s["plan"], s["demo_mode"])
    notices = list(s["notices"])
    if not s["demo_mode"] and data["adv2a_new"]:
        try:
            build_index(data["manager_id"], data["adv2a_new"])
        except Exception as e:      # 색인이 없어도 분석은 Item 8 본문으로 진행된다
            notices.append(f"근거 검색 색인 실패: {e}")
    upd = {"data": data, "unavailable": s["unavailable"] + data["unavailable"], "notices": notices}
    if not data["has_new_filing"]:
        upd |= {"status": "early_exit", "notices": notices + ["직전 점검 이후 새 공시 없음"]}
    return upd


def n_analyze(s):
    a = analyze(s["data"], s["plan"])
    return {"analysis": a, "unavailable": s["unavailable"] + a["unavailable"]}


def n_debate(s):
    d = run_debate(s["analysis"], s["data"], s["demo_mode"])
    return {"debate": d, "notices": s["notices"] + d["warnings"]}


def n_draft(s):
    return {"draft": draft_report(s)}


def n_verify(s):
    v = verify_report(s["draft"], s["analysis"], s["debate"], s["data"])
    if v["passed"]:
        draft, removed = apply_verify(s["draft"], v, drop_mismatched=False)
        return {"verify": v, "draft": draft, "removed_sentences": removed,
                "next_step": "finish", "status": "done"}
    can_rerun = (v["failed_step"] is not None and not s["demo_mode"]
                 and s["retries"] < MAX_VERIFY_RETRIES)
    if can_rerun:
        target = "analyze" if v["failed_step"] == "analysis" else "debate"
        return {"verify": v, "retries": s["retries"] + 1, "next_step": target,
                "notices": s["notices"] + [f"검증 실패 → {target}부터 재수행 {s['retries'] + 1}/{MAX_VERIFY_RETRIES}"]}
    draft, removed = apply_verify(s["draft"], v, drop_mismatched=True)
    if v["failed_step"] is None:
        why = "리포트 조립 오류(담당 확인 필요)"
    elif s["demo_mode"]:
        why = "데모 모드라 재수행 없음"
    else:
        why = f"검증 재시도 {MAX_VERIFY_RETRIES}회 초과"
    return {"verify": v, "draft": draft, "removed_sentences": removed, "next_step": "finish",
            "status": "done", "notices": s["notices"] + [f"{why}: 문장 {len(removed)}개 삭제"]}


def build_graph():
    g = StateGraph(AgentState)
    for name, fn in [("plan", n_plan), ("collect", n_collect), ("analyze", n_analyze),
                     ("debate", n_debate), ("draft", n_draft), ("verify", n_verify)]:
        g.add_node(name, safe_node(name, fn))
    g.add_edge(START, "plan")

    def chain(src, nxt):   # status 가 running 이 아니면(실패·조기 종료) 바로 끝낸다
        g.add_conditional_edges(src, lambda s: "next" if s["status"] == "running" else "stop",
                                {"next": nxt, "stop": END})
    chain("plan", "collect"); chain("collect", "analyze"); chain("analyze", "debate")
    chain("debate", "draft"); chain("draft", "verify")
    g.add_conditional_edges(
        "verify",
        lambda s: s["next_step"] if s["status"] == "running" else "stop",
        {"analyze": "analyze", "debate": "debate", "stop": END})
    return g.compile()


APP = build_graph()


def stream_run(request: str, demo_mode: bool = True) -> Iterator[dict]:
    reset_call_count()
    state = initial_state(request, demo_mode)
    for chunk in APP.stream(state, stream_mode="updates", config={"recursion_limit": 30}):
        for node, update in chunk.items():          # {"collect": {...바뀐 값...}}
            state = {**state, **(update or {})}
            yield {"step": node, "state": state}
    yield {"step": "done", "state": state}
