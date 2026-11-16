"""근거 검색(RAG) — build_index, search_evidence (PM)
chromadb 는 함수 안에서만 불러온다(배포 서버엔 설치하지 않음). 없거나 오류가 나면 0 / 빈 목록.

- 색인 단위: ADV 2A Item 본문을 문단으로 나누고, 짧은 문단은 이어 붙여 약 CHUNK_CHARS 자 덩어리로 만든다.
- 임베딩: 단어 해싱 벡터(외부 모델 다운로드 없음, 같은 입력 → 같은 결과). 질의가 Item 8 제목과
  같은 단어를 쓰므로 단어 일치로 충분하다. 품질이 모자라면 임베딩 함수만 바꾸면 된다.
- 운용사마다 컬렉션 하나. build_index 는 기존 색인을 지우고 최신 2A로 새로 만든다.
- 인용(quote)은 원문을 그대로 자른 200자 이내 문자열이라 검증 에이전트가 원문과 대조할 수 있다.
"""
import hashlib
import math
import re

from src.config import CHROMA_DIR
from src.state import AdvPart2A, Evidence

CHUNK_CHARS = 800
QUOTE_MAX = 200
DIM = 1024
_STOP = {"a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have", "in", "is",
         "it", "its", "of", "on", "or", "our", "that", "the", "their", "this", "to", "we", "which",
         "with", "you", "your", "may", "will", "not", "these", "those", "such"}


# ---------- 문단 나누기 ----------
def _chunks(text: str) -> list[str]:
    """빈 줄 기준 문단 → 짧은 것끼리 이어 붙임. 긴 문단은 문장 경계에서 자른다. 각 덩어리는 원문의 부분 문자열."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    pieces: list[str] = []
    for p in paras:
        while len(p) > CHUNK_CHARS:
            cut = max(p.rfind(". ", 0, CHUNK_CHARS), p.rfind("\n", 0, CHUNK_CHARS))
            cut = cut + 1 if cut > CHUNK_CHARS // 2 else CHUNK_CHARS
            pieces.append(p[:cut].strip())
            p = p[cut:].strip()
        if p:
            pieces.append(p)
    out: list[str] = []
    for p in pieces:          # 짧은 문단(제목 등)은 다음 문단과 묶되, 원문 순서를 지킨다
        if out and len(out[-1]) < CHUNK_CHARS // 4 and len(out[-1]) + len(p) + 2 <= CHUNK_CHARS:
            out[-1] = out[-1] + "\n\n" + p
        else:
            out.append(p)
    return out


# ---------- 임베딩 ----------
def _tokens(text: str) -> list[str]:
    words = [w for w in re.findall(r"[a-z]+", text.lower()) if w not in _STOP and len(w) > 1]
    stem = [w[:-3] + "y" if w.endswith("ies") else w[:-1] if w.endswith("s") and len(w) > 3 else w
            for w in words]
    return stem + [f"{a}_{b}" for a, b in zip(stem, stem[1:])]


def _embed(text: str) -> list[float]:
    v = [0.0] * DIM
    for t in _tokens(text):
        h = int.from_bytes(hashlib.md5(t.encode()).digest()[:4], "little")
        v[h % DIM] += 1.0
    v = [math.log1p(x) for x in v]
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


# ---------- 인용 고르기 ----------
def _quote(chunk: str, query: str) -> str:
    """덩어리 안에서 질의 단어가 가장 많이 겹치는 문장을 원문 그대로 200자 이내로."""
    q = set(_tokens(query))
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", chunk) if s.strip()]
    best = max(sents, key=lambda s: len(q & set(_tokens(s))), default=chunk.strip())
    if len(best) <= QUOTE_MAX:
        return best
    cut = best.rfind(" ", 0, QUOTE_MAX)
    return best[:cut if cut > 0 else QUOTE_MAX].rstrip()


# ---------- 공개 함수 ----------
def _collection(manager_id: str, reset: bool = False):
    import chromadb   # 배포 서버엔 없음 → 호출한 쪽에서 예외 처리
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    name = "adv2a_" + hashlib.md5(manager_id.encode()).hexdigest()[:12]   # 컬렉션 이름 규칙(영숫자 시작·끝) 지키기
    if reset:
        try:
            client.delete_collection(name)
        except Exception:
            pass
        return client.create_collection(name, metadata={"hnsw:space": "cosine"})
    return client.get_collection(name)


def build_index(manager_id: str, adv2a: AdvPart2A) -> int:
    """ADV 2A 문단을 색인에 넣고 넣은 개수를 돌려준다. chromadb 가 없거나 실패하면 0."""
    try:
        ids, docs, metas = [], [], []
        for item, text in (adv2a.get("items") or {}).items():
            for i, c in enumerate(_chunks(text or "")):
                ids.append(f"{item}-{i}")
                docs.append(c)
                metas.append({"item": str(item), "page": int(adv2a.get("pages", {}).get(item, -1)),
                              "filed_date": adv2a.get("filed_date", ""), "url": adv2a.get("url", "")})
        if not docs:
            return 0
        col = _collection(manager_id, reset=True)
        col.add(ids=ids, documents=docs, metadatas=metas, embeddings=[_embed(d) for d in docs])
        return len(docs)
    except Exception:
        return 0


def search_evidence(manager_id: str, query: str, k: int = 3) -> list[Evidence]:
    """ADV 2A에서 질의와 가까운 문단 k개를 Evidence 로. 색인이 없거나 chromadb 가 없으면 빈 목록."""
    try:
        col = _collection(manager_id)
        n = min(k, col.count())
        if n <= 0:
            return []
        r = col.query(query_embeddings=[_embed(query)], n_results=n,
                      include=["documents", "metadatas"])
        out: list[Evidence] = []
        for doc, m in zip(r["documents"][0], r["metadatas"][0]):
            out.append({"source": f"Form ADV Part 2A Item {m['item']}", "url": m["url"],
                        "as_of": m["filed_date"], "page": m["page"] if m["page"] >= 0 else None,
                        "quote": _quote(doc, query)})
        return out
    except Exception:
        return []
