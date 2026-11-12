"""숫자 표기와 숫자 검사 — 모든 파트가 쓴다. docs/CONTRACT.md A7 코드 그대로."""
import re
from decimal import Decimal, ROUND_HALF_UP

from src.config import RULE_TOKENS


def _r1(x) -> Decimal:
    """소수 첫째 자리 사사오입. round()는 쓰지 않는다."""
    return Decimal(str(x)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def _s(d: Decimal) -> str:
    t = format(d, "f")
    return t[:-2] if t.endswith(".0") else t


def fmt_ratio(x: float) -> str:                       # 0.27 -> "27%"
    return _s(_r1(Decimal(str(x)) * 100)) + "%"


def fmt_signed_ratio(x: float) -> str:                # -0.35 -> "-35%" (증감률)
    q = _r1(Decimal(str(x)) * 100)
    return ("+" if q > 0 else "-" if q < 0 else "") + _s(abs(q)) + "%"


def fmt_pp(d: float) -> str:                          # 0.15 -> "+15%p"
    q = _r1(Decimal(str(d)) * 100)
    return ("+" if q > 0 else "-" if q < 0 else "") + _s(abs(q)) + "%p"


def fmt_change_pp(b: float, a: float) -> str:         # "12% → 27% (+15%p)"
    return f"{fmt_ratio(b)} → {fmt_ratio(a)} ({fmt_pp(a - b)})"


def fmt_top_pct(p: float) -> str:                     # 0.97 -> "상위 3%"
    return "상위 " + fmt_ratio(1 - p)


def fmt_multiple(a: float, b: float):                 # 0.27, 0.14 -> "1.9배"
    if not b:
        return None
    return _s(_r1(Decimal(str(a)) / Decimal(str(b)))) + "배"


def fmt_usd(x: float) -> str:                         # 1.2e9 -> "$1.2B"
    for unit, base in (("B", Decimal("1e9")), ("M", Decimal("1e6")), ("K", Decimal("1e3"))):
        if abs(Decimal(str(x))) >= base:
            return "$" + _s(_r1(Decimal(str(x)) / base)) + unit
    return "$" + _s(_r1(x))


def fmt_count(n: int, unit: str) -> str:              # 1234, "명" -> "1,234명"
    return f"{int(n):,}{unit}"


# 검사 대상 표기: $금액, %p, %, 배, 명 (리포트 검증에서는 건·점도)
# '개'는 "4개 분기" 같은 일반 표현과 겹쳐서 검사하지 않는다
_TOKEN = re.compile(
    r"\$\d+(?:\.\d+)?[KMB]?"
    r"|[+\-]?\d+(?:\.\d+)?%p"
    r"|[+\-]?\d+(?:\.\d+)?%"
    r"|\d+(?:\.\d+)?배"
    r"|\d{1,3}(?:,\d{3})+(?:명|건|점)|\d+(?:명|건|점)"
)


def number_tokens(text: str, include_report_units: bool = False) -> list[str]:
    toks = _TOKEN.findall(text.replace("−", "-"))
    if not include_report_units:
        toks = [t for t in toks if not (t.endswith("건") or t.endswith("점"))]
    return toks


def _both_signs(out: set, t):
    if t:
        out.add(t)
        out.add(t.lstrip("+-"))


def allowed_tokens(sig: dict) -> set[str]:
    """그 신호에 대해 글에 써도 되는 숫자 표기의 집합."""
    out = set(RULE_TOKENS) | set(number_tokens(sig["summary"]))   # summary는 코드가 만든 문장이라 믿는다
    b, a = sig["before"], sig["after"]
    if sig["unit"] == "ratio":
        for v in (b, a, sig["peer_median"]):
            if v is not None:
                out.add(fmt_ratio(v))
        for d in (sig["change"], sig["active_change"]):
            if d is not None:
                _both_signs(out, fmt_pp(d))
        if a is not None and sig["peer_median"]:
            out.add(fmt_multiple(a, sig["peer_median"]))
    elif sig["unit"] in ("usd", "count"):
        for v in (b, a):
            if v is not None:
                out.add(fmt_usd(v) if sig["unit"] == "usd" else fmt_count(v, "명"))
        if b and a is not None:
            _both_signs(out, fmt_signed_ratio((a - b) / b))
        if sig["unit"] == "count" and b is not None and a is not None:
            out.add(fmt_count(abs(a - b), "명"))
    if sig["percentile"] is not None:
        out.add(fmt_ratio(1 - sig["percentile"]))
    return out


def unknown_numbers(text: str, signals: list[dict]) -> list[str]:
    """글 속 숫자 중 관련 신호들로 설명되지 않는 것 (빈 목록이면 통과)."""
    allowed = set().union(*(allowed_tokens(s) for s in signals)) if signals else set(RULE_TOKENS)
    return [t for t in number_tokens(text) if t not in allowed]
