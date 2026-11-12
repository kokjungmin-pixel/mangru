"""④ 토론 — run_debate (Backend · 임동욱)
TODO(임동욱): 지금은 계약 샘플을 돌려주는 가짜다. docs/parts/3_Backend 문서 C장 순서로 진짜로 바꾼다.
"""
from src.mock_data import sample
from src.state import AnalysisResult, DebateResult, ManagerData


def run_debate(analysis: AnalysisResult, data: ManagerData, demo_mode: bool = True) -> DebateResult:
    return sample("debate")
