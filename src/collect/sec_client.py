"""모든 SEC 요청은 sec_get 하나로 (Frontend · 조재연).

- User-Agent: "Mangru-Team <SEC_CONTACT_EMAIL>" (.env). 이메일은 로그에 남기지 않는다.
- 속도: 요청 사이 0.2초 이상(초당 5회. SEC 한도는 초당 10회).
- 실패: 최대 3번 시도(사이에 1초, 2초 대기). 404는 바로 None.
- 원본 저장: data_cache/raw/http/ 에 저장하고, 같은 주소는 다시 요청하지 않고 저장본을 쓴다.
- 예외를 던지지 않는다. 끝내 못 받으면 None.
- 큰 zip(월별 브로셔 묶음 0.4~3GB)은 sec_zip 으로 목차와 필요한 파일만 범위 요청(Range)으로 읽는다.
"""
import hashlib
import io
import json
import logging
import os
import threading
import time
import zipfile
from pathlib import Path
from typing import Literal

import requests
from dotenv import load_dotenv

from src.config import RAW_DIR, ROOT

log = logging.getLogger(__name__)

HTTP_CACHE_DIR: Path = RAW_DIR / "http"
MIN_INTERVAL_SEC = 0.2
MAX_ATTEMPTS = 3
BACKOFF_SEC = (1, 2)            # 1번째 실패 후 1초, 2번째 실패 후 2초
TIMEOUT_SEC = 30
_RETRY_STATUS = {429, 500, 502, 503, 504}

# 테스트에서 바꿔 끼울 수 있게 모듈 속성으로 둔다
_clock = time.monotonic
_sleep = time.sleep
_lock = threading.Lock()
_last_request_at: float | None = None
_session: requests.Session | None = None


def _user_agent() -> str | None:
    load_dotenv(ROOT / ".env", override=False)
    email = os.getenv("SEC_CONTACT_EMAIL", "").strip()
    return f"Mangru-Team {email}" if email else None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
    return _session


def _cache_path(url: str) -> Path:
    return HTTP_CACHE_DIR / (hashlib.sha256(url.encode("utf-8")).hexdigest() + ".bin")


def _throttle() -> None:
    """직전 요청 뒤 MIN_INTERVAL_SEC 가 지날 때까지 기다린다(스레드 사이에서도)."""
    global _last_request_at
    with _lock:
        if _last_request_at is not None:
            wait = MIN_INTERVAL_SEC - (_clock() - _last_request_at)
            if wait > 0:
                _sleep(wait)
        _last_request_at = _clock()


def _decode(body: bytes, kind: str, url: str):
    if kind == "bytes":
        return body
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        log.warning("SEC 응답이 JSON이 아님: %s", url)
        return None


def _fetch(url: str, user_agent: str, byte_range: tuple[int, int] | None = None) -> requests.Response | None:
    headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
    want, extra = 200, {}
    if byte_range is not None:
        # 압축 응답이면 바이트 위치가 어긋나므로 Accept-Encoding 은 뺀다. stream 은 아래 200 처리용
        headers = {"User-Agent": user_agent, "Range": f"bytes={byte_range[0]}-{byte_range[1]}"}
        want, extra = 206, {"stream": True}
    for attempt in range(1, MAX_ATTEMPTS + 1):
        _throttle()
        try:
            resp = _get_session().get(url, headers=headers, timeout=TIMEOUT_SEC, **extra)
            if resp.status_code == want:
                _ = resp.content   # stream 이면 본문을 여기서 받는다 → 도중에 끊겨도 아래 except 로 다시 시도
                return resp
        except requests.RequestException as e:
            reason = f"연결 오류({type(e).__name__})"
        else:
            if byte_range is not None:
                resp.close()   # stream 응답은 닫아야 연결을 놓는다
                if resp.status_code == 200:   # 범위를 무시하고 전체(수 GB)를 보내는 중 → 본문을 읽지 않고 끊는다
                    log.warning("SEC 범위 요청을 지원하지 않음: %s", url)
                    return None
            if resp.status_code == 404:
                log.info("SEC 404: %s", url)
                return None
            if resp.status_code not in _RETRY_STATUS:
                log.warning("SEC HTTP %s (재시도 안 함): %s", resp.status_code, url)
                return None
            reason = f"HTTP {resp.status_code}"
        log.warning("SEC 요청 실패 %d/%d %s: %s", attempt, MAX_ATTEMPTS, reason, url)
        if attempt < MAX_ATTEMPTS:
            _sleep(BACKOFF_SEC[attempt - 1])
    return None


