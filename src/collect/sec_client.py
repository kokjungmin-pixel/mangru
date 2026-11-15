"""모든 SEC 요청은 sec_get 하나로 (Frontend · 조재연).

- User-Agent: "Mangru-Team <SEC_CONTACT_EMAIL>" (.env). 이메일은 로그에 남기지 않는다.
- 속도: 요청 사이 0.2초 이상(초당 5회. SEC 한도는 초당 10회).
- 실패: 최대 3번 시도(사이에 1초, 2초 대기). 404는 바로 None.
- 원본 저장: data_cache/raw/http/ 에 저장하고, 같은 주소는 다시 요청하지 않고 저장본을 쓴다.
- 예외를 던지지 않는다. 끝내 못 받으면 None.
"""
import hashlib
import json
import logging
import os
import threading
import time
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


def _fetch(url: str, user_agent: str) -> bytes | None:
    headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
    for attempt in range(1, MAX_ATTEMPTS + 1):
        _throttle()
        try:
            resp = _get_session().get(url, headers=headers, timeout=TIMEOUT_SEC)
        except requests.RequestException as e:
            reason = f"연결 오류({type(e).__name__})"
        else:
            if resp.status_code == 200:
                return resp.content
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


def sec_get(url: str, kind: Literal["json", "bytes"] = "json") -> dict | bytes | None:
    """SEC 주소 하나를 받아 JSON(dict) 또는 원본 bytes로 돌려준다. 404·끝내 실패하면 None."""
    path = _cache_path(url)
    if path.exists():
        return _decode(path.read_bytes(), kind, url)

    user_agent = _user_agent()
    if user_agent is None:
        log.warning("SEC_CONTACT_EMAIL 이 .env 에 없어 SEC 요청을 보내지 않음: %s", url)
        return None

    body = _fetch(url, user_agent)
    if body is None:
        return None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    except OSError as e:
        log.warning("원본 저장 실패(%s): %s", type(e).__name__, url)
    return _decode(body, kind, url)
