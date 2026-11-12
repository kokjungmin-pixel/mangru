"""⑥ 검증 — verify_report (Data · 김지유, 12/6~13)
TODO(김지유): 지금은 '통과'를 돌려주는 가짜다. 실패 예시는 tests/fixtures/verify.sample.json.
"""
from src.state import AnalysisResult, DebateResult, ManagerData, ReportDraft, VerifyResult


def verify_report(draft: ReportDraft, analysis: AnalysisResult, debate: DebateResult,
                  data: ManagerData) -> VerifyResult:
    return {"passed": True, "failed_step": None, "mismatches": [], "unsupported_idx": [],
            "uncited_signals": []}
