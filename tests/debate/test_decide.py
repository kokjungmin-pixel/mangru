"""코드 판정(src/debate/decide.py) 규칙 테스트 — LLM 없이 돈다. (Backend 문서 B3 "코드 판정", B7)"""
import pytest

from src import config
from src.debate.decide import (
    build_options,
    no_debate_options,
    recommend,
    status_of,
    total,
)
from src.mock_data import sample
from src.state import Option
from src.validate import validate


# ---------- 도우미 ----------
def score(n: int) -> dict:
    """합계가 n점인 SideScore (수치3 → 근거3 → 반박2 → 한계2 순으로 채움)."""
    out = {}
    for key, cap in (("numbers", 3), ("grounds", 3), ("rebuttal", 2), ("limits", 2)):
        out[key] = min(cap, n)
        n -= out[key]
    assert n == 0, "합계는 10점 이하"
    return out


def signal(sid: str, form: str) -> dict:
    return {"id": sid, "source_form": form}


def verdict(sid: str, status: str) -> dict:
    keep, term = (score(7), score(6)) if status == "explained" else (score(5), score(8))
    return {"signal_id": sid, "keep": keep, "terminate": term, "status": status, "reason": "테스트"}


def arg(sid: str, side: str) -> dict:
    return {"signal_id": sid, "claim": f"{side} 논거", "evidence_idx": [0], "falsifier": f"{side} 반증 조건"}


# ---------- total / status_of ----------
def test_total_adds_four_items():
    assert total({"numbers": 1, "grounds": 2, "rebuttal": 1, "limits": 1}) == 5
    assert total({"numbers": 2, "grounds": 3, "rebuttal": 2, "limits": 1}) == 8


def test_a11_sample_5_vs_8_is_unexplained():
    keep = {"numbers": 1, "grounds": 2, "rebuttal": 1, "limits": 1}
    term = {"numbers": 2, "grounds": 3, "rebuttal": 2, "limits": 1}
    assert status_of(keep, term) == "unexplained"


def test_tie_6_6_is_unexplained():
    assert status_of(score(6), score(6)) == "unexplained"


def test_margin_7_6_is_explained():
    assert config.EXPLAINED_MARGIN == 1   # 기본값이 바뀌면 이 테스트의 기대값도 다시 본다
    assert status_of(score(7), score(6)) == "explained"


# ---------- recommend ----------
def test_zero_unexplained_is_maintain():
    sigs = [signal("s1", "ADV"), signal("s2", "13F")]
    vs = [verdict("s1", "explained"), verdict("s2", "explained")]
    assert recommend(vs, sigs) == "maintain"


def test_no_verdicts_is_maintain():
    assert recommend([], []) == "maintain"


def test_two_unexplained_is_conditional():
    sigs = [signal("s1", "ADV"), signal("s2", "ADV"), signal("s3", "13F")]
    vs = [verdict("s1", "unexplained"), verdict("s2", "unexplained"), verdict("s3", "explained")]
    assert recommend(vs, sigs) == "conditional"


def test_three_unexplained_with_adv_is_review_termination():
    sigs = [signal("s1", "13F"), signal("s2", "13F"), signal("s3", "ADV")]
    vs = [verdict(s["id"], "unexplained") for s in sigs]
    assert recommend(vs, sigs) == "review_termination"


def test_three_unexplained_all_13f_is_conditional():
    """기획서 규칙: 13F 신호만으로는 해지 검토를 권고하지 않는다."""
    sigs = [signal("s1", "13F"), signal("s2", "13F"), signal("s3", "13F")]
    vs = [verdict(s["id"], "unexplained") for s in sigs]
    assert recommend(vs, sigs) == "conditional"


def test_13f_rule_looks_only_at_unexplained_signals():
    """설명됨인 ADV 신호가 있어도 미설명이 모두 13F면 conditional."""
    sigs = [signal("s1", "13F"), signal("s2", "13F"), signal("s3", "13F"), signal("s4", "ADV")]
    vs = [verdict("s1", "unexplained"), verdict("s2", "unexplained"),
          verdict("s3", "unexplained"), verdict("s4", "explained")]
    assert recommend(vs, sigs) == "conditional"