def _save(path: Path, body: bytes, url: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    except OSError as e:
        log.warning("원본 저장 실패(%s): %s", type(e).__name__, url)


def sec_get(url: str, kind: Literal["json", "bytes"] = "json") -> dict | bytes | None:
    """SEC 주소 하나를 받아 JSON(dict) 또는 원본 bytes로 돌려준다. 404·끝내 실패하면 None."""
    path = _cache_path(url)
    if path.exists():
        return _decode(path.read_bytes(), kind, url)

    user_agent = _user_agent()
    if user_agent is None:
        log.warning("SEC_CONTACT_EMAIL 이 .env 에 없어 SEC 요청을 보내지 않음: %s", url)
        return None

    resp = _fetch(url, user_agent)
    if resp is None:
        return None
    _save(path, resp.content, url)
    return _decode(resp.content, kind, url)


def sec_get_range(url: str, start: int, end: int) -> bytes | None:
    """주소의 start~end 바이트(end 포함)만 받는다. 큰 zip 에서 파일 하나만 읽을 때 쓴다.
    저장·재사용은 sec_get 과 같고, 응답에 전체 크기가 오면 함께 저장한다(sec_zip 이 씀)."""
    path = _cache_path(f"{url}#bytes={start}-{end}")
    if path.exists():
        return path.read_bytes()
    user_agent = _user_agent()
    if user_agent is None:
        log.warning("SEC_CONTACT_EMAIL 이 .env 에 없어 SEC 요청을 보내지 않음: %s", url)
        return None
    resp = _fetch(url, user_agent, (start, end))
    if resp is None:
        return None
    _save(path, resp.content, url)
    total = (resp.headers.get("Content-Range") or "").rpartition("/")[2]
    if total.isdigit():
        _save(_cache_path(f"{url}#size"), total.encode(), url)
    return resp.content


class _RemoteFile(io.RawIOBase):
    """zipfile 이 읽는 만큼만 범위 요청으로 받는 읽기 전용 파일."""

    def __init__(self, url: str, size: int):
        self.url, self.size, self.pos = url, size, 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        self.pos = {io.SEEK_SET: 0, io.SEEK_CUR: self.pos, io.SEEK_END: self.size}[whence] + offset
        return self.pos

    def readinto(self, b) -> int:
        if self.pos >= self.size or not len(b):
            return 0
        data = sec_get_range(self.url, self.pos, min(self.pos + len(b), self.size) - 1)
        if data is None:
            raise OSError(f"SEC 범위 요청 실패: {self.url}")
        data = data[:len(b)]   # 서버가 요청보다 길게 주어도 버퍼만큼만
        b[:len(data)] = data
        self.pos += len(data)
        return len(data)


def sec_zip(url: str) -> zipfile.ZipFile | None:
    """큰 zip 을 통째로 받지 않고 목차와 필요한 파일만 범위 요청으로 읽는 ZipFile. 없거나 못 읽으면 None.
    돌려받은 ZipFile 의 read() 도 네트워크를 쓰므로 예외가 날 수 있다(부르는 쪽이 잡는다)."""
    if sec_get_range(url, 0, 0) is None:
        return None
    size_path = _cache_path(f"{url}#size")
    if not size_path.exists():
        log.warning("SEC 응답에 전체 크기(Content-Range)가 없음: %s", url)
        return None
    try:
        raw = _RemoteFile(url, int(size_path.read_text()))
        return zipfile.ZipFile(io.BufferedReader(raw, buffer_size=1 << 20))
    except Exception as e:  # noqa: BLE001 — 외부 파일이라 zipfile 이 여러 종류의 예외를 던진다. 이 함수는 None 으로 끝낸다
        log.warning("zip 을 읽지 못함(%s): %s", type(e).__name__, url)
        return None
