"""모든 LLM 호출은 call_llm 하나로 (Backend · 임동욱).
TODO(임동욱): role → .env 의 MODEL_* 로 보내고, 호출 수 상한(MAX_LLM_CALLS_PER_RUN)을 센다.
"""
import os

_calls = 0


def reset_call_count() -> None:
    global _calls
    _calls = 0


def call_llm(role, system, user, json_keys=None, temperature=None):
    if os.getenv("LLM_MOCK", "1") == "1":
        raise RuntimeError("LLM_MOCK=1 상태: 실제 호출 대신 각 파트의 mock을 쓴다")
    raise NotImplementedError("임동욱이 구현")
