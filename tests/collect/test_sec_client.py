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


# ---- 범위 요청 (큰 zip 에서 파일 하나만 읽기) ----
import io
import zipfile


class RangeResp:
    def __init__(self, status, body=b"", headers=None):
        self.status_code, self.content, self.headers = status, body, headers or {}
        self.closed = False

    def close(self):
        self.closed = True


class RangeServer:
    """Range 머리글대로 잘라 206 으로 주는 가짜 서버. honor=False 면 범위를 무시하고 200 으로 전체를 준다."""
    def __init__(self, files, honor=True):
        self.files, self.honor, self.calls, self.last = files, honor, [], None

    def get(self, url, headers=None, timeout=None, stream=False):
        self.calls.append({"url": url, "headers": headers, "stream": stream})
        body = self.files.get(url)
        if body is None:
            return RangeResp(404)
        if not self.honor or "Range" not in (headers or {}):
            self.last = RangeResp(200, body)
            return self.last
        a, b = map(int, headers["Range"].removeprefix("bytes=").split("-"))
        b = min(b, len(body) - 1)
        return RangeResp(206, body[a:b + 1], {"Content-Range": f"bytes {a}-{b}/{len(body)}"})


def _zip_bytes(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_range_request_sends_header_and_is_cached(env, monkeypatch):
    url = "https://reports.adviserinfo.sec.gov/a.zip"
    s = RangeServer({url: b"0123456789"})
    monkeypatch.setattr(sec_client, "_session", s)
    assert sec_client.sec_get_range(url, 2, 5) == b"2345"
    assert sec_client.sec_get_range(url, 2, 5) == b"2345"
    assert len(s.calls) == 1
    h = s.calls[0]["headers"]
    assert h["Range"] == "bytes=2-5" and h["User-Agent"].startswith("Mangru-Team")
    assert "Accept-Encoding" not in h and s.calls[0]["stream"] is True


def test_range_ignored_by_server_returns_none_without_reading(env, monkeypatch):
    url = "https://reports.adviserinfo.sec.gov/big.zip"
    s = RangeServer({url: b"x" * 100}, honor=False)
    monkeypatch.setattr(sec_client, "_session", s)
    assert sec_client.sec_get_range(url, 0, 9) is None       # 수 GB 를 통째로 받지 않게 끊는다
    assert s.last.closed and len(s.calls) == 1


def test_sec_zip_reads_one_member_with_ranges(env, monkeypatch):
    url = "https://reports.adviserinfo.sec.gov/briefs.zip"
    blob = _zip_bytes({"109242_1_1_20250328.pdf": b"%PDF akre", "other.pdf": b"y" * 5000,
                       "map.csv": b"CRDNumber\n109242\n"})
    s = RangeServer({url: blob})
    monkeypatch.setattr(sec_client, "_session", s)
    z = sec_client.sec_zip(url)
    assert sorted(z.namelist()) == ["109242_1_1_20250328.pdf", "map.csv", "other.pdf"]
    assert z.read("109242_1_1_20250328.pdf") == b"%PDF akre"
    assert all("Range" in c["headers"] for c in s.calls)
    n = len(s.calls)
    z2 = sec_client.sec_zip(url)                                # 두 번째는 저장본만 쓴다
    assert z2.read("109242_1_1_20250328.pdf") == b"%PDF akre" and len(s.calls) == n


def test_sec_zip_missing_returns_none(env, monkeypatch):
    monkeypatch.setattr(sec_client, "_session", RangeServer({}))
    assert sec_client.sec_zip("https://reports.adviserinfo.sec.gov/none.zip") is None
