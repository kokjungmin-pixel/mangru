"""토론 독립 작성 → 반박 2회 (src/debate/rounds.py) 테스트. (Backend 문서 B3, B7, C장 5번)
LLM_MOCK=1. 응답 검사를 시험할 때는 call_llm 을 순서대로 응답하는 가짜로 바꿔 끼운다.
"""
import copy
import json

import pytest

from src import config, llm
from src.debate import rounds
from src.debate.rounds import material, run_rounds
from src.mock_data import sample
from src.state import AnalysisResult, Argument, Rebuttal
from src.validate import validate

A11_PATH = config.ROOT / "tests" / "debate" / "fixtures" / "a11_analysis.json"
KP, SD, PA = "demo1-key_person-1", "demo1-strategy_drift-1", "demo1-peer_anomaly-1"
IDS = [KP, SD, PA]


@pytest.fixture
def a11() -> dict:
    return json.loads(A11_PATH.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "1")
    llm.reset_call_count()
    yield
    llm.reset_call_count()


# ---------- 가짜 call_llm ----------
def args_resp(prefix: str, ids=IDS, **override) -> dict:
    """신호마다 숫자 없는 정상 논거. override[sid] 로 특정 신호의 항목을 바꾼다(None이면 뺀다)."""
    out = []
    for sid in ids:
        item = {"signal_id": sid, "claim": f"{prefix} 논거 {sid}", "evidence_idx": [0],
                "falsifier": f"{prefix} 반증 조건 {sid}"}
        if sid in override:
            if override[sid] is None:
                continue
            item.update(override[sid])
        out.append(item)
    return {"arguments": out}


def reb_resp(prefix: str, ids=IDS, **override) -> dict:
    out = []
    for sid in ids:
        item = {"signal_id": sid, "text": f"{prefix} 반박 {sid}", "concede": False}
        if sid in override:
            if override[sid] is None:
                continue
            item.update(override[sid])
        out.append(item)
    return {"rebuttals": out}


class FakeLLM:
    """(role, 첫 json 키) 마다 응답 목록을 앞에서부터 돌려준다. 목록이 비면 기본 정상 응답."""

    def __init__(self):
        self.queue: dict[tuple[str, str], list[dict]] = {}
        self.calls: list[dict] = []

    def add(self, role: str, key: str, *responses: dict):
        self.queue.setdefault((role, key), []).extend(responses)

    def __call__(self, role, system, user, json_keys=None, temperature=None):
        key = json_keys[0]
        self.calls.append({"role": role, "key": key, "system": system, "user": user})
        q = self.queue.get((role, key))
        if q:
            return copy.deepcopy(q.pop(0))
        n = sum(1 for c in self.calls if c["role"] == role and c["key"] == key)
        return args_resp(role) if key == "arguments" else reb_resp(f"{role}{n}")

    def of(self, role, key):
        return [c for c in self.calls if c["role"] == role and c["key"] == key]


def feedback(first: dict, retry: dict) -> str:
    """재요청은 처음 질문 뒤에 검사 결과를 붙인다. 붙인 부분만 돌려준다."""
    assert retry["user"].startswith(first["user"]) and retry["system"] == first["system"]
    return retry["user"][len(first["user"]):]


@pytest.fixture
def fake(monkeypatch) -> FakeLLM:
    f = FakeLLM()
    monkeypatch.setattr(rounds, "call_llm", f)
    return f


# ---------- 입력 fixture ----------
def test_a11_fixture_is_valid_analysis_with_three_signals(a11):
    validate(a11, AnalysisResult)
    assert [s["id"] for s in a11["signals"]] == IDS
    assert a11["debate_required"] is True


# ---------- 양측에게 주는 자료 ----------
def test_material_has_strategy_signals_numbered_evidence(a11):
    text, warnings = material(a11)
    assert warnings == []
    assert a11["stated_strategy"] in text
    assert "We invest primarily in U.S. large-capitalization equities" in text
    for s in a11["signals"]:
        assert s["id"] in text and s["summary"] in text and s["explanation"] in text
    assert "[0] Form 13F 2026Q3" in text
    assert "45일" in text          # 데이터 한계 안내


