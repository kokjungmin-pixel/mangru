"""validate(obj, 타입): state.py 모양과 다르면 예외. 함수 경계에서 부른다."""
from functools import lru_cache

from pydantic import TypeAdapter


@lru_cache(maxsize=None)
def _adapter(type_):
    return TypeAdapter(type_)


def validate(obj, type_) -> None:
    _adapter(type_).validate_python(obj, strict=False)
