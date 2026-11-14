"""src/llm.py 테스트 — 실제 API를 부르지 않는다. (Backend 문서 B2 "src/llm.py")
실제 호출 함수 _send_real 은 가짜로 바꿔 끼워 재시도·재요청·상한·기록을 검사한다.
"""
import json

import pytest

from src import config, llm
from src.llm import LLMUnavailable, call_llm, extract_json, reset_call_count


# ---------- 공통 준비 ----------
@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    reset_call_count()
    monkeypatch.setattr(llm, "LOG_PATH", tmp_path / "logs" / "llm_calls.jsonl")
    sleeps = []
    monkeypatch.setattr(llm, "_sleep", sleeps.append)
    yield sleeps
    reset_call_count()


@pytest.fixture
def real(monkeypatch):
    """LLM_MOCK=0 + 모델 환경변수 + 가짜 _send_real. responses 에 넣은 순서대로 응답(예외면 raise)."""
    monkeypatch.setenv("LLM_MOCK", "0")
    for role in ("KEEP", "TERMINATE", "JUDGE", "ANALYST"):
        monkeypatch.setenv(f"MODEL_{role}", f"model-{role.lower()}")

    class Fake:
        def __init__(self):
            self.responses = []
            self.sent = []          # (role, model, system, user, temperature)

        def __call__(self, role, model, system, user, temperature):
            self.sent.append((role, model, system, user, temperature))
            r = self.responses.pop(0)
            if isinstance(r, Exception):
                raise r
            return r, 11, 7       # (응답 텍스트, 입력 토큰, 출력 토큰)

    fake = Fake()
    monkeypatch.setattr(llm, "_send_real", fake)
    return fake


# ---------- extract_json ----------
def test_extract_json_plain():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_with_prose_and_code_fence():
    text = '네, 결과입니다.\n```json\n{"arguments": [{"signal_id": "s1"}]}\n```\n이상입니다.'
    assert extract_json(text) == {"arguments": [{"signal_id": "s1"}]}


@pytest.mark.parametrize("text", ["JSON 없음", "", "} 거꾸로 {", '{"a": 1,,}'])
def test_extract_json_raises_value_error(text):
    with pytest.raises(ValueError):
        extract_json(text)


# ---------- LLM_MOCK=1 ----------
@pytest.fixture
def mock(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "1")
    monkeypatch.delenv("MODEL_KEEP", raising=False)   # 모델 설정 없이도 돈다


@pytest.mark.parametrize("role,key", [
    ("keep", "arguments"), ("terminate", "arguments"),
    ("keep", "rebuttals"), ("terminate", "rebuttals"),
    ("judge", "scores"), ("keep", "questions"),
])
def test_mock_returns_fixture_for_each_debate_step(mock, role, key):
    out = call_llm(role, "시스템", "사용자", json_keys=[key])
    assert isinstance(out, dict) and isinstance(out[key], list) and out[key]


def test_mock_fixture_matches_contract_sample_ids(mock):
    out = call_llm("judge", "s", "u", json_keys=["scores"])
    assert {r["signal_id"] for r in out["scores"]} == {"demo1-key_person-1", "demo1-strategy_drift-1"}


def test_mock_without_fixture_is_unavailable(mock):
    with pytest.raises(LLMUnavailable):
        call_llm("analyst", "s", "u", json_keys=["explanations"])


def test_mock_counts_calls_but_writes_no_log(mock):
    for _ in range(3):
        call_llm("keep", "s", "u", json_keys=["arguments"])
    assert llm.call_count() == 3
    assert not llm.LOG_PATH.exists()
    reset_call_count()
    assert llm.call_count() == 0


def test_mock_is_default_when_env_missing(monkeypatch):
    monkeypatch.delenv("LLM_MOCK", raising=False)
    monkeypatch.setattr(llm, "_send_real", lambda *a: pytest.fail("실제 호출이 일어나면 안 됨"))
    assert "arguments" in call_llm("keep", "s", "u", json_keys=["arguments"])


# ---------- 역할·모델·온도 ----------
def test_unknown_role_is_value_error(real):
    with pytest.raises(ValueError):
        call_llm("referee", "s", "u")
    assert real.sent == []


def test_role_goes_to_env_model_with_default_temperature(real):
    real.responses = ["답", "답"]
    call_llm("keep", "s", "u")
    call_llm("judge", "s", "u")
    assert [(r, m, t) for r, m, _, _, t in real.sent] == [
        ("keep", "model-keep", config.TEMPERATURE["keep"]),
        ("judge", "model-judge", config.TEMPERATURE["judge"]),
    ]


def test_explicit_temperature_wins(real):
    real.responses = ["답"]
    call_llm("keep", "s", "u", temperature=0.7)
    assert real.sent[0][4] == 0.7


def test_missing_model_env_is_unavailable_without_sending(real, monkeypatch):
    monkeypatch.delenv("MODEL_TERMINATE")
    with pytest.raises(LLMUnavailable, match="MODEL_TERMINATE"):
        call_llm("terminate", "s", "u")
    assert real.sent == [] and llm.call_count() == 0


# ---------- JSON 읽기와 키 검사 ----------
def test_text_mode_returns_raw_string(real):
    real.responses = ["그냥 글"]
    assert call_llm("analyst", "s", "u") == "그냥 글"


