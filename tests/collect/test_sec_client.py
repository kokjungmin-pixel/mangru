"""sec_get 테스트 (B7). 네트워크는 쓰지 않는다: 세션·시계·sleep 을 가짜로 바꾼다."""
import json

import pytest
import requests

from src.collect import sec_client


class FakeResp:
    def __init__(self, status: int, body: bytes = b""):
        self.status_code = status
        self.content = body


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "at": sec_client._clock()})
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, sec):
        self.sleeps.append(sec)
        self.now += sec


@pytest.fixture
def env(monkeypatch, tmp_path):
    clock = FakeClock()
    monkeypatch.setattr(sec_client, "HTTP_CACHE_DIR", tmp_path / "http")
    monkeypatch.setattr(sec_client, "_clock", clock.clock)
    monkeypatch.setattr(sec_client, "_sleep", clock.sleep)
    monkeypatch.setattr(sec_client, "_last_request_at", None)
    monkeypatch.setattr(sec_client, "_user_agent", lambda: "Mangru-Team test@example.com")

    def use(responses):
        s = FakeSession(responses)
        monkeypatch.setattr(sec_client, "_session", s)
        return s

    return clock, use


def test_user_agent_header_and_json(env):
    _, use = env
    s = use([FakeResp(200, json.dumps({"cik": "1"}).encode())])
    assert sec_client.sec_get("https://data.sec.gov/a.json") == {"cik": "1"}
    assert s.calls[0]["headers"]["User-Agent"] == "Mangru-Team test@example.com"


def test_requests_are_at_least_0_2s_apart(env):
    _, use = env
    s = use([FakeResp(200, b"{}") for _ in range(3)])
    for i in range(3):
        sec_client.sec_get(f"https://data.sec.gov/{i}.json")
    gaps = [b["at"] - a["at"] for a, b in zip(s.calls, s.calls[1:])]
    assert all(g >= 0.2 - 1e-9 for g in gaps)


def test_404_returns_none_without_retry(env):
    _, use = env
    s = use([FakeResp(404)])
    assert sec_client.sec_get("https://www.sec.gov/missing") is None
    assert len(s.calls) == 1


def test_connection_error_three_attempts_then_none(env):
    clock, use = env
    s = use([requests.ConnectionError("x")] * 3)
    assert sec_client.sec_get("https://www.sec.gov/down") is None
    assert len(s.calls) == 3
    assert 1 in clock.sleeps and 2 in clock.sleeps


def test_retry_then_success(env):
    _, use = env
    s = use([FakeResp(503), FakeResp(200, b"raw")])
    assert sec_client.sec_get("https://www.sec.gov/x.xml", kind="bytes") == b"raw"
    assert len(s.calls) == 2


def test_raw_saved_and_not_requested_again(env):
    _, use = env
    s = use([FakeResp(200, b'{"a": 1}')])
    url = "https://data.sec.gov/cached.json"
    assert sec_client.sec_get(url) == {"a": 1}
    assert sec_client.sec_get(url) == {"a": 1}
    assert len(s.calls) == 1
    assert sec_client._cache_path(url).exists()


def test_no_contact_email_returns_none(env, monkeypatch):
    _, use = env
    s = use([])
    monkeypatch.setattr(sec_client, "_user_agent", lambda: None)
    assert sec_client.sec_get("https://data.sec.gov/b.json") is None
    assert s.calls == []
