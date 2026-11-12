"""숫자 표기 — CONTRACT A7 표의 예 + PM 문서 B4 추가 테스트"""
import json

from src.config import FIXTURES_DIR
from src.report.format import (allowed_tokens, fmt_change_pp, fmt_count, fmt_multiple, fmt_pp,
                               fmt_ratio, fmt_signed_ratio, fmt_top_pct, fmt_usd, number_tokens,
                               unknown_numbers)

A11 = json.loads((FIXTURES_DIR / "a11_signals.sample.json").read_text(encoding="utf-8"))["signals"]
SMALL_CAP = A11[1]
ANALYSIS = json.loads((FIXTURES_DIR / "analysis.sample.json").read_text(encoding="utf-8"))


def test_ratio():
    assert fmt_ratio(0.27) == "27%"
    assert fmt_ratio(0.1225) == "12.3%"    # 사사오입 (round()였다면 12.2%)
    assert fmt_ratio(0.125) == "12.5%"


def test_pp():
    assert fmt_pp(0.15) == "+15%p"
    assert fmt_pp(-0.0216) == "-2.2%p"
    assert fmt_pp(0) == "0%p"
    assert fmt_pp(-0.21645) == "-21.6%p"
    assert fmt_change_pp(0.12, 0.27) == "12% → 27% (+15%p)"


def test_misc():
    assert fmt_top_pct(0.97) == "상위 3%"
    assert fmt_top_pct(0.96) == "상위 4%"
    assert fmt_multiple(0.27, 0.14) == "1.9배"
    assert fmt_multiple(0.27, 0) is None
    assert fmt_usd(1.2e9) == "$1.2B"
    assert fmt_usd(850e6) == "$850M"
    assert fmt_usd(999) == "$999"
    assert fmt_signed_ratio(-0.35) == "-35%"
    assert fmt_count(1234, "명") == "1,234명"


def test_number_tokens():
    assert number_tokens("소형주 비중 12% → 27% (+15%p), 상위 3%") == ["12%", "27%", "+15%p", "3%"]


def test_allowed_tokens_small_cap():
    ok = allowed_tokens(SMALL_CAP)
    for t in ["12%", "27%", "+15%p", "15%p", "+14%p", "14%p", "3%", "5%", "10%"]:
        assert t in ok, t


def test_unknown_numbers():
    assert unknown_numbers("…31%까지 갈 수 있다", [SMALL_CAP]) == ["31%"]
    assert unknown_numbers("운용자산이 $12B에서 $7.8B로", ANALYSIS["signals"]) == []
