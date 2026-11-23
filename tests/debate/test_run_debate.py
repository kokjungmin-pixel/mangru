"""run_debate 조립 (src/debate/__init__.py) 테스트. (Backend 문서 B3, B5, B7, C장 6번 6-6)
LLM_MOCK=1. 호출 수는 src.llm.call_count() 로 센다.
"""
import copy
import random

import pytest

from src import llm
from src.debate import judge as judge_mod
from src.debate import questions as q_mod
from src.debate import rounds as rounds_mod
from src.debate import run_debate
from src.debate.decide import no_debate_options
from src.mock_data import sample
from src.state import DebateResult
from src.validate import validate

FAIL_GROUND = "토론을 완료하지 못함: 담당자 확인 필요"
NO_SAVED = "저장된 토론 없음: 계약 샘플 사용"


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "1")
    llm.reset_call_count()
    yield
    llm.reset_call_count()


@pytest.fixture
def analysis() -> dict:
    return sample("analysis")


@pytest.fixture
def data() -> dict:
    return sample("manager_data")


def seed_a_is_keep(analysis) -> int:
    return next(s for s in range(50)
                if judge_mod.blind_input(analysis, [], [], [], random.Random(s))["sides"]["A"] == "keep")


def real(analysis, data, seed=None):
    rng = random.Random(seed) if seed is not None else None
    return run_debate(analysis, data, demo_mode=False, rng=rng)


# ---------- 정상 토론 ----------
def test_normal_debate_is_exactly_eight_calls_and_valid(analysis, data):
    out = real(analysis, data, seed=0)
    assert llm.call_count() == 8
    validate(out, DebateResult)


def test_normal_debate_fields(analysis, data):
    out = real(analysis, data, seed=seed_a_is_keep(analysis))
    ids = [s["id"] for s in analysis["signals"]]
    assert out["manager_id"] == analysis["manager_id"]
    assert out["held"] is True and out["rounds"] == 2
    assert [a["signal_id"] for a in out["keep_args"]] == ids
    assert [a["signal_id"] for a in out["terminate_args"]] == ids
    assert len(out["rebuttals"]) == 2 * 2 * len(ids)
    assert [v["signal_id"] for v in out["verdicts"]] == ids
    assert len(out["options"]) == 3
    assert [o["name"] for o in out["options"] if o["recommended"]] == [out["recommendation"]]
    assert len(out["questions"]) == 3                       # B7: 정상 상황에서 3개
    assert out["warnings"] == []
    assert out["models"] == {"keep": "mock", "terminate": "mock", "judge": "mock"}


def test_mock_debate_matches_contract_sample_when_a_is_keep(analysis, data):
    out = real(analysis, data, seed=seed_a_is_keep(analysis))
    d = sample("debate")
    for key in ("verdicts", "unexplained_count", "recommendation", "keep_args", "terminate_args"):
        assert out[key] == d[key], key


def test_default_rng_works(analysis, data):
    out = run_debate(analysis, data, demo_mode=False)
    assert llm.call_count() == 8
    validate(out, DebateResult)


def test_concede_in_round1_warns_and_still_eight_calls(analysis, data, monkeypatch):
    """B7: 반박 1회차 concede=true → '토론 불충분' 경고가 붙고 LLM 호출 수는 그대로 8번."""
    real_call = rounds_mod.call_llm
    state = {"done": False}

    def conceding(role, system, user, json_keys=None, temperature=None):
        out = real_call(role, system, user, json_keys=json_keys, temperature=temperature)
        if role == "keep" and json_keys == ["rebuttals"] and not state["done"]:
            state["done"] = True                            # 첫 유지 측 반박 = 1회차
            out = copy.deepcopy(out)
            out["rebuttals"][0]["concede"] = True
        return out

    monkeypatch.setattr(rounds_mod, "call_llm", conceding)
    out = real(analysis, data, seed=0)
    assert llm.call_count() == 8
    assert f"토론 불충분: {analysis['signals'][0]['id']}" in out["warnings"]
    validate(out, DebateResult)


def test_warnings_from_all_stages_are_collected(analysis, data):
    analysis["stated_strategy"] = None
    analysis["stated_strategy_evidence"] = []
    out = real(analysis, data, seed=0)
    assert out["warnings"][0] == "운용사가 밝힌 전략을 확인할 수 없음"
    validate(out, DebateResult)


