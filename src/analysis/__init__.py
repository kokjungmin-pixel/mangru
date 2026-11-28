"""③ 변화 감지 — analyze (Data · 김지유, Data 문서 B4 "조립").

detect(신호 판정, LLM 없음) → explain(설명, LLM 1회) → stated_strategy(전략, LLM 1회)
→ AnalysisResult → validate. LLM 호출은 최대 2번.

저장본(CONTRACT A9): data_cache/demo/<manager_id>/analysis.json = {"fingerprint": <manager_data sha256>, "result": ...}
- 같은 입력의 저장본이 있으면 그대로 쓴다(데모 모드에서 네트워크·API 키 없이 돈다).
- 실제 LLM 으로 만든 결과(LLM_MOCK=0)만 저장한다. mock 결과로 저장본을 덮지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os

from src.analysis.explain import explain
from src.analysis.signals import detect
from src.analysis.strategy import stated_strategy
from src.config import DEMO_DIR
from src.state import AnalysisResult, ManagerData, Plan
from src.validate import validate

log = logging.getLogger(__name__)


def fingerprint(data: ManagerData) -> str:
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_path(manager_id: str):
    return DEMO_DIR / manager_id / "analysis.json"


def _load_cache(data: ManagerData) -> AnalysisResult | None:
    try:
        saved = json.loads(_cache_path(data["manager_id"]).read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError):
        return None
    if saved.get("fingerprint") != fingerprint(data):
        return None
    result = saved.get("result")
    try:
        validate(result, AnalysisResult)
    except Exception:
        return None
    return result


def _save_cache(data: ManagerData, result: AnalysisResult) -> None:
    try:
        path = _cache_path(data["manager_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"fingerprint": fingerprint(data), "result": result},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as e:
        log.warning("analysis.json 저장 실패: %s", e)


def build(data: ManagerData) -> AnalysisResult:
    """저장본을 보지 않고 새로 계산한다."""
    det = detect(data)
    signals, explain_checks = explain(det.signals, data.get("manager_name", ""))
    strategy, strategy_ev, strategy_unavail = stated_strategy(data)
    result: AnalysisResult = {
        "manager_id": data["manager_id"],
        "signals": signals,
        "debate_required": det.debate_required,
        "stated_strategy": strategy,
        "stated_strategy_evidence": strategy_ev,
        "data_checks": det.data_checks + explain_checks,
        "unavailable": det.unavailable + strategy_unavail,
    }
    validate(result, AnalysisResult)
    return result


def analyze(data: ManagerData, plan: Plan) -> AnalysisResult:
    cached = _load_cache(data)
    if cached is not None:
        return cached
    result = build(data)
    if os.getenv("LLM_MOCK", "1") != "1":
        _save_cache(data, result)
    return result
