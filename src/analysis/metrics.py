"""지표 계산 (Data · 김지유, Data 문서 B2·B3). 계산식은 docs/metrics.md 와 같다.

prepare(q)               한 분기 보유 표 → 계산용 표 (ETF 제외, 비중·업종·규모 구간, 커버리지)
compute_changes(p, c)    이웃한 두 분기 → 지표 4개 + data_checks + unavailable
compute_series(quarters) 오래된 분기 → 최신 순 목록 → 분기 쌍마다 compute_changes (회전율 before 채움)

- 비율은 0~1 로 두고 반올림하지 않는다(반올림은 표기할 때 src/report/format.py 가 한다).
- 매매 기준 변화(active_change) = Σ 실제 최신 비중 − Σ passive 비중.
  passive 금액 = (보정한) 직전 주식 수 × 최신 주가. 최신 분기에 없는 종목(전량 매도)은 직전 주가.
"""
from __future__ import annotations

import math

import pandas as pd

from src.analysis.sectors import SECTORS, UNCLASSIFIED, sector_of
from src.analysis.splits import adjust_splits
from src.config import MIN_MAPPING_RATE, MIN_SIZE_COVERAGE, SIZE_BOUNDS_USD
from src.report.format import fmt_ratio

TOP_N = 10
SIZE_BUCKETS = ("소형", "중형", "대형")            # 동점이면 앞선 구간
SIZE_METRIC = {"소형": "small_cap_weight", "중형": "mid_cap_weight", "대형": "large_cap_weight"}
METRIC_KEYS = ("sector_shift", "size_shift", "concentration_change", "turnover")
_EPS = 1e-12

COLUMNS = ["issuer", "ticker", "value", "shares", "price", "w", "issuer_cik", "sector",
           "shares_outstanding", "size"]


# ======================================================================
# 준비
# ======================================================================
def size_bucket(price, shares_outstanding, partial: bool) -> str:
    """시가총액 구간. 정할 수 없으면 "미분류".
    partial(여러 종류 주식 중 한 종류만 잡힌 하한값)이면 대형 경계 이상일 때만 "대형"."""
    if not _pos(price) or not _pos(shares_outstanding):
        return UNCLASSIFIED
    mcap = price * shares_outstanding
    small_max, mid_max = SIZE_BOUNDS_USD
    if partial:
        return "대형" if mcap >= mid_max else UNCLASSIFIED
    if mcap < small_max:
        return "소형"
    if mcap < mid_max:
        return "중형"
    return "대형"


def prepare(q: dict) -> pd.DataFrame:
    """QuarterHoldings → 계산용 표(색인 cusip). 표의 attrs 에 V, mapping_rate, size_coverage."""
    rows = {}
    for h in q.get("holdings") or []:
        if h.get("is_etf"):
            continue                           # 준비 1: ETF 제외
        cusip = h["cusip"]
        value = float(h.get("value_usd") or 0)
        shares = float(h.get("shares") or 0)
        if cusip in rows:                      # 같은 CUSIP 이 또 있으면 합친다(보통은 Frontend 가 이미 합침)
            rows[cusip]["value"] += value
            rows[cusip]["shares"] += shares
            continue
        rows[cusip] = {
            "issuer": h.get("issuer"), "ticker": h.get("ticker"),
            "value": value, "shares": shares,
            "issuer_cik": h.get("issuer_cik"), "sic": h.get("sic"),
            "shares_outstanding": h.get("shares_outstanding"),
            "partial": bool(h.get("shares_outstanding_partial")),
        }

    df = pd.DataFrame.from_dict(rows, orient="index")
    if df.empty:
        df = pd.DataFrame(columns=COLUMNS)
        df.attrs.update(V=0.0, mapping_rate=0.0, size_coverage=0.0)
        return df
    df.index.name = "cusip"

    V = float(df["value"].sum())
    df["price"] = [v / s if s > 0 else math.nan for v, s in zip(df["value"], df["shares"])]
    df["w"] = df["value"] / V if V > 0 else 0.0
    df["sector"] = [sector_of(s) for s in df["sic"]]
    df["size"] = [size_bucket(p, so, part) for p, so, part
                  in zip(df["price"], df["shares_outstanding"], df["partial"])]

    mapped = df["issuer_cik"].notna() & (df["issuer_cik"].astype(str).str.len() > 0)
    df.attrs["V"] = V
    df.attrs["mapping_rate"] = float(df.loc[mapped, "value"].sum() / V) if V > 0 else 0.0
    df.attrs["size_coverage"] = float(df.loc[df["size"] != UNCLASSIFIED, "value"].sum() / V) if V > 0 else 0.0
    return df


