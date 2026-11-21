"""Streamlit 화면 (Frontend · 조재연). 실행: streamlit run src/app.py
지금 있는 것: 운용사 선택 → 실행 → 진행 상황 → 결과(권고·알림·리포트 문장·출처·운용사 정보) → PDF 다운로드.
실행 결과는 st.session_state 에 두어 화면을 다시 그려도 그래프를 또 돌리지 않고 결과가 남는다 (B5 "지킬 것").
TODO(조재연): B5 세 칸 구성(신호 카드·토론·선택지)과 실제 모드 스위치.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # streamlit 실행 시 src 찾기

import streamlit as st

from src.config import DEMO_MANAGERS
from src.report.draft import OPTION_LABELS
from src.ui.result import manager_facts, run_check, verdict

SECTION_TITLES = {"recommendation": "권고", "changes": "감지된 변화", "debate": "토론 요약",
                  "options": "선택지별 근거", "questions": "미팅 질문"}

st.set_page_config(page_title="망루", page_icon="🗼")
st.title("망루 — 위탁운용사 점검 AI")
st.caption("데모 모드: 미리 받아 둔 SEC 공시 저장본으로 실행합니다.")
name = st.selectbox("운용사", [m["name"] for m in DEMO_MANAGERS.values()])
if st.button("점검 시작"):
    with st.spinner("점검 중…"):
        st.session_state["result"] = run_check(name)

res = st.session_state.get("result")
if res:
    s = res["state"]
    st.subheader(f"결과: {res['manager_name']}")
    for line in res["lines"]:
        st.write(f"✅ {line}")
    kind, message = verdict(s)
    getattr(st, kind)(message)
    if s.get("debate"):
        st.markdown(f"**권고: {OPTION_LABELS[s['debate']['recommendation']]}** (최종 결정은 담당자)")
    for label, items in (("알림", s["notices"]), ("확인 불가", s["unavailable"]),
                         ("검증에서 삭제된 문장", s["removed_sentences"])):
        if items:
            with st.expander(f"{label} {len(items)}건"):
                for it in items:
                    st.write(f"- {it}")
    for section, title in SECTION_TITLES.items():
        rows = [x for x in (s.get("draft") or {}).get("sentences", []) if x["section"] == section]
        if rows:
            st.markdown(f"#### {title}")
            for x in rows:
                st.write(f"- {x['text']}" + (" (의견)" if x["kind"] == "opinion" else ""))
    if (s.get("draft") or {}).get("sources"):
        with st.expander("출처"):
            for e in s["draft"]["sources"]:
                st.write(f"- {e['source']} (기준일 {e['as_of']}) {e['url']}")
    if s.get("data"):
        st.caption(" · ".join(manager_facts(s)))
    if res["pdf"]:
        label = "PDF 다운로드" + (" (검증 실패 문장 삭제됨)" if kind == "warning" else "")
        st.download_button(label, data=res["pdf"], file_name=res["pdf_name"], mime="application/pdf")
    else:
        st.caption(res["pdf_error"])