def test_material_gives_formatted_numbers_not_raw_values(a11):
    text, _ = material(a11)
    for token in ("12%", "27%", "+15%p", "+14%p", "상위 3%", "14%", "1.9배", "상위 4%"):
        assert token in text
    for raw in ("0.27", "0.12", "0.97", "0.15"):
        assert raw not in text


def test_material_without_stated_strategy_warns(a11):
    a11["stated_strategy"] = None
    a11["stated_strategy_evidence"] = []
    text, warnings = material(a11)
    assert "운용사가 밝힌 전략을 확인할 수 없음" in text
    assert warnings == ["운용사가 밝힌 전략을 확인할 수 없음"]


# ---------- 정상 흐름 ----------
def test_normal_flow_is_six_calls_in_order(a11, fake):
    out = run_rounds(a11)
    assert [(c["role"], c["key"]) for c in fake.calls] == [
        ("keep", "arguments"), ("terminate", "arguments"),
        ("keep", "rebuttals"), ("terminate", "rebuttals"),
        ("keep", "rebuttals"), ("terminate", "rebuttals"),
    ]
    assert out["warnings"] == []
    assert [a["signal_id"] for a in out["keep_args"]] == IDS
    assert [a["signal_id"] for a in out["terminate_args"]] == IDS
    assert len(out["rebuttals"]) == 12
    for a in out["keep_args"] + out["terminate_args"]:
        validate(a, Argument)
    for r in out["rebuttals"]:
        validate(r, Rebuttal)


def test_round_and_side_are_filled_by_code(a11, fake):
    out = run_rounds(a11)
    got = {(r["round"], r["side"]) for r in out["rebuttals"]}
    assert got == {(1, "keep"), (1, "terminate"), (2, "keep"), (2, "terminate")}
    r = next(r for r in out["rebuttals"] if r["round"] == 2 and r["side"] == "terminate")
    assert r["text"].startswith("terminate2 반박")


def test_opening_is_independent_and_rebuttals_see_opponent(a11, fake):
    run_rounds(a11)
    keep_open, keep_r1, keep_r2 = fake.of("keep", "arguments")[0], *fake.of("keep", "rebuttals")
    term_open = fake.of("terminate", "arguments")[0]
    # 독립 작성: 상대의 글을 보지 않는다
    assert "keep 논거" not in term_open["user"] and "terminate 논거" not in keep_open["user"]
    # 반박 1회차: 상대의 논거를 받는다
    assert f"terminate 논거 {KP}" in keep_r1["user"]
    # 반박 2회차: 상대의 1회차 반박을 받는다
    assert f"terminate1 반박 {KP}" in keep_r2["user"]


def test_each_side_gets_its_own_system_prompt_and_same_material(a11, fake):
    run_rounds(a11)
    keep_open = fake.of("keep", "arguments")[0]
    term_open = fake.of("terminate", "arguments")[0]
    assert keep_open["system"] != term_open["system"]
    assert "유지" in keep_open["system"] and "해지" in term_open["system"]
    text, _ = material(a11)
    assert text in keep_open["user"] and text in term_open["user"]


# ---------- 검사 1: 모든 신호에 논거 ----------
def test_missing_argument_rerequested_once_then_ok(a11, fake):
    fake.add("keep", "arguments", args_resp("keep", **{PA: None}), args_resp("keep"))
    out = run_rounds(a11)
    first, retry = fake.of("keep", "arguments")
    assert PA in feedback(first, retry)
    assert [a["signal_id"] for a in out["keep_args"]] == IDS
    assert out["warnings"] == []


def test_missing_argument_twice_leaves_gap_and_warns(a11, fake):
    bad = args_resp("keep", **{PA: None})
    fake.add("keep", "arguments", bad, bad)
    out = run_rounds(a11)
    assert len(fake.of("keep", "arguments")) == 2          # 재요청은 1회까지
    assert [a["signal_id"] for a in out["keep_args"]] == [KP, SD]
    assert f"유지 측 논거 없음: {PA}" in out["warnings"]


