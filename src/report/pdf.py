"""PDF — render_pdf (PM). fpdf2 + assets/fonts/NanumGothic, A4 1장 (PM 문서 B4)."""
from datetime import datetime

from fpdf import FPDF

from src.config import ROOT
from src.report.draft import JUDGE_PREFIX
from src.state import AgentState

FONT_DIR = ROOT / "assets" / "fonts"
FONT = "Nanum"
DISCLAIMER = "최종 결정은 담당자가 합니다. 본 리포트의 권고는 공시 변화에 한정됩니다."
SECTIONS = [("recommendation", "권고"), ("changes", "감지된 변화"), ("debate", "토론 요약"),
            ("options", "선택지별 근거"), ("questions", "미팅 질문")]
# 1장을 넘칠 때 줄이는 단계: (설명 문장 빼기, 토론은 심판 문장만)
SHRINK_LEVELS = [(False, False), (True, False), (True, True)]


def _new_pdf() -> FPDF:
    pdf = FPDF(format="A4")
    pdf.set_margins(14, 12, 14)
    pdf.set_auto_page_break(True, margin=12)
    pdf.add_font(FONT, "", str(FONT_DIR / "NanumGothic-Regular.ttf"))
    pdf.add_font(FONT, "B", str(FONT_DIR / "NanumGothic-Bold.ttf"))
    pdf.add_page()
    return pdf


def _line(pdf: FPDF, text: str, size: float = 9, style: str = "", h: float = 4.6, indent: float = 0):
    pdf.set_font(FONT, style, size)
    pdf.set_x(pdf.l_margin + indent)
    pdf.multi_cell(0, h, text, new_x="LMARGIN", new_y="NEXT")


def _heading(pdf: FPDF, text: str):
    pdf.ln(1.5)
    _line(pdf, text, size=11, style="B", h=6)


def _manager_name(state: AgentState) -> str:
    for src in (state.get("plan"), state.get("data")):
        if src and src.get("manager_name"):
            return src["manager_name"]
    return state["draft"]["manager_id"]


def _sentences(state: AgentState, section: str, no_expl: bool, judge_only: bool) -> list[str]:
    out = []
    for s in state["draft"]["sentences"]:
        if s["section"] != section:
            continue
        if no_expl and section == "changes" and s["kind"] == "opinion" and s["signal_ids"]:
            continue
        if judge_only and section == "debate" and s["signal_ids"] and not s["text"].startswith(JUDGE_PREFIX):
            continue
        out.append(s["text"])
    return out


def _build(state: AgentState, no_expl: bool, judge_only: bool, generated_at: str) -> FPDF:
    draft = state["draft"]
    pdf = _new_pdf()
    _line(pdf, f"{_manager_name(state)} 점검 리포트", size=15, style="B", h=8)
    _line(pdf, f"점검 반기 {draft['period']} · 기준일 {draft['as_of']}", size=9)

    for section, title in SECTIONS:
        lines = _sentences(state, section, no_expl, judge_only)
        if not lines:
            continue
        _heading(pdf, title)
        for i, text in enumerate(lines, 1):
            bullet = f"{i}. " if section == "questions" else "· "
            _line(pdf, bullet + text, indent=2,
                  style="B" if section == "recommendation" else "")

    if draft["sources"]:
        _heading(pdf, "출처")
        for e in draft["sources"]:
            _line(pdf, f"· {e['source']} (기준일 {e['as_of']}) {e['url']}", size=7.5, h=3.8, indent=2)

    pdf.ln(2)
    pdf.set_draw_color(160, 160, 160)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(1)
    _line(pdf, DISCLAIMER, size=8.5, style="B", h=4.4)
    omitted = (["변화 설명 문장"] if no_expl else []) + (["토론 논거(심판 문장만 남김)"] if judge_only else [])
    footer = [("확인 불가", state.get("unavailable") or []),
              ("삭제된 문장", state.get("removed_sentences") or []),
              ("알림", state.get("notices") or []),
              ("지면상 생략", omitted)]
    for label, items in footer:
        _line(pdf, f"{label}: {' / '.join(items) if items else '없음'}", size=7.5, h=3.8)
    _line(pdf, f"생성 시각: {generated_at}", size=7.5, h=3.8)
    return pdf


def render_pdf(state: AgentState) -> bytes:
    """state["draft"] 를 A4 1장 PDF로. 넘치면 설명 문장 → 토론 논거 순으로 뺀다."""
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    for no_expl, judge_only in SHRINK_LEVELS:
        pdf = _build(state, no_expl, judge_only, generated_at)
        if pdf.page_no() == 1:
            break
    return bytes(pdf.output())
