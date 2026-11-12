"""근거 검색(RAG) — build_index, search_evidence (PM, 12/1~5)
chromadb 는 함수 안에서만 불러온다(배포 서버엔 설치하지 않음). 없으면 0 / 빈 목록.
"""
from src.state import AdvPart2A, Evidence


def build_index(manager_id: str, adv2a: AdvPart2A) -> int:
    return 0   # TODO(PM): Chroma 색인


def search_evidence(manager_id: str, query: str, k: int = 3) -> list[Evidence]:
    return []  # TODO(PM): 색인에서 관련 문단 찾기
