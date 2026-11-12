"""③ 변화 감지 — analyze (Data · 김지유)
TODO(김지유): 지금은 계약 샘플을 돌려주는 가짜다. docs/parts/4_Data 문서 C장 순서로 진짜로 바꾼다.
"""
from src.mock_data import sample
from src.state import AnalysisResult, ManagerData, Plan


def analyze(data: ManagerData, plan: Plan) -> AnalysisResult:
    return sample("analysis")
