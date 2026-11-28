"""신호 설명 (Data · 김지유, Data 문서 B4 "설명"). 데이터 분석 에이전트의 LLM 부분.

신호 전체를 call_llm(role="analyst") 한 번으로 보내 신호별 1~2문장 한국어 설명을 받는다.
- LLM 에게는 summary(코드가 format.py 로 만든 표기)만 준다.
- 응답 설명에 주어지지 않은 숫자가 있으면(unknown_numbers) 그 설명은 버리고 explanation = summary.
- LLM 이 실패해도 멈추지 않는다(전부 explanation = summary).
"""
from __future__ import annotations

import json
import logging

from src.config import ROOT
from src.llm import call_llm
from src.report.format import unknown_numbers
from src.state import Signal

log = logging.getLogger(__name__)
PROMPT_DIR = ROOT / "prompts" / "analysis"
MAX_TEXT_LEN = 400


def explain(signals: list[Signal], manager_name: str) -> tuple[list[Signal], list[str]]:
    """설명을 채운 신호 목록과 data_checks 문장 목록. 입력 목록은 바꾸지 않는다."""
    out = [dict(s, explanation=s["summary"]) for s in signals]
    if not out:
        return out, []
    try:
        resp = call_llm("analyst", _prompt("explain_system.md"),
                        _prompt("explain_user.md").format(manager_name=manager_name, signals=_signal_lines(out)),
                        json_keys=["explanations"])
    except Exception as e:                    # LLMUnavailable 포함: 분석은 멈추지 않는다
        log.warning("신호 설명 LLM 실패: %s", e)
        return out, ["신호 설명: LLM을 쓰지 못해 사실 문장(summary)으로 대체"]

    texts = {}
    for row in (resp or {}).get("explanations") or []:
        if isinstance(row, dict) and isinstance(row.get("signal_id"), str) and isinstance(row.get("text"), str):
            texts[row["signal_id"]] = row["text"].strip()

    dropped = []
    for s in out:
        t = texts.get(s["id"])
        if not t or len(t) > MAX_TEXT_LEN:
            dropped.append(s["id"])
            continue
        if unknown_numbers(t, out):           # 신호 전체 기준 (CONTRACT A7 숫자 검사)
            dropped.append(s["id"])
            continue
        s["explanation"] = t
    checks = []
    if dropped:
        checks.append(f"신호 설명: {len(dropped)}개는 없는 숫자·형식 문제로 버리고 사실 문장으로 대체 ({', '.join(dropped)})")
    return out, checks


def _signal_lines(signals: list[Signal]) -> str:
    rows = [{"signal_id": s["id"], "level": "경보" if s["level"] == "alert" else "관찰",
             "metric": s["metric"], "summary": s["summary"]} for s in signals]
    return json.dumps(rows, ensure_ascii=False, indent=1)


def _prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")
