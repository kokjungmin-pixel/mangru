"""근거 검색(RAG): build_index / search_evidence (PM)"""
import builtins

import pytest

import src.rag as R
from src.config import RAG_QUERIES
from src.state import Evidence
from src.validate import validate

ITEM8 = """Item 8 Methods of Analysis, Investment Strategies and Risk of Loss

Our investment strategy focuses on high-quality U.S. companies. Our methods of analysis rely on fundamental research, including meetings with company management and review of financial statements.

We generally hold a concentrated portfolio of 20 to 30 positions and expect low turnover.

Risk of Loss. Investing in securities involves risk of loss that clients should be prepared to bear. Concentration increases the risk that a single holding hurts performance."""

ADV2A = {
    "filed_date": "2026-03-30",
    "url": "https://adviserinfo.sec.gov/firm/summary/000000",
    "items": {
        "2": "Item 2 Material Changes\n\nThere have been no material changes since our last annual update.",
        "8": ITEM8,
        "9": "Item 9 Disciplinary Information\n\nWe have no legal or disciplinary events to report.",
    },
    "pages": {"2": 2, "8": 9, "9": 14},
}


def test_chunks_are_substrings_and_bounded():
    long = ("This sentence is about strategy. " * 60).strip()
    for text in (ITEM8, long):
        for c in R._chunks(text):
            assert c and len(c) <= R.CHUNK_CHARS
            for part in c.split("\n\n"):
                assert part in text


def test_quote_is_original_and_short():
    q = R._quote(ITEM8, RAG_QUERIES["strategy"])
    assert q in ITEM8 and len(q) <= R.QUOTE_MAX
    assert "strategy" in q.lower() or "analysis" in q.lower()


def test_missing_chromadb_returns_empty(monkeypatch):
    real = builtins.__import__
    def no_chroma(name, *a, **kw):
        if name == "chromadb":
            raise ImportError("no chromadb")
        return real(name, *a, **kw)
    monkeypatch.setattr(builtins, "__import__", no_chroma)
    assert R.build_index("demo1", ADV2A) == 0
    assert R.search_evidence("demo1", "strategy") == []


def test_empty_items_returns_zero():
    assert R.build_index("demo1", {**ADV2A, "items": {}}) == 0


try:
    import chromadb  # noqa: F401
    HAS_CHROMA = True
except ImportError:
    HAS_CHROMA = False
needs_chroma = pytest.mark.skipif(not HAS_CHROMA, reason="chromadb 는 dev 전용 (CI 서버엔 없음)")


@pytest.fixture
def tmp_index(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "CHROMA_DIR", tmp_path / "chroma")


@needs_chroma
def test_strategy_query_finds_item8(tmp_index):
    n = R.build_index("demo1", ADV2A)
    assert n >= 3
    evs = R.search_evidence("demo1", RAG_QUERIES["strategy"], k=3)
    assert 1 <= len(evs) <= 3
    top = evs[0]
    validate(top, Evidence)
    assert top["source"] == "Form ADV Part 2A Item 8"
    assert top["page"] == 9 and top["as_of"] == "2026-03-30" and top["url"] == ADV2A["url"]
    assert top["quote"] in ITEM8 and len(top["quote"]) <= R.QUOTE_MAX


@needs_chroma
def test_rebuild_replaces_old_index(tmp_index):
    n1 = R.build_index("demo1", ADV2A)
    n2 = R.build_index("demo1", ADV2A)
    assert n1 == n2
    assert len(R.search_evidence("demo1", "anything", k=50)) == n1


@needs_chroma
def test_managers_are_separate_and_unknown_is_empty(tmp_index):
    R.build_index("demo1", ADV2A)
    assert R.search_evidence("demo2", "strategy") == []
    assert R.search_evidence("없는 운용사", "strategy") == []


@needs_chroma
def test_same_input_same_result(tmp_index):
    R.build_index("demo1", ADV2A)
    a = R.search_evidence("demo1", RAG_QUERIES["strategy"])
    b = R.search_evidence("demo1", RAG_QUERIES["strategy"])
    assert a == b
