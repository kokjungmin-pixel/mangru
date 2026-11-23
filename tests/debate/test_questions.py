"""미팅 질문 (src/debate/questions.py) 테스트. (Backend 문서 B3 "미팅 질문 3개", B7, C장 6번 6-4)
6-4 재료 고르기는 LLM을 부르지 않는다.
"""
import copy
import json

import pytest

from src import config, llm
from src.debate.decide import status_of
from src.debate.questions import question_materials
from src.mock_data import sample

A11_PATH = config.ROOT / "tests" / "debate" / "fixtures" / "a11_analysis.json"
KP, SD, PA = "demo1-key_person-1", "demo1-strategy_drift-1", "demo1-peer_anomaly-1"
SD2 = "demo1-strategy_drift-2"
IDS = [KP, SD, PA]


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "1")
    llm.reset_call_count()
    yield
    llm.reset_call_count()


@pytest.fixture
def a11() -> dict:
    return json.loads(A11_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def a11_four(a11) -> dict:
    """설명됨 변화를 채우는 순서를 보려고 신호 하나(SD2)를 더한 4개짜리."""
    extra = copy.deepcopy(a11["signals"][1])
    extra["id"] = SD2
    a11["signals"].append(extra)
    return a11


def score(n: int) -> dict:
    out = {}
    for key, cap in (("numbers", 3), ("grounds", 3), ("rebuttal", 2), ("limits", 2)):
        out[key] = min(cap, n)
        n -= out[key]
    return out


def v(sid, keep_total, term_total) -> dict:
    k, t = score(keep_total), score(term_total)
    return {"signal_id": sid, "keep": k, "terminate": t, "status": status_of(k, t), "reason": "r"}


def args(ids):
    keep = [{"signal_id": s, "claim": "c", "evidence_idx": [0], "falsifier": f"K-fals-{s}"} for s in ids]
    term = [{"signal_id": s, "claim": "c", "evidence_idx": [0], "falsifier": f"T-fals-{s}"} for s in ids]
    return keep, term


def picked(mats) -> list[str]:
    """재료에 나온 신호 id (순서 유지, 중복 제거)."""
    out = []
    for m in mats:
        if m["signal_id"] not in out:
            out.append(m["signal_id"])
    return out


# ---------- 재료 모양 ----------
def test_material_has_kind_label_side_and_falsifier_of_both_sides(a11):
    verdicts = [v(KP, 5, 8), v(SD, 4, 9), v(PA, 6, 6)]          # 모두 미설명
    keep, term = args(IDS)
    mats = question_materials(verdicts, a11["signals"], keep, term)
    assert mats[:2] == [
        {"signal_id": KP, "kind": "핵심 인력", "side": "keep", "falsifier": f"K-fals-{KP}", "unexplained": True},
        {"signal_id": KP, "kind": "핵심 인력", "side": "terminate", "falsifier": f"T-fals-{KP}", "unexplained": True},
    ]
    assert {m["kind"] for m in mats} == {"핵심 인력", "전략 이탈", "Peer 대비"}
    assert len(mats) == 6


# ---------- 미설명 변화 ----------
def test_all_unexplained_are_used_even_when_more_than_three(a11_four):
    ids = IDS + [SD2]
    verdicts = [v(s, 5, 8) for s in ids]
    keep, term = args(ids)
    mats = question_materials(verdicts, a11_four["signals"], keep, term)
    assert picked(mats) == ids                    # 미설명은 모두, 원래 신호 순서
    assert all(m["unexplained"] for m in mats)


def test_three_unexplained_adds_no_explained(a11_four):
    ids = IDS + [SD2]
    verdicts = [v(KP, 5, 8), v(SD, 5, 8), v(PA, 6, 6), v(SD2, 7, 6)]   # SD2만 설명됨(차이 1)
    keep, term = args(ids)
    mats = question_materials(verdicts, a11_four["signals"], keep, term)
    assert picked(mats) == [KP, SD, PA]


# ---------- 미설명이 3개보다 적으면 |유지 − 해지| 가 작은 설명됨 변화로 채운다 ----------
def test_fill_with_explained_by_smallest_gap(a11_four):
    ids = IDS + [SD2]
    # KP 미설명 / SD 설명됨 차이 5 / PA 설명됨 차이 1 / SD2 설명됨 차이 3
    verdicts = [v(KP, 5, 8), v(SD, 9, 4), v(PA, 7, 6), v(SD2, 8, 5)]
    keep, term = args(ids)
    mats = question_materials(verdicts, a11_four["signals"], keep, term)
    assert picked(mats) == [KP, PA, SD2]          # 미설명 먼저, 그다음 차이 1 → 3. 차이 5(SD)는 빠짐
    assert [m["unexplained"] for m in mats] == [True, True, False, False, False, False]


def test_no_unexplained_uses_three_smallest_gaps(a11_four):
    ids = IDS + [SD2]
    verdicts = [v(KP, 10, 2), v(SD, 9, 4), v(PA, 7, 6), v(SD2, 8, 5)]  # 차이 8, 5, 1, 3
    keep, term = args(ids)
    mats = question_materials(verdicts, a11_four["signals"], keep, term)
    assert picked(mats) == [PA, SD2, SD]


def test_equal_gap_keeps_signal_order(a11_four):
    ids = IDS + [SD2]
    verdicts = [v(KP, 5, 8), v(SD, 8, 5), v(PA, 9, 4), v(SD2, 8, 5)]  # SD·SD2 차이 3 동점
    keep, term = args(ids)
    mats = question_materials(verdicts, a11_four["signals"], keep, term)
    assert picked(mats) == [KP, SD, SD2]


def test_zero_zero_verdict_is_unexplained_material(a11):
    zero = score(0)
    verdicts = [v(KP, 9, 4), v(SD, 9, 4),
                {"signal_id": PA, "keep": zero, "terminate": zero,
                 "status": status_of(zero, zero), "reason": "심판 점수 확인 불가"}]
    keep, term = args(IDS)
    mats = question_materials(verdicts, a11["signals"], keep, term)
    assert picked(mats)[0] == PA and mats[0]["unexplained"] is True


# ---------- 논거가 없을 때 ----------
def test_missing_argument_skips_that_falsifier(a11):
    verdicts = [v(KP, 5, 8), v(SD, 5, 8), v(PA, 5, 8)]
    keep, term = args(IDS)
    term = [a for a in term if a["signal_id"] != SD]
    mats = question_materials(verdicts, a11["signals"], keep, term)
    assert [(m["signal_id"], m["side"]) for m in mats if m["signal_id"] == SD] == [(SD, "keep")]
    assert len(mats) == 5


def test_single_signal_gives_at_most_two_materials(a11):
    a11["signals"] = a11["signals"][:1]
    keep, term = args([KP])
    mats = question_materials([v(KP, 9, 4)], a11["signals"], keep, term)
    assert [(m["signal_id"], m["side"]) for m in mats] == [(KP, "keep"), (KP, "terminate")]


def test_no_verdicts_gives_no_materials(a11):
    assert question_materials([], a11["signals"], [], []) == []


# ---------- 기타 ----------
def test_contract_sample_materials():
    a, d = sample("analysis"), sample("debate")
    mats = question_materials(d["verdicts"], a["signals"], d["keep_args"], d["terminate_args"])
    assert [(m["signal_id"], m["side"]) for m in mats] == [
        ("demo1-key_person-1", "keep"), ("demo1-key_person-1", "terminate"),
        ("demo1-strategy_drift-1", "keep"), ("demo1-strategy_drift-1", "terminate"),
    ]
    assert mats[0]["falsifier"] == d["keep_args"][0]["falsifier"]


def test_no_llm_call_and_inputs_unchanged(a11):
    verdicts = [v(KP, 5, 8), v(SD, 9, 4), v(PA, 7, 6)]
    keep, term = args(IDS)
    before = json.dumps([verdicts, a11, keep, term], sort_keys=True, ensure_ascii=False)
    question_materials(verdicts, a11["signals"], keep, term)
    assert json.dumps([verdicts, a11, keep, term], sort_keys=True, ensure_ascii=False) == before
    assert llm.call_count() == 0