def test_unknown_signal_id_and_duplicates_are_dropped(a11, fake):
    resp = args_resp("terminate")
    resp["arguments"].append({"signal_id": "demo1-x-9", "claim": "c", "evidence_idx": [0], "falsifier": "f"})
    resp["arguments"].append({**resp["arguments"][0], "claim": "중복"})
    fake.add("terminate", "arguments", resp)
    out = run_rounds(a11)
    assert [a["signal_id"] for a in out["terminate_args"]] == IDS
    assert all(a["claim"] != "중복" for a in out["terminate_args"])


def test_malformed_argument_counts_as_missing(a11, fake):
    bad = args_resp("keep", **{SD: {"evidence_idx": "0"}})     # 목록이 아님
    fake.add("keep", "arguments", bad, bad)
    out = run_rounds(a11)
    assert SD not in [a["signal_id"] for a in out["keep_args"]]
    assert f"유지 측 논거 없음: {SD}" in out["warnings"]


# ---------- 검사 2: 근거 번호 ----------
def test_out_of_range_evidence_idx_removed_without_rerequest(a11, fake):
    fake.add("keep", "arguments", args_resp("keep", **{KP: {"evidence_idx": [0, 5, -1]}}))
    out = run_rounds(a11)
    assert len(fake.of("keep", "arguments")) == 1
    assert out["keep_args"][0]["evidence_idx"] == [0]
    assert out["warnings"] == []


def test_no_valid_evidence_idx_deletes_argument_and_warns(a11, fake):
    fake.add("keep", "arguments", args_resp("keep", **{KP: {"evidence_idx": [1]}}))
    out = run_rounds(a11)
    assert len(fake.of("keep", "arguments")) == 1
    assert KP not in [a["signal_id"] for a in out["keep_args"]]
    assert f"유지 측 논거 삭제(근거 번호 없음): {KP}" in out["warnings"]


def test_bool_is_not_evidence_index(a11, fake):
    bad = args_resp("keep", **{KP: {"evidence_idx": [True]}})   # True == 1 이지만 번호가 아니다 → 형식 오류
    fake.add("keep", "arguments", bad, bad)
    out = run_rounds(a11)
    assert len(fake.of("keep", "arguments")) == 2
    assert KP not in [a["signal_id"] for a in out["keep_args"]]
    assert f"유지 측 논거 없음: {KP}" in out["warnings"]


# ---------- 검사 3: 새 숫자 ----------
def test_unknown_number_rerequested_then_deleted_and_warned(a11, fake):
    bad = args_resp("terminate", **{SD: {"claim": "소형주 비중이 31% 늘었습니다."}})
    fake.add("terminate", "arguments", bad, bad)
    out = run_rounds(a11)
    calls = fake.of("terminate", "arguments")
    assert len(calls) == 2 and "31%" in feedback(*calls)
    assert SD not in [a["signal_id"] for a in out["terminate_args"]]
    assert f"해지 측 논거 삭제(신호에 없는 숫자 31%): {SD}" in out["warnings"]


def test_unknown_number_in_falsifier_is_checked(a11, fake):
    fake.add("keep", "arguments", args_resp("keep", **{PA: {"falsifier": "중앙값이 20% 이상이면"}}),
             args_resp("keep"))
    out = run_rounds(a11)
    assert len(fake.of("keep", "arguments")) == 2
    assert out["warnings"] == []


def test_number_from_other_signal_passes(a11, fake):
    # 인력 신호 논거 속 소형주 신호의 숫자 → 그 운용사 신호 전체 기준이라 통과
    fake.add("terminate", "arguments",
             args_resp("terminate", **{KP: {"claim": "CIO 이탈과 소형주 비중 +15%p (상위 3%)가 겹칩니다."}}))
    out = run_rounds(a11)
    assert len(fake.of("terminate", "arguments")) == 1
    assert out["terminate_args"][0]["claim"].startswith("CIO 이탈")
    assert out["warnings"] == []


