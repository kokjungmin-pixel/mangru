"""신호 판정 (Data · 김지유, Data 문서 B4 "판정", CONTRACT A8). LLM 없음.

detect_signals(data) -> list[Signal]     계약 함수
detect(data) -> Detection                 신호 + data_checks + unavailable + debate_required (analyze 가 씀)

13F 지표 (sector_shift, size_shift, concentration_change, turnover):
  m   = 이번 분기 변화폭, own = 직전 최대 12개 변화폭의 최댓값(4개 미만이면 판정 불가)
  경보: pct >= 0.95 / 관찰: 0.90 <= pct < 0.95 이고 m > own
  thresholds.json 이 placeholder 면 pct 대신 m >= p95 / p90 <= m < p95 로 판정하고 percentile=None.
ADV: 임원·소유주 변경 → 경보, Item 8 실질 변경·Item 2 불일치·운용자산·직원·사모펀드 → 관찰.
토론 개시: 경보 1개 이상 또는 관찰 2개 이상. item2_mismatch 가 strategy_text_changed 와 함께 나오면 관찰 1개로 센다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from src import config
from src.analysis.metrics import METRIC_KEYS, compute_series
from src.report.format import (fmt_change_pp, fmt_count, fmt_pp, fmt_ratio, fmt_signed_ratio,
                               fmt_top_pct, fmt_usd)
from src.state import Evidence, ManagerData, Signal

METRIC_LABEL = {"sector_shift": "업종 비중 변화", "size_shift": "규모 비중 변화",
                "concentration_change": "상위 10종목 집중도 변화", "turnover": "회전율"}
SIZE_NAME = {"small_cap_weight": "소형주 비중", "mid_cap_weight": "중형주 비중",
             "large_cap_weight": "대형주 비중", "top10_concentration": "상위 10종목 비중",
             "turnover": "분기 회전율"}
OWN_WINDOW = 12                        # 직전 12개 분기 = 3년


@dataclass
class Detection:
    signals: list[Signal] = field(default_factory=list)
    data_checks: list[str] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)
    debate_required: bool = False


def detect_signals(data: ManagerData) -> list[Signal]:
    return detect(data).signals


def detect(data: ManagerData, thresholds: dict | None = None) -> Detection:
    out = Detection()
    th = load_thresholds() if thresholds is None else thresholds
    raw: list[dict] = []
    raw += _signals_13f(data, th, out)
    raw += _signals_people(data)
    raw += _signals_text(data)
    raw += _signals_adv1(data)
    out.signals = _assign_ids(data["manager_id"], raw)
    out.debate_required = debate_required(out.signals)
    return out


def debate_required(signals: list[Signal]) -> bool:
    alerts = sum(1 for s in signals if s["level"] == "alert")
    watch = [s for s in signals if s["level"] == "watch"]
    n_watch = len(watch)
    metrics = {s["metric"] for s in watch}
    if "item2_mismatch" in metrics and "strategy_text_changed" in metrics:
        n_watch -= 1                   # 같은 Item 8 변경에서 나온 신호 (11/25 PM·Data 합의)
    return alerts >= 1 or n_watch >= 2


def load_thresholds() -> dict:
    try:
        return json.loads(config.THRESHOLDS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"metrics": {}, "levels": {}}


def percentile_of(m: float, quantiles: list[float]) -> float:
    """m 이 0~100 백분위 값 101개 사이 어디에 놓이는지 선형 보간 → 0~1."""
    q = quantiles
    if m <= q[0]:
        return 0.0
    if m >= q[-1]:
        return 1.0
    for i in range(1, len(q)):
        if m <= q[i]:
            lo, hi = q[i - 1], q[i]
            frac = 0.0 if hi == lo else (m - lo) / (hi - lo)
            return (i - 1 + frac) / 100
    return 1.0


# ======================================================================
# 13F
# ======================================================================
def _signals_13f(data: ManagerData, th: dict, out: Detection) -> list[dict]:
    quarters = data.get("quarters") or []
    if len(quarters) < 2:
        return []
    series = compute_series(quarters)
    last = series[-1]
    out.data_checks += last["data_checks"]
    out.unavailable += last["unavailable"]
    prev_q, curr_q = quarters[-2], quarters[-1]
    evidence = [_ev_13f(curr_q), _ev_13f(prev_q)]

    sigs = []
    for key in METRIC_KEYS:
        res = last.get(key)
        if res is None or res.get("magnitude") is None:
            continue                                          # 이유는 이미 unavailable 에 있음
        label = METRIC_LABEL[key]
        rule = (th.get("metrics") or {}).get(key)
        if not rule:
            out.unavailable.append(f"{label}: 전체 13F 운용사 기준값 없음")
            continue
        m = res["magnitude"]
        history = [r[key]["magnitude"] for r in series[:-1][-OWN_WINDOW:]
                   if r.get(key) is not None and r[key].get("magnitude") is not None]
        own = max(history) if len(history) >= config.MIN_HISTORY_CHANGES else None
        if own is not None and len(history) < OWN_WINDOW:
            out.data_checks.append(f"{label}: 직전 변화 {len(history)}개로 자기 3년 최대치 판정")

        placeholder = rule.get("mode") != "distribution" or not rule.get("quantiles")
        if placeholder:
            pct = None
            is_alert = m >= rule["p95"]
            in_watch = rule["p90"] <= m < rule["p95"]
        else:
            pct = percentile_of(m, rule["quantiles"])
            is_alert = pct >= config.ALERT_PERCENTILE
            in_watch = config.WATCH_PERCENTILE <= pct < config.ALERT_PERCENTILE

        level = None
        if is_alert:
            level = "alert"
        elif in_watch:
            if own is None:
                out.unavailable.append(f"{label}: 직전 변화 {len(history)}개, 자기 3년 최대치 판정 불가")
            elif m > own:
                level = "watch"
        if level is None:
            continue
        sigs.append({
            "kind": "strategy_drift", "level": level, "source_form": "13F", "metric": res["metric"],
            "unit": "ratio", "before": res["before"], "after": res["after"], "change": res["change"],
            "active_change": res["active_change"], "percentile": pct,
            "exceeds_own_3y_max": (m > own) if own is not None else None, "peer_median": None,
            "summary": _summary_13f(res, pct, placeholder), "evidence": evidence,
        })
    return sigs


def _metric_name(metric: str) -> str:
    if metric.startswith("sector_weight:"):
        return f"{metric.split(':', 1)[1]} 업종 비중"
    return SIZE_NAME.get(metric, metric)


def _summary_13f(res: dict, pct: float | None, placeholder: bool) -> str:
    name = _metric_name(res["metric"])
    if res["metric"] == "turnover":
        head = f"{name} {fmt_ratio(res['after'])}"
        if res["before"] is not None:
            head += f" (직전 {fmt_ratio(res['before'])})"
    else:
        head = f"{name} {fmt_change_pp(res['before'], res['after'])}, 매매 기준 {fmt_pp(res['active_change'])}"
    tail = "(임시 기준)" if placeholder or pct is None else f"전체 13F 운용사 분기 변화폭 {fmt_top_pct(pct)}"
    return f"{head}, {tail}"


def _ev_13f(q: dict) -> Evidence:
    return {"source": f"Form 13F {q['period']}", "url": q.get("url") or "",
            "as_of": q.get("report_date") or "", "page": None, "quote": None}


# ======================================================================
# ADV: 임원·소유주
# ======================================================================
def _is_person(ch: dict) -> bool:
    p = ch.get("after") or ch.get("before") or {}
    return p.get("entity_type") in (None, "I")


def _signals_people(data: ManagerData) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for ch in data.get("person_changes") or []:
        kind = ch.get("kind")
        if kind == "ownership_changed" or not _is_person(ch):
            metric = "owner_changed"
        elif kind == "added":
            metric = "officer_added"
        elif kind == "removed":
            metric = "officer_removed"
        elif kind == "title_changed":
            metric = "title_changed"
        else:
            continue
        groups.setdefault(metric, []).append(ch)

    sigs = []
    for metric, chs in groups.items():
        sigs.append({
            "kind": "key_person", "level": "alert", "source_form": "ADV", "metric": metric,
            "unit": "text", "before": None, "after": None, "change": None, "active_change": None,
            "percentile": None, "exceeds_own_3y_max": None, "peer_median": None,
            "summary": _summary_people(metric, chs), "evidence": _merge_evidence(chs),
        })
    return sigs


def _title(p: dict | None) -> str:
    return (p or {}).get("title") or "직함 미기재"


def _summary_people(metric: str, chs: list[dict]) -> str:
    n = len(chs)
    if metric == "officer_added":
        return f"임원 {fmt_count(n, '명')} 추가: " + ", ".join(f"{c['name']}({_title(c.get('after'))})" for c in chs)
    if metric == "officer_removed":
        return f"임원 {fmt_count(n, '명')} 제외: " + ", ".join(f"{c['name']}({_title(c.get('before'))})" for c in chs)
    if metric == "title_changed":
        return f"임원 {fmt_count(n, '명')} 직함 변경: " + ", ".join(
            f"{c['name']}({_title(c.get('before'))} → {_title(c.get('after'))})" for c in chs)
    kinds = {"added": "추가", "removed": "제외", "ownership_changed": "지분 변경", "title_changed": "직함 변경"}
    return "소유주 변경: " + ", ".join(f"{c['name']}({kinds.get(c.get('kind'), '변경')})" for c in chs)


def _merge_evidence(items: list[dict]) -> list[Evidence]:
    seen, out = set(), []
    for it in items:
        for e in it.get("evidence") or []:
            key = (e.get("source"), e.get("url"), e.get("as_of"), e.get("page"), e.get("quote"))
            if key not in seen:
                seen.add(key)
                out.append(e)
    return out


# ======================================================================
# ADV 2A: Item 8 실질 변경, Item 2 불일치
# ======================================================================
def _signals_text(data: ManagerData) -> list[dict]:
    material = [t for t in data.get("text_changes") or [] if str(t.get("item")) == "8" and t.get("material")]
    if not material:
        return []
    base = {"kind": "strategy_drift", "level": "watch", "source_form": "ADV", "unit": "text",
            "before": None, "after": None, "change": None, "active_change": None, "percentile": None,
            "exceeds_own_3y_max": None, "peer_median": None}
    ev8 = _merge_evidence(material)
    sigs = [dict(base, metric="strategy_text_changed",
                 summary=f"ADV 2A Item 8(투자 전략·위험) 실질 변경 문단 {len(material)}곳", evidence=ev8)]
    if data.get("item2_declares_no_change") is True:
        adv = data.get("adv2a_new") or {}
        ev2 = [{"source": "Form ADV Part 2A Item 2", "url": adv.get("url") or "",
                "as_of": adv.get("filed_date") or "", "page": (adv.get("pages") or {}).get("2"), "quote": None}]
        sigs.append(dict(base, metric="item2_mismatch",
                         summary="ADV 2A Item 2는 중요 변경이 없다고 적었지만 Item 8에 실질 변경",
                         evidence=ev2 + ev8))
    return sigs


# ======================================================================
# ADV Part 1: 운용자산·직원·사모펀드
# ======================================================================
def _ok(x) -> bool:
    return x is not None


def _signals_adv1(data: ManagerData) -> list[dict]:
    old, new = data.get("adv1_old"), data.get("adv1_new")
    if not old or not new:
        return []
    dates = f"ADV 제출일 {old.get('filed_date')} → {new.get('filed_date')}"
    evidence = [{"source": "Form ADV Part 1A", "url": new.get("url") or "", "as_of": new.get("filed_date") or "",
                 "page": None, "quote": None},
                {"source": "Form ADV Part 1A (직전본)", "url": old.get("url") or "",
                 "as_of": old.get("filed_date") or "", "page": None, "quote": None}]
    base = {"level": "watch", "source_form": "ADV", "active_change": None, "percentile": None,
            "exceeds_own_3y_max": None, "peer_median": None, "evidence": evidence}
    sigs = []

    b, a = old.get("aum_usd"), new.get("aum_usd")
    if _ok(b) and _ok(a) and b > 0:
        r = (a - b) / b
        if r <= -config.AUM_DROP or r >= config.AUM_JUMP:
            sigs.append(dict(base, kind="strategy_drift", metric="aum_change", unit="usd",
                             before=b, after=a, change=a - b,
                             summary=f"운용자산 {fmt_usd(b)} → {fmt_usd(a)} ({fmt_signed_ratio(r)}), {dates}"))

    b, a = old.get("employees"), new.get("employees")
    if _ok(b) and _ok(a) and b > 0:
        d = b - a
        if d >= config.EMPLOYEE_DROP_MIN and d / b >= config.EMPLOYEE_DROP_RATE:
            sigs.append(dict(base, kind="key_person", metric="employee_drop", unit="count",
                             before=float(b), after=float(a), change=float(a - b),
                             summary=f"직원 {fmt_count(b, '명')} → {fmt_count(a, '명')} "
                                     f"({fmt_signed_ratio((a - b) / b)}), {dates}"))

    b, a = old.get("private_funds"), new.get("private_funds")
    if _ok(b) and _ok(a):
        e = abs(a - b)
        if e >= config.PRIVATE_FUND_MIN_DIFF and e / max(b, 1) >= config.PRIVATE_FUND_RATE:
            sigs.append(dict(base, kind="strategy_drift", metric="private_fund_change", unit="count",
                             before=float(b), after=float(a), change=float(a - b),
                             summary=f"사모펀드 {b}개 → {a}개, {dates}"))
    return sigs


# ======================================================================
# id
# ======================================================================
def _assign_ids(manager_id: str, raw: list[dict]) -> list[Signal]:
    raw = sorted(raw, key=lambda s: (s["kind"], s["metric"]))
    counter: dict[str, int] = {}
    out = []
    for s in raw:
        counter[s["kind"]] = counter.get(s["kind"], 0) + 1
        sig: Signal = {"id": f"{manager_id}-{s['kind']}-{counter[s['kind']]}", "manager_id": manager_id,
                       "kind": s["kind"], "level": s["level"], "source_form": s["source_form"],
                       "metric": s["metric"], "unit": s["unit"], "before": s["before"], "after": s["after"],
                       "change": s["change"], "active_change": s["active_change"],
                       "percentile": s["percentile"], "exceeds_own_3y_max": s["exceeds_own_3y_max"],
                       "peer_median": s["peer_median"], "summary": s["summary"],
                       "explanation": s["summary"], "evidence": s["evidence"]}
        out.append(sig)
    return out