# ======================================================================
# 두 분기 비교
# ======================================================================
def compute_changes(prev: dict, curr: dict) -> dict:
    """이웃한 두 분기(QuarterHoldings) → 지표.

    반환:
      {"sector_shift": {...} 또는 None, "size_shift": ..., "concentration_change": ..., "turnover": ...,
       "data_checks": [str], "unavailable": [str], "coverage": {...}}
      지표 하나 = {"metric", "before", "after", "change", "active_change", "magnitude"}.
      None 은 계산할 수 없다는 뜻이고, 이유는 unavailable 에 있다.
      turnover 의 before(직전 분기 회전율)는 여기서는 None. compute_series 가 채운다.
    """
    P, C = prepare(prev), prepare(curr)
    P_adj, checks = adjust_splits(P, C)
    unavailable: list[str] = []
    out: dict = {k: None for k in METRIC_KEYS}

    if P.attrs["V"] <= 0 or C.attrs["V"] <= 0:
        unavailable.append("지표 계산: 주식 보유가 없는 분기")
        out.update(data_checks=checks, unavailable=unavailable, coverage=_coverage(P, C))
        return out

    table = _joined(P, P_adj, C)

    # 업종·규모: 매핑률 검사 (두 분기 중 낮은 쪽)
    mapping = min(P.attrs["mapping_rate"], C.attrs["mapping_rate"])
    if mapping < MIN_MAPPING_RATE:
        unavailable.append(f"업종·규모 지표: 매핑률 {fmt_ratio(mapping)}")
    else:
        out["sector_shift"] = _group_shift(table, P, C, "sector", SECTORS,
                                           lambda g: f"sector_weight:{g}")
        size_cov = min(P.attrs["size_coverage"], C.attrs["size_coverage"])
        if size_cov < MIN_SIZE_COVERAGE:
            unavailable.append(f"규모 지표: 시가총액 확인 비율 {fmt_ratio(size_cov)}")
        else:
            out["size_shift"] = _group_shift(table, P, C, "size", SIZE_BUCKETS, SIZE_METRIC.get)

    out["concentration_change"] = _concentration(table, P, C)
    out["turnover"] = {"metric": "turnover", "before": None, "after": turnover(P, P_adj, C),
                       "change": None, "active_change": None, "magnitude": None}
    out["turnover"]["magnitude"] = out["turnover"]["after"]

    out.update(data_checks=checks, unavailable=unavailable, coverage=_coverage(P, C))
    return out


def compute_series(quarters: list[dict]) -> list[dict]:
    """오래된 분기 → 최신 순 QuarterHoldings 목록 → 이웃한 쌍마다 compute_changes.
    각 결과에 "period"(최신 쪽 분기)를 붙이고, 회전율 before 에 바로 앞 쌍의 회전율을 넣는다."""
    results = []
    prev_turnover = None
    for prev, curr in zip(quarters, quarters[1:]):
        r = compute_changes(prev, curr)
        r["period"] = curr.get("period")
        r["prev_period"] = prev.get("period")
        t = r.get("turnover")
        if t is not None:
            t["before"] = prev_turnover
            if prev_turnover is not None:
                t["change"] = t["after"] - prev_turnover
            prev_turnover = t["after"]
        else:
            prev_turnover = None
        results.append(r)
    return results