# ---------- build_options ----------
def _check_options(opts: list, rec: str) -> None:
    assert [o["name"] for o in opts] == ["maintain", "conditional", "review_termination"]
    assert sum(o["recommended"] for o in opts) == 1
    assert next(o for o in opts if o["recommended"])["name"] == rec
    for o in opts:
        validate(o, Option)


@pytest.mark.parametrize("rec", ["maintain", "conditional", "review_termination"])
def test_options_always_three_and_one_recommended(rec):
    _check_options(build_options(rec, [], [], []), rec)


def test_option_grounds_come_from_the_right_side_with_signal_id():
    vs = [verdict("s1", "explained"), verdict("s2", "unexplained")]
    keep = [arg("s1", "유지"), arg("s2", "유지")]
    term = [arg("s1", "해지"), arg("s2", "해지")]
    opts = {o["name"]: o for o in build_options("conditional", vs, keep, term)}

    # 설명됨 → 유지 측 논거 / 미설명 → 유지 측 반증 조건 / 미설명 → 해지 측 논거
    assert opts["maintain"]["grounds"] == ["유지 논거 [s1]"]
    assert opts["conditional"]["grounds"] == ["유지 반증 조건 [s2]"]
    assert opts["review_termination"]["grounds"] == ["해지 논거 [s2]"]


def test_option_grounds_keep_verdict_order_and_skip_missing_args():
    """논거가 검사에서 지워진 신호는 근거에서 빠진다. 근거 순서는 판정 순서."""
    vs = [verdict("s2", "unexplained"), verdict("s1", "unexplained"), verdict("s3", "unexplained")]
    keep = [arg("s1", "유지"), arg("s2", "유지")]          # s3 유지 측 논거 없음
    term = [arg("s3", "해지"), arg("s1", "해지")]          # s2 해지 측 논거 없음
    opts = {o["name"]: o for o in build_options("review_termination", vs, keep, term)}
    assert opts["maintain"]["grounds"] == []
    assert opts["conditional"]["grounds"] == ["유지 반증 조건 [s2]", "유지 반증 조건 [s1]"]
    assert opts["review_termination"]["grounds"] == ["해지 논거 [s1]", "해지 논거 [s3]"]


def test_option_grounds_are_copied_verbatim():
    vs = [verdict("s1", "unexplained")]
    claim = "운용자산이 $12B에서 $7.8B로 줄어 고객 이탈 가능성이 있습니다."
    term = [{"signal_id": "s1", "claim": claim, "evidence_idx": [0], "falsifier": "x"}]
    opts = {o["name"]: o for o in build_options("conditional", vs, [], term)}
    assert opts["review_termination"]["grounds"] == [f"{claim} [s1]"]


# ---------- 토론을 하지 않을 때 ----------
def test_no_debate_options_counts_alert_and_watch():
    sigs = [{"id": "a", "level": "alert"}, {"id": "b", "level": "watch"}]
    opts = no_debate_options(sigs)
    _check_options(opts, "maintain")
    by = {o["name"]: o for o in opts}
    assert by["maintain"]["grounds"] == ["토론 개시 기준 미달: 경보 1건, 관찰 1건"]
    assert by["conditional"]["grounds"] == []
    assert by["review_termination"]["grounds"] == []


def test_no_debate_options_with_no_signals():
    by = {o["name"]: o for o in no_debate_options([])}
    assert by["maintain"]["grounds"] == ["토론 개시 기준 미달: 경보 0건, 관찰 0건"]


# ---------- 계약 샘플과 맞는가 ----------
def test_contract_sample_statuses_and_recommendation():
    deb = sample("debate")
    sigs = sample("analysis")["signals"]
    for v in deb["verdicts"]:
        assert status_of(v["keep"], v["terminate"]) == v["status"]
    assert recommend(deb["verdicts"], sigs) == deb["recommendation"]


def test_contract_sample_maintain_and_conditional_grounds():
    deb = sample("debate")
    opts = {o["name"]: o for o in build_options(
        deb["recommendation"], deb["verdicts"], deb["keep_args"], deb["terminate_args"])}
    want = {o["name"]: o for o in deb["options"]}
    assert opts["maintain"] == want["maintain"]
    assert opts["conditional"] == want["conditional"]
    assert opts["review_termination"]["recommended"] is False
