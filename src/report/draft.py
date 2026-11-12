"""⑤ 리포트 초안 — draft_report, apply_verify (PM)"""
from src.mock_data import sample
from src.state import AgentState, ReportDraft, VerifyResult


def draft_report(state: AgentState) -> ReportDraft:
    return sample("draft")   # TODO(PM, 11/22~24): 신호·토론으로 코드 조립 (B4 표)


def apply_verify(draft: ReportDraft, verify: VerifyResult,
                 drop_mismatched: bool) -> tuple[ReportDraft, list[str]]:
    """근거 없는 문장은 항상, 불일치 문장은 drop_mismatched=True 일 때 뺀다."""
    idx = set(verify["unsupported_idx"])
    if drop_mismatched:
        idx |= {m["sentence_idx"] for m in verify["mismatches"]}
    removed = [s["text"] for i, s in enumerate(draft["sentences"]) if i in idx]
    kept = [s for i, s in enumerate(draft["sentences"]) if i not in idx]
    return {**draft, "sentences": kept}, removed