def test_json_ok_first_try(real):
    real.responses = ['```json\n{"arguments": [], "extra": 1}\n```']
    assert call_llm("keep", "s", "u", json_keys=["arguments"]) == {"arguments": [], "extra": 1}
    assert len(real.sent) == 1


def test_missing_key_is_re_requested_once_with_error(real):
    real.responses = ['{"argument": []}', '{"arguments": []}']
    assert call_llm("keep", "s", "원래 질문", json_keys=["arguments"]) == {"arguments": []}
    assert len(real.sent) == 2
    retry_user = real.sent[1][3]
    assert retry_user.startswith("원래 질문")
    assert "arguments" in retry_user and "argument" in retry_user   # 빠진 키와 받은 키를 알려 준다


def test_broken_json_is_re_requested_once(real):
    real.responses = ["JSON을 못 만들었습니다", '{"scores": []}']
    assert call_llm("judge", "s", "u", json_keys=["scores"]) == {"scores": []}
    assert len(real.sent) == 2


def test_json_wrong_twice_is_unavailable(real):
    real.responses = ['{"x": 1}', "여전히 아님"]
    with pytest.raises(LLMUnavailable):
        call_llm("keep", "s", "u", json_keys=["arguments"])
    assert len(real.sent) == 2


def test_non_object_json_is_rejected(real):
    real.responses = ['[1, 2]', '{"arguments": []}']
    assert call_llm("keep", "s", "u", json_keys=["arguments"]) == {"arguments": []}
    assert len(real.sent) == 2


# ---------- API 오류 재시도 ----------
def test_api_error_retried_with_backoff_then_success(real, _isolate):
    real.responses = [RuntimeError("503"), TimeoutError("느림"), "답"]
    assert call_llm("keep", "s", "u") == "답"
    assert len(real.sent) == config.API_RETRIES == 3
    assert _isolate == [1, 2]          # 시도 사이 대기 1초, 2초


def test_api_error_three_times_is_unavailable(real, _isolate):
    real.responses = [RuntimeError("a"), RuntimeError("b"), RuntimeError("c")]
    with pytest.raises(LLMUnavailable):
        call_llm("keep", "s", "u")
    assert len(real.sent) == 3
    assert _isolate == [1, 2]


def test_unavailable_from_sender_is_not_retried(real, _isolate):
    real.responses = [LLMUnavailable("설정 문제")]
    with pytest.raises(LLMUnavailable):
        call_llm("keep", "s", "u")
    assert len(real.sent) == 1 and _isolate == []


# ---------- 호출 상한 ----------
def test_call_cap_blocks_extra_calls_until_reset(real, monkeypatch):
    monkeypatch.setattr(config, "MAX_LLM_CALLS_PER_RUN", 2)
    real.responses = ["1", "2", "3"]
    call_llm("keep", "s", "u")
    call_llm("keep", "s", "u")
    with pytest.raises(LLMUnavailable, match="상한"):
        call_llm("keep", "s", "u")
    assert len(real.sent) == 2
    reset_call_count()
    assert call_llm("keep", "s", "u") == "3"


def test_count_is_requests_re_request_counts_api_retry_does_not(real):
    """호출 수 = call_llm 1번 + 형식 오류 재요청 1번. API 오류 재시도는 세지 않는다."""
    real.responses = [RuntimeError("x"), '{"a": 1}', RuntimeError("y"), '{"arguments": []}']
    call_llm("keep", "s", "u", json_keys=["arguments"])
    assert len(real.sent) == 4
    assert llm.call_count() == 2


def test_api_retries_do_not_hit_the_cap(real, monkeypatch):
    """상한 32는 정상 10번 × 3 + 2로 잡혀 있어 재시도까지 세면 정상 실행이 멈출 수 있다."""
    monkeypatch.setattr(config, "MAX_LLM_CALLS_PER_RUN", 1)
    real.responses = [RuntimeError("503"), RuntimeError("503"), "답"]
    assert call_llm("keep", "s", "u") == "답"
    assert llm.call_count() == 1


def test_api_retries_are_logged(real):
    real.responses = [RuntimeError("503"), RuntimeError("503"), "답"]
    call_llm("keep", "s", "u")
    assert [r["ok"] for r in _log_lines()] == [False, False, True]
    assert llm.call_count() == 1


# ---------- 호출 기록 ----------
def _log_lines():
    return [json.loads(l) for l in llm.LOG_PATH.read_text(encoding="utf-8").splitlines()]


def test_log_one_line_per_request_without_prompt(real):
    real.responses = [RuntimeError("503"), "응답 본문 비밀"]
    call_llm("judge", "시스템 프롬프트 본문", "사용자 프롬프트 본문")
    lines = _log_lines()
    assert len(lines) == 2
    for row in lines:
        assert set(row) == {"ts", "role", "model", "input_tokens", "output_tokens", "seconds", "ok"}
        assert row["role"] == "judge" and row["model"] == "model-judge"
    assert [r["ok"] for r in lines] == [False, True]
    assert (lines[1]["input_tokens"], lines[1]["output_tokens"]) == (11, 7)
    raw = llm.LOG_PATH.read_text(encoding="utf-8")
    assert "프롬프트 본문" not in raw and "응답 본문" not in raw