def test_single_signal_debate_gives_fewer_questions_with_warning(analysis, data):
    """결정 3: 신호 1개 → 재료는 남은 반증 조건 수(최대 2) → 질문도 그만큼 + '미팅 질문 N개만 생성'.
    mock 해지 측 인력 논거의 '-35%' 는 지운 운용자산 신호의 숫자라 숫자 검사로 삭제된다 → 재료 1개."""
    analysis["signals"] = analysis["signals"][:1]
    sid = analysis["signals"][0]["id"]
    out = real(analysis, data, seed=0)
    assert out["held"] is True
    assert out["terminate_args"] == []
    assert f"해지 측 논거 삭제(신호에 없는 숫자 -35%): {sid}" in out["warnings"]
    n = len(out["keep_args"]) + len(out["terminate_args"])
    assert n == 1 and len(out["questions"]) == n
    assert f"미팅 질문 {n}개만 생성" in out["warnings"]
    validate(out, DebateResult)


# ---------- debate_required=False ----------
@pytest.mark.parametrize("demo_mode", [True, False])
def test_no_debate_required_calls_no_llm(analysis, data, demo_mode):
    analysis["debate_required"] = False
    out = run_debate(analysis, data, demo_mode=demo_mode)
    assert llm.call_count() == 0
    validate(out, DebateResult)
    assert out["manager_id"] == analysis["manager_id"]
    assert out["held"] is False and out["rounds"] == 0
    assert out["keep_args"] == out["terminate_args"] == out["rebuttals"] == out["verdicts"] == []
    assert out["unexplained_count"] == 0
    assert out["recommendation"] == "maintain"
    assert out["options"] == no_debate_options(analysis["signals"])
    assert out["questions"] == [] and out["warnings"] == []


def test_no_debate_options_counts_real_levels(analysis, data):
    analysis["debate_required"] = False
    out = run_debate(analysis, data, demo_mode=False)
    alerts = sum(s["level"] == "alert" for s in analysis["signals"])
    watches = sum(s["level"] == "watch" for s in analysis["signals"])
    maintain = out["options"][0]
    assert maintain["name"] == "maintain" and maintain["recommended"] is True
    assert maintain["grounds"] == [f"토론 개시 기준 미달: 경보 {alerts}건, 관찰 {watches}건"]


# ---------- B5 토론 실패 ----------
@pytest.mark.parametrize("stage", [rounds_mod, judge_mod, q_mod])
def test_llm_unavailable_at_any_stage_gives_failure_result(analysis, data, monkeypatch, stage):
    def boom(*a, **k):
        raise llm.LLMUnavailable("API 오류 3회: Timeout")
    monkeypatch.setattr(stage, "call_llm", boom)
    out = real(analysis, data, seed=0)
    validate(out, DebateResult)
    assert out["manager_id"] == analysis["manager_id"]
    assert out["held"] is False and out["rounds"] == 0
    assert out["keep_args"] == out["terminate_args"] == out["rebuttals"] == out["verdicts"] == []
    assert out["unexplained_count"] == 0
    assert out["recommendation"] == "conditional"
    opts = {o["name"]: o for o in out["options"]}
    assert [o["name"] for o in out["options"]] == ["maintain", "conditional", "review_termination"]
    assert opts["conditional"]["recommended"] is True
    assert opts["conditional"]["grounds"] == [FAIL_GROUND]
    assert opts["maintain"]["grounds"] == opts["review_termination"]["grounds"] == []
    assert out["questions"] == []
    assert out["warnings"] == ["토론 실패: API 오류 3회: Timeout"]


def test_call_limit_exceeded_is_debate_failure(analysis, data, monkeypatch):
    from src import config
    monkeypatch.setattr(config, "MAX_LLM_CALLS_PER_RUN", 3)
    out = real(analysis, data, seed=0)
    assert out["held"] is False and out["recommendation"] == "conditional"
    assert out["warnings"][0].startswith("토론 실패: LLM 호출 상한 초과")


# ---------- 결정 1: 데모 모드 ----------
def test_demo_mode_without_saved_debate_returns_contract_sample(analysis, data):
    out = run_debate(analysis, data, demo_mode=True)
    assert llm.call_count() == 0
    validate(out, DebateResult)
    expected = sample("debate")
    assert {k: v for k, v in out.items() if k != "warnings"} == {k: v for k, v in expected.items() if k != "warnings"}
    assert out["warnings"] == expected["warnings"] + [NO_SAVED]


def test_demo_mode_is_default(analysis, data):
    out = run_debate(analysis, data)
    assert llm.call_count() == 0 and NO_SAVED in out["warnings"]


# ---------- 모델 이름 ----------
def test_models_from_env_when_not_mock(analysis, data, monkeypatch):
    from src.llm import model_name
    monkeypatch.setenv("LLM_MOCK", "0")
    monkeypatch.setenv("MODEL_KEEP", "gpt-5-mini")
    monkeypatch.delenv("MODEL_JUDGE", raising=False)
    assert model_name("keep") == "gpt-5-mini"
    assert model_name("judge") == "확인 불가"
    monkeypatch.setenv("LLM_MOCK", "1")
    assert model_name("keep") == "mock"
