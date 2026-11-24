"""다른 파트에 넘기는 재현 테스트 (Frontend 조재연, 2026-11-22).
Frontend 는 자기 폴더만 고친다(CLAUDE.md 규칙 6). 아래는 지금 실패하는 동작을 xfail(strict)로 고정해 둔 것이다.
담당 파트가 고치면 XPASS 로 실패하므로, 그때 xfail 표시만 지우면 회귀 테스트가 된다. 데모 저장본(data_cache/demo/)을 쓴다."""
import copy
import io

import pdfplumber
import pytest

import src.graph as G
from src.analysis.verify import verify_report
from src.mock_data import sample
from src.report.pdf import render_pdf


def _last(request, demo_mode=True):
    return list(G.stream_run(request, demo_mode))[-1]["state"]


def _pdf_text(state) -> str:
    with pdfplumber.open(io.BytesIO(render_pdf(state))) as doc:
        return "\n".join(p.extract_text() or "" for p in doc.pages)


@pytest.mark.xfail(strict=True, reason="Data analyze()·Backend run_debate() 가 고른 운용사와 관계없이 demo1 샘플을 돌려줌 "
                                       "(src/analysis/__init__.py, src/debate/__init__.py)")
def test_every_step_uses_the_selected_manager():
    st = _last("Brown Capital 반기 점검 준비해줘")
    assert st["data"]["manager_id"] == "demo2"                      # 수집(Frontend)은 맞음
    assert st["analysis"]["manager_id"] == "demo2"
    assert st["debate"]["manager_id"] == "demo2"
    assert st["draft"]["manager_id"] == "demo2"
    brown = ("105633", "885062")
    assert all(any(k in e["url"] for k in brown) for e in st["draft"]["sources"])   # 출처도 Brown 공시
    assert "000000" not in _pdf_text(st)                              # 샘플의 가짜 CRD 주소가 PDF 에 없어야 함


def test_no_signals_means_no_debate_and_consistent_counts(monkeypatch):
    def calm(data, plan):
        return {**sample("analysis"), "manager_id": data["manager_id"], "signals": [], "debate_required": False}
    monkeypatch.setattr(G, "analyze", calm)
    st = _last("Akre 반기 점검 준비해줘")
    d = st["debate"]
    assert d["held"] is False and d["verdicts"] == [] and d["unexplained_count"] == 0
    assert not any("미설명 2건" in x["text"] for x in st["draft"]["sentences"])   # 지금은 '변화 0건 중 미설명 2건'


@pytest.mark.xfail(strict=True, reason="Data verify_report() 가 아직 항상 통과를 돌려줌 (src/analysis/verify.py)")
def test_unsourced_number_fails_verification():
    st = _last("Akre 반기 점검 준비해줘")
    draft = copy.deepcopy(st["draft"])
    draft["sentences"].append({"section": "changes", "text": "운용자산이 $999B 로 늘었다", "kind": "fact",
                               "signal_ids": [], "evidence": []})              # 출처 없는 가상 수치
    v = verify_report(draft, st["analysis"], st["debate"], st["data"])
    assert v["passed"] is False and len(draft["sentences"]) - 1 in v["unsupported_idx"]


@pytest.mark.xfail(strict=True, reason="PM render_pdf() 가 하단 '삭제된 문장'에 지운 문장 원문을 다시 적음 (src/report/pdf.py)")
def test_removed_number_does_not_come_back_in_pdf(monkeypatch):
    real_draft = G.draft_report

    def with_fake_number(s):
        d = real_draft(s)
        d["sentences"].append({"section": "changes", "text": "운용자산이 $999B 로 늘었다", "kind": "fact",
                               "signal_ids": [], "evidence": []})
        return d
    monkeypatch.setattr(G, "draft_report", with_fake_number)
    monkeypatch.setattr(G, "verify_report", lambda d, *a: {"passed": False, "failed_step": None, "mismatches": [],
                                                           "unsupported_idx": [len(d["sentences"]) - 1],
                                                           "uncited_signals": []})   # 검증 실패 주입
    st = _last("Akre 반기 점검 준비해줘")
    assert not any("$999B" in x["text"] for x in st["draft"]["sentences"])        # 본문에서는 지워짐 (지금도 통과)
    assert "$999B" not in _pdf_text(st)                                          # 하단 삭제 내역에 다시 나옴 (실패)
