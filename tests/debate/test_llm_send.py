"""src/llm.py _send_real 테스트 — 실제 API를 부르지 않는다. (Backend 문서 B2)
SDK 클라이언트를 만드는 함수(_anthropic_client, _openai_client)를 가짜로 바꿔 끼워
회사별로 보내는 값과 받은 값 처리를 검사한다.
"""
from types import SimpleNamespace as NS

import anthropic
import httpx2
import openai
import pytest

from src import config, llm
from src.llm import LLMUnavailable, _send_real, call_llm


class FakeCreate:
    """client.messages.create / client.chat.completions.create 대신. 받은 인자를 남기고 정해 둔 응답을 돌려준다.
    response 가 예외면 raise 한다."""
    def __init__(self, response):
        self.response = response
        self.kwargs = None
        self.calls = 0

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        self.calls += 1
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


_REQ = httpx2.Request("POST", "https://example.invalid/v1")


def _status_error(sdk, status):
    """SDK 의 진짜 상태 오류 객체 (예: 401 → AuthenticationError)."""
    cls = {401: sdk.AuthenticationError, 403: sdk.PermissionDeniedError,
           404: sdk.NotFoundError, 429: sdk.RateLimitError, 500: sdk.InternalServerError}[status]
    return cls("오류 본문", response=httpx2.Response(status, request=_REQ), body=None)


def _claude_response(blocks, stop_reason="end_turn", in_tok=12, out_tok=5):
    return NS(content=blocks, stop_reason=stop_reason, usage=NS(input_tokens=in_tok, output_tokens=out_tok))


def _openai_response(text, in_tok=9, out_tok=4):
    return NS(choices=[NS(message=NS(content=text))], usage=NS(prompt_tokens=in_tok, completion_tokens=out_tok))


