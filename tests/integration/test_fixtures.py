"""계약 샘플 5개가 state.py 모양과 맞는지 (11/15 데이터 형식 확정 기준)"""
import json

import pytest

from src.config import FIXTURES_DIR
from src.state import AnalysisResult, DebateResult, ManagerData, ReportDraft, VerifyResult
from src.validate import validate

CASES = [("manager_data", ManagerData), ("analysis", AnalysisResult), ("debate", DebateResult),
         ("draft", ReportDraft), ("verify", VerifyResult)]


@pytest.mark.parametrize("name,type_", CASES)
def test_fixture_matches_contract(name, type_):
    obj = json.loads((FIXTURES_DIR / f"{name}.sample.json").read_text(encoding="utf-8"))
    validate(obj, type_)


def test_validate_rejects_wrong_shape():
    with pytest.raises(Exception):
        validate({"passed": "yes"}, VerifyResult)
