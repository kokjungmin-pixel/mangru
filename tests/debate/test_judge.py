"""심판 (src/debate/judge.py) 테스트. (Backend 문서 B3 "심판", B4, B7, C장 6번 6-1·6-2)
6-1 blind_input 은 LLM을 부르지 않는다. 6-2 run_judge 는 call_llm 을 가짜로 바꾸거나 LLM_MOCK=1 고정 응답을 쓴다. 무작위는 random.Random(seed) 를 넣어 고정한다.
"""
import copy
import json
import random
import re

import pytest

from src import config, llm
from src.debate.judge import blind_input

A11_PATH = config.ROOT / "tests" / "debate" / "fixtures" / "a11_analysis.json"
KP, SD, PA = "demo1-key_person-1", "demo1-strategy_drift-1", "demo1-peer_anomaly-1"
IDS = [KP, SD, PA]
TAG = {"keep": "K", "terminate": "T"}     # 글에 '유지'·'해지'·keep 이 들어가지 않도록 측 표시는 K/T


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "1")
    llm.reset_call_count()
    yield
    llm.reset_call_count()


@pytest.fixture
def a11() -> dict:
    return json.loads(A11_PATH.read_text(encoding="utf-8"))


def record(ids=IDS) -> dict:
    """run_rounds 결과 모양의 토론 기록. 문장마다 어느 측·어느 단계인지 알 수 있게 만든다."""
    args = {side: [{"signal_id": sid, "claim": f"{t}-claim-{sid}", "evidence_idx": [0],
                    "falsifier": f"{t}-falsifier-{sid}"} for sid in ids]
            for side, t in TAG.items()}
    rebuttals = [{"round": rnd, "side": side, "signal_id": sid, "text": f"{t}-reb{rnd}-{sid}", "concede": False}
                 for rnd in (1, 2) for side, t in TAG.items() for sid in ids]
    return {"keep_args": args["keep"], "terminate_args": args["terminate"], "rebuttals": rebuttals}


def build(a11, seed=0, rec=None):
    rec = rec or record()
    return blind_input(a11, rec["keep_args"], rec["terminate_args"], rec["rebuttals"], random.Random(seed))


def section(user: str, sid: str) -> str:
    """사용자 글에서 한 신호의 부분만 잘라낸다 (## <sid> 부터 다음 ## 전까지)."""
    m = re.search(rf"^## {re.escape(sid)}.*?(?=^## |\Z)", user, re.S | re.M)
    assert m, f"{sid} 부분 없음"
    return m.group(0)


# ---------- 작성자 가리기 ----------
def test_sides_are_a_permutation_of_keep_and_terminate(a11):
    out = build(a11)
    assert set(out["sides"]) == {"A", "B"}
    assert sorted(out["sides"].values()) == ["keep", "terminate"]


def test_text_under_a_and_b_comes_from_mapped_side(a11):
    for seed in range(6):
        out = build(a11, seed)
        for label, side in out["sides"].items():
            t = TAG[side]
            for sid in IDS:
                part = section(out["user"], sid)
                assert f"{label}측 논거: {t}-claim-{sid}" in part
                assert f"{label}측 반증 조건: {t}-falsifier-{sid}" in part
                assert f"{label}측 반박 1회차: {t}-reb1-{sid}" in part
                assert f"{label}측 반박 2회차: {t}-reb2-{sid}" in part


def test_no_code_side_names_role_labels_or_model_names(a11, monkeypatch):
    models = {"KEEP": "gpt-5-mini", "TERMINATE": "gemini-3.8-flash", "JUDGE": "claude-sonnet-5-5"}
    for role, name in models.items():
        monkeypatch.setenv(f"MODEL_{role}", name)
    out = build(a11)
    text = out["system"] + "\n" + out["user"]
    for word in ("keep", "terminate"):
        assert word not in text.lower()
    for word in ("유지 측", "해지 측", "유지측", "해지측"):
        assert word not in text
    for name in models.values():
        assert name not in text
    for word in ("gpt", "gemini", "claude", "openai", "anthropic"):
        assert word not in text.lower()


# ---------- 무작위 순서 ----------
def test_a_side_assignment_varies_with_seed(a11):
    seen = {build(a11, seed)["sides"]["A"] for seed in range(20)}
    assert seen == {"keep", "terminate"}


def test_signal_order_is_shuffled_and_recorded(a11):
    orders = set()
    for seed in range(20):
        out = build(a11, seed)
        assert sorted(out["order"]) == sorted(IDS)
        pos = [out["user"].index(f"## {sid}") for sid in out["order"]]
        assert pos == sorted(pos)            # 글 속 순서 = 기록한 순서
        orders.add(tuple(out["order"]))
    assert len(orders) > 1


