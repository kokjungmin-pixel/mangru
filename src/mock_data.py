"""개발 초기에 쓰는 가짜 결과. tests/fixtures/ 의 계약 샘플을 그대로 돌려준다.
각 파트가 진짜 함수를 만들면 자기 파일의 mock 부분을 지우면 된다. (PM)
"""
import copy
import json
from functools import lru_cache

from src.config import FIXTURES_DIR


@lru_cache(maxsize=None)
def _load(name: str) -> dict:
    return json.loads((FIXTURES_DIR / f"{name}.sample.json").read_text(encoding="utf-8"))


def sample(name: str) -> dict:
    """name: manager_data / analysis / debate / draft / verify"""
    return copy.deepcopy(_load(name))
