"""주식 분할 보정 (Data · 김지유, Data 문서 B2 "주식 분할 보정").

두 분기 모두 보유한 종목마다 주가 변화 c = price_now ÷ price_prev 를 본다.
1. 두 분기 모두 shares_outstanding 이 있으면 k = so_now ÷ so_prev.
   (k ≥ 1.4 또는 k ≤ 1/1.4) 이고 0.7 ≤ c × k ≤ 1.4 → 분할로 보고 직전 주식 수 × k, 직전 주가 ÷ k.
2. 1에 해당하지 않고, 발행주식 수를 몰라 확인할 수 없는데 c < 0.55 또는 c > 1.8
   → 분할 여부 확인 불가. 그 종목은 매매가 없었던 것으로 둔다(직전 주식 수 := 최신 주식 수).
3. 보정·제외한 종목은 data_checks 에 남긴다.
"""
import math

import pandas as pd

from src.config import PRICE_JUMP_BAND, SPLIT_CAP_BAND, SPLIT_SO_RATIO


def _known(x) -> bool:
    return x is not None and not (isinstance(x, float) and math.isnan(x)) and x > 0


def _fmt_k(k: float) -> str:
    r = round(k, 2)
    return str(int(r)) if r == int(r) else f"{r:g}"


def adjust_splits(prev: pd.DataFrame, curr: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """prepare() 로 만든 두 분기 표 → (보정한 직전 분기 표, data_checks 문장 목록).
    직전 표의 shares·price 만 바꾼다. value(실제 금액)와 비중은 그대로 둔다."""
    out = prev.copy()
    checks: list[str] = []
    common = out.index.intersection(curr.index)
    for cusip in common:
        p, c_row = out.loc[cusip], curr.loc[cusip]
        if not (_known(p["price"]) and _known(c_row["price"])):
            continue
        c = c_row["price"] / p["price"]
        name = c_row.get("ticker") or c_row.get("issuer") or cusip

        so_prev, so_now = p.get("shares_outstanding"), c_row.get("shares_outstanding")
        if _known(so_prev) and _known(so_now):
            k = so_now / so_prev
            if (k >= SPLIT_SO_RATIO or k <= 1 / SPLIT_SO_RATIO) and SPLIT_CAP_BAND[0] <= c * k <= SPLIT_CAP_BAND[1]:
                out.at[cusip, "shares"] = p["shares"] * k
                out.at[cusip, "price"] = p["price"] / k
                checks.append(f"분할 보정: {name} ×{_fmt_k(k)}")
            continue                           # 발행주식 수로 확인했으면 2번 규칙은 보지 않는다

        if c < PRICE_JUMP_BAND[0] or c > PRICE_JUMP_BAND[1]:
            out.at[cusip, "shares"] = c_row["shares"]
            checks.append(f"가격 급변으로 매매 계산 제외: {name}")
    return out, checks
