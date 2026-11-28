"""운용사가 밝힌 전략 (Data · 김지유, Data 문서 B4 "운용사가 밝힌 전략").

1. 후보 문단: search_evidence(manager_id, 질의). 비어 있으면 adv2a_new.items["8"] 앞 6,000자.
2. call_llm(role="analyst") 1회: 후보에서 전략 문장을 원문 그대로 3개 이내로 고르고 한국어 한 줄 요약.
3. 고른 인용이 adv2a_new 본문에 실제로 있는지 코드로 확인(연속 공백만 하나로 정리해 비교). 없는 인용은 버린다.
4. 남은 인용이 없거나 Part 2A 가 없으면 stated_strategy=None, unavailable 에 "운용사가 밝힌 전략: 확인 불가".
"""
from __future__ import annotations

import logging
import re

from src.config import RAG_QUERIES, ROOT
from src.llm import call_llm
from src.state import Evidence, ManagerData

log = logging.getLogger(__name__)
PROMPT_DIR = ROOT / "prompts" / "analysis"
FALLBACK_CHARS = 6000
MAX_QUOTES = 3
QUOTE_MAX_LEN = 200                     # Evidence.quote 길이 상한
UNAVAILABLE = "운용사가 밝힌 전략: 확인 불가"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _search(manager_id: str) -> list[Evidence]:
    try:
        from src.rag import search_evidence
        return search_evidence(manager_id, RAG_QUERIES["strategy"]) or []
    except Exception:
        return []


def stated_strategy(data: ManagerData) -> tuple[str | None, list[Evidence], list[str]]:
    """(한 줄 요약 또는 None, 인용 근거 목록, unavailable 문장 목록)."""
    adv = data.get("adv2a_new")
    if not adv or not (adv.get("items") or {}):
        return None, [], [UNAVAILABLE]

    hits = _search(data["manager_id"])
    if hits:
        candidates = "\n\n".join(f"[{h.get('source')}] {h.get('quote') or ''}" for h in hits)
    else:
        candidates = (adv["items"].get("8") or "")[:FALLBACK_CHARS]
    if not candidates.strip():
        return None, [], [UNAVAILABLE]

    try:
        resp = call_llm("analyst", (PROMPT_DIR / "strategy_system.md").read_text(encoding="utf-8"),
                        (PROMPT_DIR / "strategy_user.md").read_text(encoding="utf-8").format(
                            manager_name=data.get("manager_name", ""), candidates=candidates),
                        json_keys=["quotes", "summary"])
    except Exception as e:
        log.warning("전략 LLM 실패: %s", e)
        return None, [], [UNAVAILABLE]

    quotes = (resp or {}).get("quotes") or []
    summary = (resp or {}).get("summary")
    evidence = _verified_quotes(quotes, adv)
    if not evidence or not isinstance(summary, str) or not summary.strip():
        return None, [], [UNAVAILABLE]
    return summary.strip(), evidence, []


def _verified_quotes(quotes, adv: dict) -> list[Evidence]:
    """본문에 실제로 있는 인용만 Evidence 로. 어느 Item 에 있는지 찾아 그 페이지를 붙인다."""
    items = {k: _norm(v) for k, v in (adv.get("items") or {}).items()}
    out: list[Evidence] = []
    for q in quotes if isinstance(quotes, list) else []:
        if not isinstance(q, str):
            continue
        nq = _norm(q)
        if len(nq) < 20:                        # 너무 짧은 조각은 인용으로 쓰지 않는다
            continue
        item = next((k for k, body in items.items() if nq in body), None)
        if item is None:
            continue
        out.append({"source": f"Form ADV Part 2A Item {item}", "url": adv.get("url") or "",
                    "as_of": adv.get("filed_date") or "", "page": (adv.get("pages") or {}).get(item),
                    "quote": nq[:QUOTE_MAX_LEN]})
        if len(out) >= MAX_QUOTES:
            break
    return out