@pytest.fixture
def keys(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.setenv(k, f"test-{k}")


@pytest.fixture
def claude(monkeypatch, keys):
    create = FakeCreate(_claude_response([NS(type="text", text='{"a": 1}')]))
    made = []

    def factory(api_key):
        made.append(api_key)
        return NS(messages=NS(create=create))

    monkeypatch.setattr(llm, "_anthropic_client", factory)
    return NS(create=create, made=made)


@pytest.fixture
def openai_like(monkeypatch, keys):
    create = FakeCreate(_openai_response("답"))
    made = []

    def factory(api_key, base_url):
        made.append((api_key, base_url))
        return NS(chat=NS(completions=NS(create=create)))

    monkeypatch.setattr(llm, "_openai_client", factory)
    return NS(create=create, made=made)


# ---------- 회사 고르기 ----------
@pytest.mark.parametrize("model,provider", [
    ("claude-sonnet-5-5", "anthropic"),
    ("gemini-2.5-flash", "gemini"),
    ("gpt-5-mini", "openai"),
])
def test_provider_by_model_prefix(model, provider):
    assert llm._provider(model) == provider


def test_unknown_model_prefix_is_unavailable():
    with pytest.raises(LLMUnavailable):
        llm._provider("llama-3")


# ---------- Claude ----------
def test_claude_sends_system_user_and_no_temperature(claude):
    text, i, o = _send_real("judge", "claude-sonnet-5-5", "시스템", "사용자", 0.0)
    assert (text, i, o) == ('{"a": 1}', 12, 5)
    kw = claude.create.kwargs
    assert kw["model"] == "claude-sonnet-5-5"
    assert kw["system"] == "시스템"
    assert kw["messages"] == [{"role": "user", "content": "사용자"}]
    assert kw["max_tokens"] == llm.MAX_OUTPUT_TOKENS
    assert "temperature" not in kw          # API 2026-10-21 은 temperature 를 받지 않음
    assert claude.made == ["test-ANTHROPIC_API_KEY"]


def test_claude_joins_text_blocks_and_skips_thinking(claude):
    claude.create.response = _claude_response([
        NS(type="thinking", thinking=""), NS(type="text", text='{"a":'), NS(type="text", text=' 1}')])
    text, _, _ = _send_real("judge", "claude-sonnet-5-5", "s", "u", 0.0)
    assert text == '{"a": 1}'


def test_claude_refusal_is_unavailable(claude):
    claude.create.response = _claude_response([], stop_reason="refusal")
    with pytest.raises(LLMUnavailable, match="거절"):
        _send_real("judge", "claude-sonnet-5-5", "s", "u", 0.0)


def test_claude_cut_by_max_tokens_is_unavailable(claude):
    claude.create.response = _claude_response([NS(type="text", text='{"a"')], stop_reason="max_tokens")
    with pytest.raises(LLMUnavailable, match="max_tokens"):
        _send_real("judge", "claude-sonnet-5-5", "s", "u", 0.0)


# ---------- OpenAI ----------
def test_openai_sends_system_and_user(openai_like):
    text, i, o = _send_real("keep", "gpt-5-mini", "시스템", "사용자", 0.2)
    assert (text, i, o) == ("답", 9, 4)
    kw = openai_like.create.kwargs
    assert kw["model"] == "gpt-5-mini"
    assert kw["messages"] == [{"role": "system", "content": "시스템"}, {"role": "user", "content": "사용자"}]
    assert openai_like.made == [("test-OPENAI_API_KEY", None)]


def test_gpt5_gets_no_temperature(openai_like):
    _send_real("keep", "gpt-5-mini", "s", "u", 0.2)
    assert "temperature" not in openai_like.create.kwargs


def test_openai_empty_content_is_unavailable(openai_like):
    openai_like.create.response = _openai_response(None)
    with pytest.raises(LLMUnavailable, match="빈 응답"):
        _send_real("keep", "gpt-5-mini", "s", "u", 0.2)


# ---------- Gemini (openai SDK, OpenAI 호환 주소) ----------
def test_gemini_uses_openai_sdk_with_gemini_base_url_and_temperature(openai_like):
    text, _, _ = _send_real("terminate", "gemini-2.5-flash", "s", "u", 0.2)
    assert text == "답"
    assert openai_like.made == [("test-GEMINI_API_KEY", llm.GEMINI_BASE_URL)]
    assert openai_like.create.kwargs["temperature"] == 0.2


# ---------- 키 ----------
@pytest.mark.parametrize("model,key", [
    ("claude-sonnet-5-5", "ANTHROPIC_API_KEY"),
    ("gpt-5-mini", "OPENAI_API_KEY"),
    ("gemini-2.5-flash", "GEMINI_API_KEY"),
])
def test_missing_key_is_unavailable_without_sending(monkeypatch, claude, openai_like, model, key):
    monkeypatch.setenv(key, "")              # .env 를 읽어도 덮어쓰지 않도록 빈 값으로 둔다
    with pytest.raises(LLMUnavailable, match=key):
        _send_real("keep", model, "s", "u", 0.2)
    assert claude.made == [] and openai_like.made == []


def test_sdk_clients_do_not_retry_themselves():
    """재시도는 _request 가 한다. SDK 자체 재시도를 켜 두면 3 × 3번이 된다."""
    assert llm._anthropic_client("k").max_retries == 0
    assert llm._openai_client("k", None).max_retries == 0
    assert str(llm._openai_client("k", llm.GEMINI_BASE_URL).base_url) == llm.GEMINI_BASE_URL


# ---------- 다시 보내도 같은 오류(401·403·404) / 시간 제한 ----------
def test_request_timeout_is_60_seconds_on_both_sdks():
    assert llm.REQUEST_TIMEOUT_SECONDS == 60
    assert llm._anthropic_client("k").timeout == 60
    assert llm._openai_client("k", None).timeout == 60


@pytest.mark.parametrize("status", [401, 403, 404])
def test_claude_auth_and_not_found_are_unavailable(claude, status):
    claude.create.response = _status_error(anthropic, status)
    with pytest.raises(LLMUnavailable, match=str(status)):
        _send_real("judge", "claude-sonnet-5-5", "s", "u", 0.0)


@pytest.mark.parametrize("status", [401, 403, 404])
def test_openai_auth_and_not_found_are_unavailable(openai_like, status):
    openai_like.create.response = _status_error(openai, status)
    with pytest.raises(LLMUnavailable, match=str(status)):
        _send_real("keep", "gpt-5-mini", "s", "u", 0.2)


def test_unavailable_message_has_no_error_body(openai_like):
    """오류 본문에 키 일부가 들어 있을 수 있어(OpenAI 401) 메시지에 옮기지 않는다."""
    openai_like.create.response = _status_error(openai, 401)
    with pytest.raises(LLMUnavailable) as e:
        _send_real("keep", "gpt-5-mini", "s", "u", 0.2)
    assert "오류 본문" not in str(e.value)


@pytest.mark.parametrize("sdk,model,fixture", [
    (anthropic, "claude-sonnet-5-5", "claude"),
    (openai, "gpt-5-mini", "openai_like"),
])
@pytest.mark.parametrize("status", [429, 500])
def test_other_status_errors_pass_through_for_retry(request, sdk, model, fixture, status):
    fake = request.getfixturevalue(fixture)
    fake.create.response = _status_error(sdk, status)
    with pytest.raises(sdk.APIStatusError):
        _send_real("keep", model, "s", "u", 0.2)


@pytest.fixture
def real_env(monkeypatch, tmp_path, keys):
    monkeypatch.setenv("LLM_MOCK", "0")
    monkeypatch.setenv("MODEL_KEEP", "gpt-5-mini")
    monkeypatch.setattr(llm, "LOG_PATH", tmp_path / "llm_calls.jsonl")
    sleeps = []
    monkeypatch.setattr(llm, "_sleep", sleeps.append)
    llm.reset_call_count()
    yield sleeps
    llm.reset_call_count()


def test_401_through_call_llm_is_sent_once_without_wait(real_env, openai_like):
    openai_like.create.response = _status_error(openai, 401)
    with pytest.raises(LLMUnavailable):
        call_llm("keep", "s", "u")
    assert openai_like.create.calls == 1
    assert real_env == []


def test_timeout_through_call_llm_is_retried_like_api_error(real_env, openai_like):
    openai_like.create.response = openai.APITimeoutError(request=_REQ)
    with pytest.raises(LLMUnavailable, match="APITimeoutError"):
        call_llm("keep", "s", "u")
    assert openai_like.create.calls == config.API_RETRIES
    assert real_env == [1, 2]
