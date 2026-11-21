"""화면 테스트 (Frontend B5·B7). Streamlit AppTest 로 실제 src/app.py 를 돌린다. 데모 저장본(data_cache/demo/<id>/)을 쓴다."""
import io

import pdfplumber
import pytest
from streamlit.testing.v1 import AppTest

import src.graph as G
from src.config import DEMO_MANAGERS, ROOT
from src.mock_data import sample
from src.ui.result import pdf_file, progress_line, verdict

APP = str(ROOT / "src" / "app.py")
NAMES = {mid: m["name"] for mid, m in DEMO_MANAGERS.items()}


def _run(name):
    at = AppTest.from_file(APP, default_timeout=120).run()
    at.selectbox[0].select(name).run()
    at.button[0].click().run()
    return at


def _pdf_text(pdf: bytes) -> str:
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        return "\n".join(p.extract_text() or "" for p in doc.pages)


@pytest.mark.parametrize("mid", ["demo1", "demo2"])
def test_result_survives_rerun_and_pdf_names_the_same_manager(mid):
    at = _run(NAMES[mid])
    assert not at.exception
    res = at.session_state["result"]
    assert res["state"]["plan"]["manager_id"] == mid and res["state"]["data"]["manager_id"] == mid
    assert at.subheader[0].value == f"결과: {NAMES[mid]}"
    at.run()                                                         # 버튼 없이 다시 그려도 결과가 남는다
    assert at.subheader[0].value == f"결과: {NAMES[mid]}"
    assert len(at.get("download_button")) == 1 and res["pdf_name"] == f"mangru_{mid}_{res['state']['draft']['as_of']}.pdf"
    first_line = _pdf_text(res["pdf"]).splitlines()[0]
    assert NAMES[mid] in first_line                                  # PDF 제목 = 고른 운용사


def test_warburg_early_exit_shows_info_and_no_pdf():
    at = _run(NAMES["demo3"])
    s = at.session_state["result"]["state"]
    assert s["status"] == "early_exit" and s["data"]["manager_id"] == "demo3" and s["data"]["quarters"] == []
    assert any("새 공시" in i.value for i in at.info)
    assert len(at.get("download_button")) == 0
    at.run()
    assert any("새 공시" in i.value for i in at.info)


def test_verify_failure_is_shown_and_marked_on_download(monkeypatch):
    monkeypatch.setattr(G, "verify_report", lambda *a: sample("verify"))   # 검증 실패(숫자 '9점' 불일치)
    at = _run(NAMES["demo1"])
    res = at.session_state["result"]
    assert res["state"]["removed_sentences"] and any("검증 실패" in w.value for w in at.warning)
    assert "검증 실패" in at.get("download_button")[0].proto.label and res["pdf_name"].endswith("_검증실패.pdf")


def test_failed_run_shows_error_and_no_pdf(monkeypatch):
    def boom(*a):
        raise RuntimeError("분석 서버 오류")
    monkeypatch.setattr(G, "analyze", boom)
    at = _run(NAMES["demo2"])
    assert any("분석 서버 오류" in e.value for e in at.error) and len(at.get("download_button")) == 0


# ---------- 화면 값 만들기 (Streamlit 없이) ----------
def _state(**kw):
    s = {"status": "done", "notices": [], "removed_sentences": [], "verify": {"passed": True},
         "plan": {"manager_id": "demo2", "manager_name": "Brown", "has_13f": True}, "draft": None}
    return {**s, **kw}


def test_verdict_and_pdf_file_for_each_status():
    assert verdict(_state(status="failed", notices=["collect 단계 오류: X"]))[0] == "error"
    assert verdict(_state(status="early_exit"))[0] == "info"
    assert verdict(_state(verify={"passed": False}, removed_sentences=["a"]))[0] == "warning"
    pdf, name, why = pdf_file(_state(status="early_exit"))
    assert pdf is None and why and name.startswith("mangru_demo2_")


def test_progress_lines():
    s = _state(plan={"manager_id": "demo3", "manager_name": "Warburg", "has_13f": False})
    assert progress_line("plan", s) == "계획: Warburg, 13F 제외(ADV만)"
    assert progress_line("collect", {**s, "status": "early_exit"}) == "새 공시 없음 → 종료"
    assert progress_line("analyze", {**s, "status": "failed", "notices": ["analyze 단계 오류: boom"]}).startswith("중단")
