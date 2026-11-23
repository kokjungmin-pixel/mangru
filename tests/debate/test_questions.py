"""미팅 질문 (src/debate/questions.py) 테스트. (Backend 문서 B3 "미팅 질문 3개", B7, C장 6번 6-4·6-5)
6-4 재료 고르기는 LLM을 부르지 않는다. 6-5 질문 생성은 call_llm 을 가짜로 바꾸거나 LLM_MOCK=1 고정 응답을 쓴다.
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


# ======================================================================
# 6-5 미팅 질문 생성 (make_questions)
# ======================================================================
from src.debate import questions as q_mod            # noqa: E402
from src.debate.questions import make_questions      # noqa: E402

FALLBACK_WARNING = "미팅 질문 생성 실패: 반증 조건을 그대로 질문으로 사용"


def mat(sid, kind, side, text, unexplained) -> dict:
    return {"signal_id": sid, "kind": kind, "side": side, "falsifier": text, "unexplained": unexplained}


# 미설명 KP(양측) + 설명됨 PA(양측). 일부러 설명됨을 앞에 둔 순서도 쓴다.
M_KP_K = mat(KP, "핵심 인력", "keep", "후임 CIO의 운용 이력이 확인되면 우려는 약해진다", True)
M_KP_T = mat(KP, "핵심 인력", "terminate", "공동 CIO 자산을 남은 CIO가 넘겨받았다면 약해진다", True)
M_PA_K = mat(PA, "Peer 대비", "keep", "소형주 비중이 과거에도 높았다면 약해진다", False)
M_PA_T = mat(PA, "Peer 대비", "terminate", "같은 전략 운용사들도 비중이 높다면 약해진다", False)
MATS = [M_KP_K, M_KP_T, M_PA_K, M_PA_T]

GOOD = {"questions": ["[핵심 인력] 후임 CIO의 운용 이력은 어떻게 됩니까?",
                     "[핵심 인력] 공동 CIO의 자산은 누가 넘겨받았습니까?",
                     "[Peer 대비] 소형주 비중이 과거에도 이 수준이었습니까?"]}


class FakeQ:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, role, system, user, json_keys=None, temperature=None):
        self.calls.append({"role": role, "system": system, "user": user, "json_keys": json_keys})
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return copy.deepcopy(r)


def asked(monkeypatch, a11, mats, *responses):
    fake = FakeQ(*responses)
    monkeypatch.setattr(q_mod, "call_llm", fake)
    return make_questions(mats, a11["signals"]), fake


# ---------- 정상 ----------
def test_normal_three_questions_one_call_as_keep(a11, monkeypatch):
    out, fake = asked(monkeypatch, a11, MATS, GOOD)
    assert out == {"questions": GOOD["questions"], "warnings": []}
    assert len(fake.calls) == 1
    assert fake.calls[0]["role"] == "keep" and fake.calls[0]["json_keys"] == ["questions"]


def test_mock_questions_from_contract_sample():
    a, d = sample("analysis"), sample("debate")
    mats = question_materials(d["verdicts"], a["signals"], d["keep_args"], d["terminate_args"])
    out = make_questions(mats, a["signals"])
    assert llm.call_count() == 1
    assert out["warnings"] == []
    assert len(out["questions"]) == 3
    assert all(qq.startswith(("[핵심 인력] ", "[전략 이탈] ")) for qq in out["questions"])


# ---------- 프롬프트: 미설명 재료 먼저 ----------
def test_prompt_lists_unexplained_first_and_says_so(a11, monkeypatch):
    _, fake = asked(monkeypatch, a11, [M_PA_K, M_KP_K, M_PA_T, M_KP_T], GOOD)
    user = fake.calls[0]["user"]
    for m in MATS:
        assert m["falsifier"] in user
    # 넘겨준 순서와 상관없이 미설명 재료가 먼저 나온다
    assert max(user.index(m["falsifier"]) for m in (M_KP_K, M_KP_T)) < \
        min(user.index(m["falsifier"]) for m in (M_PA_K, M_PA_T))
    assert "미설명" in user and "먼저" in user
    assert "3개" in user
    assert "[핵심 인력]" in user and "[Peer 대비]" in user


def test_system_prompt_is_not_a_debate_side(a11, monkeypatch):
    _, fake = asked(monkeypatch, a11, MATS, GOOD)
    system = fake.calls[0]["system"]
    assert "유지' 측" not in system and "해지 검토' 측" not in system
    assert "질문" in system


# ---------- 응답 검사 → 1회 재요청 ----------
@pytest.mark.parametrize("bad", [
    {"questions": GOOD["questions"][:2]},                                   # 개수 틀림
    {"questions": GOOD["questions"] + ["[핵심 인력] 하나 더?"]},              # 개수 틀림
    {"questions": ["후임은 누구입니까?"] + GOOD["questions"][1:]},              # 종류 표시 없음
    {"questions": ["[기타] 후임은 누구입니까?"] + GOOD["questions"][1:]},        # 재료에 없는 종류
    {"questions": ["[핵심 인력] "] + GOOD["questions"][1:]},                   # 표시만 있고 질문 없음
    {"questions": ["[핵심 인력] 운용자산이 31% 줄었습니까?"] + GOOD["questions"][1:]},  # 새 숫자
    {"questions": [1, 2, 3]},                                               # 문자열 아님
    {"questions": "[핵심 인력] 질문"},                                        # 목록 아님
])
def test_bad_response_rerequested_once_then_ok(a11, monkeypatch, bad):
    out, fake = asked(monkeypatch, a11, MATS, bad, GOOD)
    assert len(fake.calls) == 2
    first, retry = fake.calls
    assert retry["user"].startswith(first["user"]) and len(retry["user"]) > len(first["user"])
    assert out == {"questions": GOOD["questions"], "warnings": []}


def test_number_from_signals_passes(a11, monkeypatch):
    ok = {"questions": ["[Peer 대비] 소형주 비중 27%는 의도한 수준입니까?"] + GOOD["questions"][1:]}
    out, fake = asked(monkeypatch, a11, MATS, ok)
    assert len(fake.calls) == 1 and out["questions"] == ok["questions"]


def test_whitespace_around_question_is_trimmed(a11, monkeypatch):
    padded = {"questions": ["  " + qq + "\n" for qq in GOOD["questions"]]}
    out, _ = asked(monkeypatch, a11, MATS, padded)
    assert out["questions"] == GOOD["questions"]


# ---------- 두 번 실패 → 반증 조건을 그대로, 미설명 재료부터 ----------
def test_twice_bad_falls_back_to_falsifiers_unexplained_first(a11, monkeypatch):
    bad = {"questions": ["질문 하나"]}
    out, fake = asked(monkeypatch, a11, [M_PA_K, M_PA_T, M_KP_K, M_KP_T], bad, bad)
    assert len(fake.calls) == 2
    assert out["questions"] == [f"[핵심 인력] {M_KP_K['falsifier']}",
                                f"[핵심 인력] {M_KP_T['falsifier']}",
                                f"[Peer 대비] {M_PA_K['falsifier']}"]
    assert out["warnings"] == [FALLBACK_WARNING]


# ---------- 결정 3: 3개가 안 되면 있는 만큼 + 경고 ----------
def test_two_materials_ask_for_two_and_warn(a11, monkeypatch):
    two = {"questions": GOOD["questions"][:2]}
    out, fake = asked(monkeypatch, a11, [M_KP_K, M_KP_T], two)
    assert "2개" in fake.calls[0]["user"]
    assert out["questions"] == two["questions"]
    assert out["warnings"] == ["미팅 질문 2개만 생성"]


def test_two_materials_fallback_gives_two_and_both_warnings(a11, monkeypatch):
    bad = {"questions": []}
    out, _ = asked(monkeypatch, a11, [M_KP_K, M_KP_T], bad, bad)
    assert len(out["questions"]) == 2
    assert out["warnings"] == [FALLBACK_WARNING, "미팅 질문 2개만 생성"]


def test_no_materials_no_call_and_warn(a11, monkeypatch):
    out, fake = asked(monkeypatch, a11, [])
    assert fake.calls == []
    assert out == {"questions": [], "warnings": ["미팅 질문 0개만 생성"]}


# ---------- LLM 오류 ----------
def test_llm_unavailable_propagates_from_questions(a11, monkeypatch):
    with pytest.raises(llm.LLMUnavailable):
        asked(monkeypatch, a11, MATS, llm.LLMUnavailable("API 오류"))