def test_same_seed_gives_same_input(a11):
    assert build(a11, 7) == build(a11, 7)


def test_input_arguments_are_not_mutated(a11):
    rec = record()
    before = json.dumps([a11, rec], ensure_ascii=False, sort_keys=True)
    build(a11, 3, rec)
    assert json.dumps([a11, rec], ensure_ascii=False, sort_keys=True) == before


# ---------- 심판에게 주는 자료 ----------
def test_user_has_strategy_signals_evidence_and_formatted_numbers(a11):
    user = build(a11)["user"]
    assert a11["stated_strategy"] in user
    for s in a11["signals"]:
        part = section(user, s["id"])
        assert s["summary"] in part
        assert "[0] " + s["evidence"][0]["source"] in part
    for token in ("+15%p", "상위 3%", "1.9배"):
        assert token in user
    assert "0.27" not in user


def test_missing_argument_or_rebuttal_is_shown_as_none(a11):
    rec = record()
    rec["keep_args"] = [a for a in rec["keep_args"] if a["signal_id"] != SD]
    rec["rebuttals"] = [r for r in rec["rebuttals"] if not (r["side"] == "terminate" and r["round"] == 2)]
    out = build(a11, 0, rec)
    keep_label = next(k for k, v in out["sides"].items() if v == "keep")
    term_label = next(k for k, v in out["sides"].items() if v == "terminate")
    assert f"{keep_label}측 논거: (없음)" in section(out["user"], SD)
    assert f"{term_label}측 반박 2회차: (없음)" in section(out["user"], KP)


def test_system_has_score_table_and_output_format(a11):
    system = build(a11)["system"]
    for rule in ("수치 0~3", "근거 0~3", "반박 0~2", "한계 0~2"):
        assert rule in system
    assert '"scores"' in build(a11)["user"]
    assert "결론" in system                     # 결론(권고)을 내리지 않는다


def test_blind_input_makes_no_llm_call(a11):
    build(a11)
    assert llm.call_count() == 0


# ======================================================================
# 6-2 심판 응답 검사와 A/B 되돌리기
# ======================================================================
from src.debate import judge as judge_mod          # noqa: E402
from src.debate.decide import status_of            # noqa: E402
from src.debate.judge import SCORE_MAX, check_judge, run_judge, valid_score   # noqa: E402
from src.mock_data import sample                   # noqa: E402
from src.state import ChangeVerdict                # noqa: E402
from src.validate import validate                  # noqa: E402

ZERO = {"numbers": 0, "grounds": 0, "rebuttal": 0, "limits": 0}


def sc(numbers, grounds, rebuttal, limits) -> dict:
    return {"numbers": numbers, "grounds": grounds, "rebuttal": rebuttal, "limits": limits}


# 측별 정답 점수: KP 유지 5 vs 해지 8(미설명), SD 유지 9 vs 해지 4(설명됨), PA 유지 6 vs 해지 6(동점 → 미설명)
TRUE = {KP: {"keep": sc(1, 2, 1, 1), "terminate": sc(2, 3, 2, 1)},
        SD: {"keep": sc(3, 3, 2, 1), "terminate": sc(1, 1, 1, 1)},
        PA: {"keep": sc(2, 2, 1, 1), "terminate": sc(1, 2, 2, 1)}}


def seed_with_a(a11, side: str) -> int:
    return next(s for s in range(50) if build(a11, s)["sides"]["A"] == side)


def scores_resp(sides: dict, ids=IDS, **override) -> dict:
    """심판이 낼 A/B 점수 응답. override[sid] = 행 전체 대체(None이면 뺀다)."""
    rows = []
    for sid in ids:
        if sid in override:
            if override[sid] is not None:
                rows.append(override[sid])
            continue
        rows.append({"signal_id": sid, "A": TRUE[sid][sides["A"]], "B": TRUE[sid][sides["B"]],
                     "reason": f"이유 {sid}"})
    return {"scores": rows}


class FakeJudge:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, role, system, user, json_keys=None, temperature=None):
        self.calls.append({"role": role, "system": system, "user": user, "json_keys": json_keys})
        return copy.deepcopy(self.responses.pop(0))


def judged(a11, monkeypatch, seed, *responses):
    fake = FakeJudge(*responses)
    monkeypatch.setattr(judge_mod, "call_llm", fake)
    rec = record()
    out = run_judge(a11, rec["keep_args"], rec["terminate_args"], rec["rebuttals"], random.Random(seed))
    return out, fake


