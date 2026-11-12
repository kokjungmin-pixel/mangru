"""Streamlit 화면 (Frontend · 조재연). 실행: streamlit run src/app.py
TODO(조재연): 지금은 흐름이 도는지만 보여 주는 임시 화면. 11/22~23 '화면 틀'에서 다시 만든다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # streamlit 실행 시 src 찾기

import streamlit as st

from src.config import DEMO_MANAGERS
from src.graph import stream_run

st.set_page_config(page_title="망루", page_icon="🗼")
st.title("망루 — 위탁운용사 점검 AI")
name = st.selectbox("운용사", [m["name"] for m in DEMO_MANAGERS.values()])
if st.button("점검 시작"):
    last = None
    for ev in stream_run(f"{name} 점검해줘", demo_mode=True):
        st.write(f"✅ {ev['step']}")
        last = ev["state"]
    st.subheader(f"결과: {last['status']}")
    for s in (last.get("draft") or {}).get("sentences", []):
        st.write(f"- [{s['section']}] {s['text']}")
