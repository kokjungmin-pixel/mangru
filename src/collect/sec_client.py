"""모든 SEC 요청은 sec_get 하나로 (Frontend · 조재연, 11/16까지).
TODO(조재연): User-Agent(SEC_CONTACT_EMAIL), 요청 간격 0.2초, 3회 시도, 원본 저장. 404·실패는 None.
"""
from typing import Literal


def sec_get(url: str, kind: Literal["json", "bytes"] = "json") -> dict | bytes | None:
    raise NotImplementedError("조재연이 11/16까지 구현")