# ---------- valid_score / check_judge (B4 코드) ----------
def test_valid_score_ranges_and_types():
    assert valid_score(sc(3, 3, 2, 2)) and valid_score(ZERO)
    assert not valid_score(sc(4, 0, 0, 0))
    assert not valid_score(sc(0, 0, 3, 0))
    assert not valid_score(sc(-1, 0, 0, 0))
    assert not valid_score(sc(1.0, 0, 0, 0))
    assert not valid_score(sc(True, 0, 0, 0))          # bool 은 정수로 치지 않는다
    assert not valid_score({"numbers": 1, "grounds": 1, "rebuttal": 1})
    assert not valid_score({**ZERO, "extra": 0})
    assert not valid_score(None) and not valid_score([0, 0, 0, 0])
    assert SCORE_MAX == {"numbers": 3, "grounds": 3, "rebuttal": 2, "limits": 2}


def test_check_judge_reports_unknown_missing_and_bad_scores():
    ids = {KP, SD}
    resp = {"scores": [
        {"signal_id": KP, "A": sc(1, 1, 1, 1), "B": sc(9, 0, 0, 0)},
        {"signal_id": "demo1-x-9", "A": ZERO, "B": ZERO},
    ]}
    problems = check_judge(resp, ids)
    assert any("모르는 signal_id: demo1-x-9" in p for p in problems)
    assert any(KP in p and "B측" in p for p in problems)
    assert any(p == f"점수 없음: {SD}" for p in problems)
    assert check_judge({"scores": [{"signal_id": s, "A": ZERO, "B": ZERO} for s in ids]}, ids) == []


# ---------- 결정 2: 0-0 은 decide.py 가 자동으로 미설명 ----------
def test_zero_zero_is_unexplained_by_decide():
    assert status_of(ZERO, ZERO) == "unexplained"


# ---------- 정상: A/B 복원 ----------
@pytest.mark.parametrize("a_side", ["keep", "terminate"])
def test_scores_restored_to_keep_and_terminate(a11, monkeypatch, a_side):
    seed = seed_with_a(a11, a_side)
    sides = build(a11, seed)["sides"]
    out, fake = judged(a11, monkeypatch, seed, scores_resp(sides))
    assert len(fake.calls) == 1 and fake.calls[0]["role"] == "judge"
    assert fake.calls[0]["json_keys"] == ["scores"]
    assert out["warnings"] == []
    for v in out["verdicts"]:
        validate(v, ChangeVerdict)
        assert v["keep"] == TRUE[v["signal_id"]]["keep"]
        assert v["terminate"] == TRUE[v["signal_id"]]["terminate"]
        assert v["reason"] == f"이유 {v['signal_id']}"


def test_status_is_decided_by_code_from_scores(a11, monkeypatch):
    seed = seed_with_a(a11, "terminate")
    out, _ = judged(a11, monkeypatch, seed, scores_resp(build(a11, seed)["sides"]))
    status = {v["signal_id"]: v["status"] for v in out["verdicts"]}
    assert status == {KP: "unexplained", SD: "explained", PA: "unexplained"}


def test_verdicts_follow_original_signal_order_not_shuffled_order(a11, monkeypatch):
    seed = next(s for s in range(50) if build(a11, s)["order"] != IDS)
    sides = build(a11, seed)["sides"]
    shuffled = build(a11, seed)["order"]
    out, _ = judged(a11, monkeypatch, seed, scores_resp(sides, ids=shuffled))
    assert [v["signal_id"] for v in out["verdicts"]] == IDS


def test_judge_gets_blind_input(a11, monkeypatch):
    seed = 4
    expected = build(a11, seed)
    out, fake = judged(a11, monkeypatch, seed, scores_resp(expected["sides"]))
    assert fake.calls[0]["system"] == expected["system"]
    assert fake.calls[0]["user"] == expected["user"]


# ---------- 재요청 ----------
def test_bad_scores_rerequested_once_then_ok(a11, monkeypatch):
    seed = 0
    sides = build(a11, seed)["sides"]
    bad = scores_resp(sides, **{SD: {"signal_id": SD, "A": sc(4, 0, 0, 0), "B": ZERO, "reason": "r"}})
    out, fake = judged(a11, monkeypatch, seed, bad, scores_resp(sides))
    assert len(fake.calls) == 2
    first, retry = fake.calls
    assert retry["user"].startswith(first["user"]) and retry["system"] == first["system"]
    assert SD in retry["user"][len(first["user"]):]
    assert out["warnings"] == []
    assert next(v for v in out["verdicts"] if v["signal_id"] == SD)["keep"] == TRUE[SD]["keep"]