def turnover(P: pd.DataFrame, P_adj: pd.DataFrame, C: pd.DataFrame) -> float:
    """min(매수액, 매도액) ÷ ((V_prev + V_now) ÷ 2). 매수는 최신 주가, 매도는 직전 주가로 계산."""
    buys = sells = 0.0
    for cusip in P_adj.index.union(C.index):
        s_prev = float(P_adj.at[cusip, "shares"]) if cusip in P_adj.index else 0.0
        s_now = float(C.at[cusip, "shares"]) if cusip in C.index else 0.0
        delta = s_now - s_prev
        if delta > 0:
            buys += delta * float(C.at[cusip, "price"])
        elif delta < 0:
            sells += -delta * float(P_adj.at[cusip, "price"])
    avg_v = (P.attrs["V"] + C.attrs["V"]) / 2
    return min(buys, sells) / avg_v if avg_v > 0 else 0.0


# ======================================================================
# 내부
# ======================================================================
def _pos(x) -> bool:
    try:
        return x is not None and not math.isnan(float(x)) and float(x) > 0
    except (TypeError, ValueError):
        return False


def _joined(P: pd.DataFrame, P_adj: pd.DataFrame, C: pd.DataFrame) -> pd.DataFrame:
    """종목마다 직전 실제 비중, 최신 실제 비중, passive 비중, 업종·규모(최신 우선)."""
    idx = P.index.union(C.index)
    t = pd.DataFrame(index=idx)
    t["w_prev"] = P["w"].reindex(idx).fillna(0.0)
    t["w_now"] = C["w"].reindex(idx).fillna(0.0)

    passive = []
    for cusip in idx:
        if cusip not in P_adj.index:
            passive.append(0.0)                                    # 새로 산 종목
        elif cusip in C.index:
            passive.append(float(P_adj.at[cusip, "shares"]) * float(C.at[cusip, "price"]))
        else:
            passive.append(float(P_adj.at[cusip, "shares"]) * float(P_adj.at[cusip, "price"]))  # 전량 매도
    t["passive_amt"] = passive
    total = t["passive_amt"].sum()
    t["w_passive"] = t["passive_amt"] / total if total > 0 else 0.0

    for col in ("sector", "size"):
        t[col] = C[col].reindex(idx).combine_first(P[col].reindex(idx)).fillna(UNCLASSIFIED)
    return t


def _group_shift(t: pd.DataFrame, P: pd.DataFrame, C: pd.DataFrame, col: str, order, metric_name) -> dict | None:
    """묶음별 active_change 를 구해 절댓값이 가장 큰 묶음(동점이면 order 에서 앞선 것)."""
    best = None
    for g in order:
        sel = t[col] == g
        if not sel.any():
            continue
        active = float(t.loc[sel, "w_now"].sum() - t.loc[sel, "w_passive"].sum())
        if best is None or abs(active) > abs(best[1]) + _EPS:
            best = (g, active)
    if best is None:
        return None
    g, active = best
    before = float(P.loc[P[col] == g, "w"].sum())
    after = float(C.loc[C[col] == g, "w"].sum())
    return {"metric": metric_name(g), "before": before, "after": after, "change": after - before,
            "active_change": active, "magnitude": abs(active)}


def _top(weights: pd.Series) -> float:
    return float(weights.sort_values(ascending=False).head(TOP_N).sum())


def _concentration(t: pd.DataFrame, P: pd.DataFrame, C: pd.DataFrame) -> dict:
    before, after = _top(P["w"]), _top(C["w"])
    active = after - _top(t["w_passive"])
    return {"metric": "top10_concentration", "before": before, "after": after, "change": after - before,
            "active_change": active, "magnitude": abs(active)}


def _coverage(P: pd.DataFrame, C: pd.DataFrame) -> dict:
    return {"mapping_rate_prev": P.attrs.get("mapping_rate"), "mapping_rate_now": C.attrs.get("mapping_rate"),
            "size_coverage_prev": P.attrs.get("size_coverage"), "size_coverage_now": C.attrs.get("size_coverage")}
