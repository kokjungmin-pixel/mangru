"""⑤ 리포트 초안 — draft_report, apply_verify (PM). LLM 없이 코드로 조립한다 (PM 문서 B4 표)."""
import re
from datetime import date

from src.report.format import fmt_count
from src.state import (AgentState, AnalysisResult, DebateResult, Evidence, ReportDraft,
                       ReportSentence, Signal, VerifyResult)

OPTION_LABELS = {"maintain": "유지", "conditional": "조건부 유지",
                 "review_termination": "해지 검토"}
STATUS_LABELS = {"explained": "설명됨", "unexplained": "미설명"}
JUDGE_PREFIX = "심판: "
NO_DEBATE_TEXT = "토론 개시 기준 미달(경보 0개, 관찰 1개 이하)로 토론을 열지 않음"
NO_CHANGE_TEXT = "특이 변화 없음"
_TAG = re.compile(r"\s*\[([^\[\]]+)\]\s*$")


def _s(section, text, kind, signal_ids, evidence=None) -> ReportSentence:
    return {"section": section, "text": text, "kind": kind,
            "signal_ids": list(signal_ids), "evidence": list(evidence or [])}


def _score(side) -> int:
    return side["numbers"] + side["grounds"] + side["rebuttal"] + side["limits"]


def _arg_evidence(arg, sig: Signal | None) -> list[Evidence]:
    if sig is None:
        return []
    return [sig["evidence"][i] for i in arg["evidence_idx"] if 0 <= i < len(sig["evidence"])]


def _split_tag(ground: str) -> tuple[str, list[str]]:
    """'문장 [signal_id]' → ('문장', ['signal_id'])"""
    m = _TAG.search(ground)
    return (ground[:m.start()].strip(), [m.group(1)]) if m else (ground.strip(), [])


def _recommendation(analysis: AnalysisResult, debate: DebateResult) -> list[ReportSentence]:
    sigs = analysis["signals"]
    text = (f"변화 {fmt_count(len(sigs), '건')} 중 미설명 {fmt_count(debate['unexplained_count'], '건')}"
            f" → {OPTION_LABELS[debate['recommendation']]}")
    return [_s("recommendation", text, "opinion", [s["id"] for s in sigs])]


def _changes(analysis: AnalysisResult) -> list[ReportSentence]:
    if not analysis["signals"]:
        return [_s("changes", NO_CHANGE_TEXT, "opinion", [])]
    out = []
    for sig in analysis["signals"]:
        out.append(_s("changes", sig["summary"], "fact", [sig["id"]], sig["evidence"]))
        if sig["explanation"]:
            out.append(_s("changes", sig["explanation"], "opinion", [sig["id"]]))
    return out


def _debate(analysis: AnalysisResult, debate: DebateResult) -> list[ReportSentence]:
    if not debate["held"]:
        return [_s("debate", NO_DEBATE_TEXT, "opinion", [])]
    by_id = {s["id"]: s for s in analysis["signals"]}
    keep = {a["signal_id"]: a for a in debate["keep_args"]}
    term = {a["signal_id"]: a for a in debate["terminate_args"]}
    verdicts = {v["signal_id"]: v for v in debate["verdicts"]}
    order = [s["id"] for s in analysis["signals"]]
    order += [i for i in [*keep, *term, *verdicts] if i not in order]
    out = []
    for sid in order:
        sig = by_id.get(sid)
        if sid in keep:
            out.append(_s("debate", f"유지 측: {keep[sid]['claim']}", "opinion", [sid],
                          _arg_evidence(keep[sid], sig)))
        if sid in term:
            out.append(_s("debate", f"해지 측: {term[sid]['claim']}", "opinion", [sid],
                          _arg_evidence(term[sid], sig)))
        if sid in verdicts:
            v = verdicts[sid]
            text = (f"{JUDGE_PREFIX}유지 측 {fmt_count(_score(v['keep']), '점')}, "
                    f"해지 측 {fmt_count(_score(v['terminate']), '점')} → "
                    f"{STATUS_LABELS[v['status']]}. {v['reason']}")
            out.append(_s("debate", text, "opinion", [sid]))
    return out


def _options(debate: DebateResult) -> list[ReportSentence]:
    out = []
    for opt in debate["options"]:
        parts, ids = [], []
        for g in opt["grounds"]:
            text, tag = _split_tag(g)
            parts.append(text)
            ids += [t for t in tag if t not in ids]
        label = OPTION_LABELS[opt["name"]] + (" (권고)" if opt["recommended"] else "")
        body = " ".join(parts) if parts else "제시된 근거 없음"
        out.append(_s("options", f"{label}: {body}", "opinion", ids))
    return out


def _questions(debate: DebateResult) -> list[ReportSentence]:
    if not debate["held"]:
        return []
    return [_s("questions", q, "opinion", []) for q in debate["questions"]]


def _dedupe_sources(sentences: list[ReportSentence]) -> list[Evidence]:
    seen, out = set(), []
    for s in sentences:
        for e in s["evidence"]:
            key = (e["source"], e["url"], e["as_of"])
            if key not in seen:
                seen.add(key)
                out.append(e)
    return out


def draft_report(state: AgentState, today: date | None = None) -> ReportDraft:
    analysis, debate = state["analysis"], state["debate"]
    sentences = (_recommendation(analysis, debate) + _changes(analysis)
                 + _debate(analysis, debate) + _options(debate) + _questions(debate))
    return {"manager_id": analysis["manager_id"],
            "period": state["plan"]["period"] if state.get("plan") else "",
            "as_of": (today or date.today()).isoformat(),
            "sentences": sentences,
            "sources": _dedupe_sources(sentences)}


def apply_verify(draft: ReportDraft, verify: VerifyResult,
                 drop_mismatched: bool) -> tuple[ReportDraft, list[str]]:
    """근거 없는 문장은 항상, 불일치 문장은 drop_mismatched=True 일 때 뺀다."""
    idx = set(verify["unsupported_idx"])
    if drop_mismatched:
        idx |= {m["sentence_idx"] for m in verify["mismatches"]}
    removed = [s["text"] for i, s in enumerate(draft["sentences"]) if i in idx]
    kept = [s for i, s in enumerate(draft["sentences"]) if i not in idx]
    return {**draft, "sentences": kept}, removed