def test_missing_signal_rerequested_once_then_ok(a11, monkeypatch):
    seed = 0
    sides = build(a11, seed)["sides"]
    out, fake = judged(a11, monkeypatch, seed, scores_resp(sides, **{PA: None}), scores_resp(sides))
    assert len(fake.calls) == 2 and f"점수 없음: {PA}" in fake.calls[1]["user"]
    assert out["warnings"] == []


# ---------- 결정 2: 재요청 후에도 틀리면 양측 0점 + 미설명 + warnings ----------
@pytest.mark.parametrize("bad_row", [
    None,                                                                  # 빠짐
    {"signal_id": SD, "A": sc(1, 1, 1, 1), "B": sc(1, 1, 3, 1), "reason": "r"},  # 범위 밖
    {"signal_id": SD, "A": sc(1, 1, 1, 1), "reason": "r"},                  # B 없음
])
def test_still_bad_after_retry_gives_zero_zero_unexplained(a11, monkeypatch, bad_row):
    seed = seed_with_a(a11, "keep")
    sides = build(a11, seed)["sides"]
    bad = scores_resp(sides, **{SD: bad_row})
    out, fake = judged(a11, monkeypatch, seed, bad, bad)
    assert len(fake.calls) == 2                       # 재요청은 1회까지
    v = next(v for v in out["verdicts"] if v["signal_id"] == SD)
    assert v["keep"] == ZERO and v["terminate"] == ZERO
    assert v["status"] == "unexplained"
    assert v["reason"] == "심판 점수 확인 불가"
    assert out["warnings"] == [f"심판 점수 확인 불가: {SD}"]
    validate(v, ChangeVerdict)
    others = [v for v in out["verdicts"] if v["signal_id"] != SD]
    assert all(v["reason"].startswith("이유") for v in others)


def test_duplicate_rows_use_first(a11, monkeypatch):
    seed = 0
    sides = build(a11, seed)["sides"]
    resp = scores_resp(sides)
    resp["scores"].append({"signal_id": KP, "A": ZERO, "B": ZERO, "reason": "중복"})
    out, fake = judged(a11, monkeypatch, seed, resp)
    assert len(fake.calls) == 1
    assert next(v for v in out["verdicts"] if v["signal_id"] == KP)["reason"] == f"이유 {KP}"


def test_non_string_reason_becomes_empty(a11, monkeypatch):
    seed = 0
    sides = build(a11, seed)["sides"]
    resp = scores_resp(sides)
    resp["scores"][0]["reason"] = 3
    out, _ = judged(a11, monkeypatch, seed, resp)
    v = out["verdicts"][0]
    validate(v, ChangeVerdict)
    assert v["reason"] == ""


def test_llm_unavailable_propagates_from_judge(a11, monkeypatch):
    def boom(*a, **k):
        raise llm.LLMUnavailable("API 오류")
    monkeypatch.setattr(judge_mod, "call_llm", boom)
    rec = record()
    with pytest.raises(llm.LLMUnavailable):
        run_judge(a11, rec["keep_args"], rec["terminate_args"], rec["rebuttals"], random.Random(0))


# ---------- LLM_MOCK=1 고정 응답 (A측 = 유지 측) ----------
def test_mock_judge_matches_contract_sample_when_a_is_keep():
    analysis = sample("analysis")
    rec = sample("debate")
    seed = next(s for s in range(50)
                if blind_input(analysis, [], [], [], random.Random(s))["sides"]["A"] == "keep")
    out = run_judge(analysis, rec["keep_args"], rec["terminate_args"], rec["rebuttals"], random.Random(seed))
    assert llm.call_count() == 1
    assert out["verdicts"] == rec["verdicts"]
    assert out["warnings"] == []


@pytest.mark.parametrize("scores", [{"x": 1}, "문자열", ["행이 문자열", 3]])
def test_malformed_scores_do_not_crash_and_fall_back(a11, monkeypatch, scores):
    assert check_judge({"scores": scores}, set(IDS))            # 멈추지 않고 문제로 적는다
    out, fake = judged(a11, monkeypatch, 0, {"scores": scores}, {"scores": scores})
    assert len(fake.calls) == 2
    assert all(v["reason"] == "심판 점수 확인 불가" and v["status"] == "unexplained" for v in out["verdicts"])
    assert out["warnings"] == [f"심판 점수 확인 불가: {sid}" for sid in IDS]
