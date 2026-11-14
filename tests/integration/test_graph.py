"""LangGraph 흐름: mock으로 처음부터 끝까지 (PM)"""
import copy

import src.graph as G
from src.mock_data import sample

NORMAL = ["plan", "collect", "analyze", "debate", "draft", "verify", "done"]


def steps(request="Example Capital 점검해줘", demo_mode=True):
    evs = list(G.stream_run(request, demo_mode))
    return [e["step"] for e in evs], evs[-1]["state"]


def test_normal_flow():
    order, st = steps()
    assert order == NORMAL
    assert st["status"] == "done" and st["retries"] == 0


def test_unknown_manager_stops_after_plan():
    order, st = steps("없는 운용사")
    assert order == ["plan", "done"] and st["status"] == "failed"


def test_no_new_filing_early_exit(monkeypatch):
    def no_new(plan, demo_mode):
        d = sample("manager_data"); d["has_new_filing"] = False; return d
    monkeypatch.setattr(G, "collect", no_new)
    order, st = steps()
    assert order == ["plan", "collect", "done"] and st["status"] == "early_exit"


def test_node_error_does_not_crash(monkeypatch):
    def boom(*a):
        raise RuntimeError("boom")
    monkeypatch.setattr(G, "analyze", boom)
    order, st = steps()
    assert order[-2:] == ["analyze", "done"] and st["status"] == "failed"
    assert any("analyze 단계 오류" in n for n in st["notices"])


def test_verify_fail_reruns_twice_then_stops(monkeypatch):
    monkeypatch.setattr(G, "verify_report", lambda *a: sample("verify"))   # 항상 실패(debate)
    order, st = steps(demo_mode=False)
    assert order.count("verify") == 3 and order.count("debate") == 3
    assert st["retries"] == 2 and st["status"] == "done"
    assert any("재시도 2회 초과" in n for n in st["notices"])


def test_demo_mode_never_reruns(monkeypatch):
    monkeypatch.setattr(G, "verify_report", lambda *a: sample("verify"))
    order, st = steps(demo_mode=True)
    assert order == NORMAL and st["retries"] == 0


def test_verify_fail_once_then_pass_retries_one(monkeypatch):
    """실제 모드 + 검증 1회 실패(failed_step=debate) → debate 부터 다시 실행, retries=1"""
    results = iter([sample("verify"), {**sample("verify"), "passed": True, "failed_step": None,
                                       "mismatches": []}])
    monkeypatch.setattr(G, "verify_report", lambda *a: next(results))
    order, st = steps(demo_mode=False)
    assert order == ["plan", "collect", "analyze", "debate", "draft", "verify",
                     "debate", "draft", "verify", "done"]
    assert st["retries"] == 1 and st["status"] == "done"
    assert st["verify"]["passed"] is True


def test_failed_step_none_no_rerun(monkeypatch):
    """failed_step=None 인 실패 → 재수행 0회, 문장 삭제 + 알림"""
    monkeypatch.setattr(G, "verify_report", lambda *a: {**sample("verify"), "failed_step": None})
    order, st = steps(demo_mode=False)
    assert order == NORMAL and st["retries"] == 0 and st["status"] == "done"
    assert any("리포트 조립 오류" in n for n in st["notices"])


def test_debate_not_required_still_reports(monkeypatch):
    """debate_required=False → 토론 없이(held=False) 리포트가 나옴"""
    def calm_analysis(data, plan):
        a = sample("analysis"); a["debate_required"] = False; return a
    seen = {}
    def no_debate(analysis, data, demo_mode):
        seen["required"] = analysis["debate_required"]
        d = sample("debate"); d["held"] = False; d["rounds"] = []; return d
    monkeypatch.setattr(G, "analyze", calm_analysis)
    monkeypatch.setattr(G, "run_debate", no_debate)
    order, st = steps()
    assert seen["required"] is False
    assert order == NORMAL and st["status"] == "done"
    assert st["debate"]["held"] is False and st["draft"] is not None


def test_manager_without_13f_runs_to_end(monkeypatch):
    """13F 없는 운용사(quarters=[], holding_changes=[])도 끝까지 실행됨"""
    def no_13f(plan, demo_mode):
        d = sample("manager_data"); d["quarters"] = []; d["holding_changes"] = []
        d["unavailable"] = d["unavailable"] + ["13F"]; return d
    monkeypatch.setattr(G, "collect", no_13f)
    order, st = steps()
    assert order == NORMAL and st["status"] == "done"
    assert "13F" in st["unavailable"]
