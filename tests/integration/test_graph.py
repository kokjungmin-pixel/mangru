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
