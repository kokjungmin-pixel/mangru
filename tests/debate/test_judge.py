"""심판 입력 만들기 (src/debate/judge.py blind_input) 테스트. (Backend 문서 B3 "심판", B7, C장 6번 6-1)
LLM을 부르지 않는다. 무작위는 random.Random(seed) 를 넣어 고정한다.
"""
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
