"""② 수집 — collect (Frontend · 조재연)
TODO(조재연): 지금은 계약 샘플을 돌려주는 가짜다. docs/parts/2_Frontend 문서 C장 순서로 진짜로 바꾼다.
"""
from src.mock_data import sample
from src.state import ManagerData, Plan


def collect(plan: Plan, demo_mode: bool = True) -> ManagerData:
    return sample("manager_data")
