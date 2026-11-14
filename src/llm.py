"""모든 LLM 호출은 call_llm 하나로 (Backend · 임동욱). 규칙은 docs/parts/3_Backend 문서 B2.

- role(keep / terminate / judge / analyst) → .env 의 MODEL_<ROLE> 로 보낸다.
- JSON은 한 방법으로만 받는다: 응답에서 첫 '{'~마지막 '}'를 읽고 json_keys 가 모두 있는지 검사.
  틀리면 오류 내용을 붙여 1회 재요청, 또 틀리면 LLMUnavailable.
- API 오류는 최대 config.API_RETRIES 회 시도(사이 대기 1초, 2초, ...). 끝내 실패하면 LLMUnavailable.
- 실행 한 번(reset_call_count 이후)의 호출 수가 config.MAX_LLM_CALLS_PER_RUN 을 넘으면 LLMUnavailable.
  호출 수 = call_llm 을 부른 횟수 + 형식 오류 재요청 횟수. API 오류 재시도는 세지 않는다
  (상한 32가 정상 10번 × 3 + 여유 2로 잡혀 있어, 재시도까지 세면 정상 실행이 멈출 수 있다).
- 재시도를 포함해 실제 요청마다 logs/llm_calls.jsonl 에 한 줄(시각·role·모델·토큰 수·걸린 시간·성공 여부). 프롬프트·응답 본문은 남기지 않는다.
- LLM_MOCK=1(기본값)이면 tests/debate/fixtures/<role>_<첫 키>.txt 의 고정 응답을 쓴다. 기록은 남기지 않는다.
"""
import json
import os
import time
from datetime import datetime, timezone

from src import config

ROLES = ("keep", "terminate", "judge", "analyst")
LOG_PATH = config.ROOT / "logs" / "llm_calls.jsonl"
MOCK_DIR = config.ROOT / "tests" / "debate" / "fixtures"

_calls = 0
_sleep = time.sleep          # 테스트에서 바꿔 끼운다


class LLMUnavailable(Exception):
    """LLM 결과를 얻지 못함. 부르는 쪽은 '확인 불가'로 처리한다."""


# ---------- 호출 수 ----------
def reset_call_count() -> None:
    global _calls
    _calls = 0


def call_count() -> int:
    return _calls


def _take_call() -> None:
    global _calls
    if _calls >= config.MAX_LLM_CALLS_PER_RUN:
        raise LLMUnavailable(f"LLM 호출 상한 초과: 실행 1회 {config.MAX_LLM_CALLS_PER_RUN}번")
    _calls += 1


# ---------- JSON ----------
def extract_json(text: str) -> dict:
    """응답 앞뒤에 설명 문장이나 코드 블록 표시가 붙어도 첫 '{'부터 마지막 '}'까지 읽는다."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("JSON 없음")
    return json.loads(text[start:end + 1])


def _parse(text: str, json_keys: list[str]) -> dict:
    obj = extract_json(text)
    if not isinstance(obj, dict):
        raise ValueError("JSON 객체가 아님")
    missing = [k for k in json_keys if k not in obj]
    if missing:
        raise ValueError(f"빠진 키 {missing}, 받은 키 {sorted(obj)}")
    return obj


def _fix_request(user: str, error: str, json_keys: list[str]) -> str:
    return (f"{user}\n\n[이전 응답 형식 오류] {error}\n"
            f"아래 키를 모두 가진 JSON 객체만 다시 출력하십시오: {json_keys}")


# ---------- 보내기 ----------
def _mock_on() -> bool:
    return os.getenv("LLM_MOCK", "1") == "1"


def _model_for(role: str) -> str:
    name = f"MODEL_{role.upper()}"
    model = os.getenv(name, "").strip()
    if not model:
        raise LLMUnavailable(f"{name} 가 .env 에 없음")
    return model


def _mock_text(role: str, json_keys: list[str] | None) -> str:
    path = MOCK_DIR / f"{role}_{json_keys[0] if json_keys else 'text'}.txt"
    if not path.exists():
        raise LLMUnavailable(f"LLM_MOCK 응답 파일 없음: {path.name}")
    return path.read_text(encoding="utf-8")


def _send_real(role: str, model: str, system: str, user: str, temperature: float) -> tuple[str, int, int]:
    """실제 API 호출 → (응답 텍스트, 입력 토큰, 출력 토큰). 회사별 SDK 차이는 여기서만 처리한다.
    TODO(임동욱): API 키를 받은 뒤 구현. 모델이 temperature 를 받지 않으면 보내지 않는다.
    """
    raise LLMUnavailable("실제 LLM 호출은 아직 구현되지 않음 (LLM_MOCK=1 로 실행)")


def _log(role: str, model: str, started: float, ok: bool, in_tok: int | None, out_tok: int | None) -> None:
    row = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "role": role, "model": model,
        "input_tokens": in_tok, "output_tokens": out_tok,
        "seconds": round(time.monotonic() - started, 3), "ok": ok,
    }
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _request(role: str, model: str | None, system: str, user: str,
             temperature: float, json_keys: list[str] | None) -> str:
    """요청 1건 = 호출 수 1. API 오류 재시도는 호출 수에 넣지 않고 기록 파일에만 남긴다."""
    _take_call()
    if model is None:
        return _mock_text(role, json_keys)
    for attempt in range(config.API_RETRIES):
        started = time.monotonic()
        try:
            text, in_tok, out_tok = _send_real(role, model, system, user, temperature)
        except LLMUnavailable:
            _log(role, model, started, False, None, None)
            raise
        except Exception as e:  # SDK마다 오류 종류가 달라 여기서 모두 받아 재시도한다
            _log(role, model, started, False, None, None)
            if attempt == config.API_RETRIES - 1:
                raise LLMUnavailable(f"API 오류 {config.API_RETRIES}회: {type(e).__name__}") from e
            _sleep(2 ** attempt)
            continue
        _log(role, model, started, True, in_tok, out_tok)
        return text
    raise LLMUnavailable("API 재시도 횟수가 0")   # config.API_RETRIES 가 0일 때만


# ---------- 공개 함수 ----------
def call_llm(role: str, system: str, user: str,
             json_keys: list[str] | None = None, temperature: float | None = None) -> dict | str:
    if role not in ROLES:
        raise ValueError(f"모르는 role: {role}")
    model = None if _mock_on() else _model_for(role)
    temp = config.TEMPERATURE[role] if temperature is None else temperature

    text = _request(role, model, system, user, temp, json_keys)
    if json_keys is None:
        return text
    try:
        return _parse(text, json_keys)
    except ValueError as e:
        error = str(e)

    text = _request(role, model, system, _fix_request(user, error, json_keys), temp, json_keys)
    try:
        return _parse(text, json_keys)
    except ValueError as e:
        raise LLMUnavailable(f"JSON 형식 오류 2회: {e}") from e