def test_one_rerequest_covers_both_problems(a11, fake):
    bad = args_resp("keep", **{PA: None, SD: {"claim": "31% 증가"}})
    fake.add("keep", "arguments", bad, args_resp("keep"))
    out = run_rounds(a11)
    calls = fake.of("keep", "arguments")
    assert len(calls) == 2
    assert PA in feedback(*calls) and "31%" in feedback(*calls)
    assert out["warnings"] == []


# ---------- 반박 검사 ----------
def test_missing_rebuttal_rerequested_then_warned(a11, fake):
    bad = reb_resp("t", **{SD: None})
    fake.add("terminate", "rebuttals", bad, bad)
    out = run_rounds(a11)
    assert len(fake.of("terminate", "rebuttals")) == 3    # 1회차 2번 + 2회차 1번
    assert f"해지 측 반박 없음(1회차): {SD}" in out["warnings"]
    r1 = [r for r in out["rebuttals"] if r["round"] == 1 and r["side"] == "terminate"]
    assert [r["signal_id"] for r in r1] == [KP, PA]


def test_rebuttal_with_unknown_number_deleted(a11, fake):
    bad = reb_resp("k", **{KP: {"text": "운용자산이 $3B 줄었습니다."}})
    fake.add("keep", "rebuttals", reb_resp("k"), bad, bad)
    out = run_rounds(a11)
    assert f"유지 측 반박 삭제(2회차, 신호에 없는 숫자 $3B): {KP}" in out["warnings"]


def test_non_bool_concede_is_malformed(a11, fake):
    bad = reb_resp("k", **{KP: {"concede": "false"}})
    fake.add("keep", "rebuttals", bad, bad)
    out = run_rounds(a11)
    assert f"유지 측 반박 없음(1회차): {KP}" in out["warnings"]


# ---------- 입장 고정 (B5) ----------
def test_concede_in_round1_warns_debate_insufficient_and_keeps_going(a11, fake):
    fake.add("keep", "rebuttals", reb_resp("k", **{SD: {"concede": True}}))
    out = run_rounds(a11)
    assert len(fake.calls) == 6
    assert out["warnings"] == [f"토론 불충분: {SD}"]
    r = next(r for r in out["rebuttals"] if r["round"] == 1 and r["side"] == "keep" and r["signal_id"] == SD)
    assert r["concede"] is True


def test_concede_by_both_sides_warns_once(a11, fake):
    fake.add("keep", "rebuttals", reb_resp("k", **{SD: {"concede": True}}))
    fake.add("terminate", "rebuttals", reb_resp("t", **{SD: {"concede": True}}))
    out = run_rounds(a11)
    assert out["warnings"].count(f"토론 불충분: {SD}") == 1


def test_concede_in_round2_has_no_warning(a11, fake):
    fake.add("keep", "rebuttals", reb_resp("k1"), reb_resp("k2", **{SD: {"concede": True}}))
    out = run_rounds(a11)
    assert out["warnings"] == []


# ---------- LLM 오류 ----------
def test_llm_unavailable_propagates(a11, monkeypatch):
    def boom(*a, **k):
        raise llm.LLMUnavailable("API 오류")
    monkeypatch.setattr(rounds, "call_llm", boom)
    with pytest.raises(llm.LLMUnavailable):
        run_rounds(a11)


# ---------- LLM_MOCK=1 고정 응답으로 끝까지 ----------
def test_mock_end_to_end_on_contract_sample():
    analysis = sample("analysis")
    out = run_rounds(analysis)
    assert llm.call_count() == 6
    assert out["warnings"] == []
    ids = [s["id"] for s in analysis["signals"]]
    assert [a["signal_id"] for a in out["keep_args"]] == ids
    assert [a["signal_id"] for a in out["terminate_args"]] == ids
    assert len(out["rebuttals"]) == 2 * 2 * len(ids)
