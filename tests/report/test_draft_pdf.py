"""리포트 초안·PDF (PM 문서 B4)"""
import re
from datetime import date

from src.mock_data import sample
from src.report.draft import NO_CHANGE_TEXT, NO_DEBATE_TEXT, apply_verify, draft_report
from src.report.format import unknown_numbers
from src.report.pdf import render_pdf
from src.state import ReportDraft
from src.validate import validate

TODAY = date(2026, 11, 20)


def state(**over):
    s = {"request": "Example Capital 점검해줘", "demo_mode": True,
         "plan": {"manager_id": "demo1", "manager_name": "Example Capital Management LLC",
                  "has_13f": True, "checks": [], "period": "2026H2"},
         "data": sample("manager_data"), "analysis": sample("analysis"), "debate": sample("debate"),
         "draft": None, "verify": None, "retries": 0, "next_step": None,
         "removed_sentences": [], "notices": [], "unavailable": [], "status": "running"}
    s.update(over)
    return s


def by_section(d, sec):
    return [x for x in d["sentences"] if x["section"] == sec]


def test_draft_matches_contract_and_sample():
    d = draft_report(state(), TODAY)
    validate(d, ReportDraft)
    assert d["period"] == "2026H2" and d["as_of"] == "2026-11-20"
    assert by_section(d, "recommendation")[0]["text"] == "변화 2건 중 미설명 2건 → 조건부 유지"
    assert "심판: 유지 측 5점, 해지 측 8점 → 미설명. 후임의 운용 이력 근거가 부족함" in \
        [x["text"] for x in by_section(d, "debate")]
    assert len(by_section(d, "options")) == 3 and len(by_section(d, "questions")) == 3
    assert by_section(d, "options")[1]["text"].startswith("조건부 유지 (권고): ")


def test_fact_sentences_have_evidence_and_sources_deduped():
    d = draft_report(state(), TODAY)
    facts = [x for x in d["sentences"] if x["kind"] == "fact"]
    assert facts and all(x["evidence"] for x in facts)
    keys = [(e["source"], e["url"], e["as_of"]) for e in d["sources"]]
    assert len(keys) == len(set(keys))


def test_no_numbers_outside_signals():
    st = state()
    d = draft_report(st, TODAY)
    for x in d["sentences"]:
        if x["section"] in ("changes", "options"):
            assert unknown_numbers(x["text"], st["analysis"]["signals"]) == [], x["text"]


def test_no_debate_and_no_signals():
    a = sample("analysis"); a["signals"] = []; a["debate_required"] = False
    deb = sample("debate"); deb["held"] = False; deb["questions"] = []; deb["unexplained_count"] = 0
    d = draft_report(state(analysis=a, debate=deb), TODAY)
    assert [x["text"] for x in by_section(d, "changes")] == [NO_CHANGE_TEXT]
    assert [x["text"] for x in by_section(d, "debate")] == [NO_DEBATE_TEXT]
    assert by_section(d, "questions") == []
    validate(d, ReportDraft)


def test_apply_verify_returns_removed_texts():
    d = draft_report(state(), TODAY)
    v = {"passed": False, "failed_step": "debate", "unsupported_idx": [1],
         "mismatches": [{"sentence_idx": 2, "token": "x", "reason": "r"}], "uncited_signals": []}
    kept, removed = apply_verify(d, v, drop_mismatched=False)
    assert removed == [d["sentences"][1]["text"]] and len(kept["sentences"]) == len(d["sentences"]) - 1
    kept, removed = apply_verify(d, v, drop_mismatched=True)
    assert len(removed) == 2


def pages(pdf: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page(?!s)", pdf))


def test_pdf_one_page():
    st = state(notices=["데모 모드라 재수행 없음: 문장 1개 삭제"], unavailable=["업종 지표"])
    st["draft"] = draft_report(st, TODAY)
    pdf = render_pdf(st)
    assert pdf.startswith(b"%PDF") and len(pdf) > 1000 and pages(pdf) == 1


def test_pdf_shrinks_to_one_page_when_long():
    st = state()
    st["draft"] = draft_report(st, TODAY)
    long = st["draft"]["sentences"][1]
    st["draft"]["sentences"] += [{**long, "kind": "opinion", "text": "긴 설명 문장 " * 30}] * 12
    assert pages(render_pdf(st)) == 1
