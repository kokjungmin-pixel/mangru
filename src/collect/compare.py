"""신·구본 비교 (Frontend · 조재연). Frontend 문서 B4. 사실을 나란히 놓는 것까지 — 해석·신호 판정은 Data.
지금 있는 것: 13F 분기 비교표(compare_holdings), ADV Part 1 임원·소유주 비교(compare_people).
TODO(조재연): ADV 2A 문구 비교(TextChange) — 날짜 조건·Item 2 판정·문단 나누기 PM 결정 뒤 (verified.md 11/21·22).
"""
import re

from src.config import NEW_OFFICER_WINDOW_MONTHS

SCHEDULE_A = "Form ADV Part 1A Schedule A"
_SUFFIXES = {"JR", "SR", "II", "III", "IV"}


# ---------- 13F 분기 비교 → HoldingChange ----------
def _qindex(period: str) -> int:
    return int(period[:4]) * 4 + int(period[-1])


def compare_holdings(quarters: list[dict]) -> tuple[list[dict], list[str]]:
    """최신 분기 vs 바로 앞 분기 → (HoldingChange 목록, unavailable). 비중 = 종목 금액 ÷ 그 분기 전체(ETF 포함).
    비중 변화가 큰 순으로 정렬한다(화면 표 순서). 13F 를 쓰지 않는 운용사에는 부르지 않는다(collect_live)."""
    if len(quarters) < 2:   # 13F 를 하나도 못 받은 경우(0개)도 '변화 없음'이 아니라 확인 불가
        return [], ["13F 비교표: 확인 불가 (분기가 2개 미만)"]
    old, new = quarters[-2], quarters[-1]
    if _qindex(new["period"]) - _qindex(old["period"]) != 1:   # 빠진 분기를 건너뛴 비교는 '직전 분기 대비'가 아니다
        i = _qindex(new["period"]) - 1
        missing = f"{(i - 1) // 4}Q{(i - 1) % 4 + 1}"
        return [], [f"13F 비교표: 확인 불가 (직전 분기 {missing} 가 없음, {old['period']} 와는 비교하지 않음)"]
    totals = {q["period"]: sum(h["value_usd"] for h in q["holdings"]) for q in (old, new)}
    zero = [p for p, t in totals.items() if t <= 0]
    if zero:
        return [], [f"13F 비교표: 확인 불가 ({', '.join(zero)} 보유 금액 합계가 0)"]
    before = {h["cusip"]: h for h in old["holdings"]}
    after = {h["cusip"]: h for h in new["holdings"]}
    rows = []
    for cusip in list(after) + [c for c in before if c not in after]:
        a, b = after.get(cusip), before.get(cusip)
        rows.append({"cusip": cusip, "issuer": (a or b)["issuer"], "ticker": (a or {}).get("ticker") or (b or {}).get("ticker"),
                     "kind": "held" if a and b else ("new" if a else "exit"),
                     "shares_before": b["shares"] if b else 0.0, "shares_after": a["shares"] if a else 0.0,
                     "value_before": b["value_usd"] if b else 0.0, "value_after": a["value_usd"] if a else 0.0,
                     "weight_before": b["value_usd"] / totals[old["period"]] if b else 0.0,
                     "weight_after": a["value_usd"] / totals[new["period"]] if a else 0.0})
    rows.sort(key=lambda r: (-abs(r["weight_after"] - r["weight_before"]), r["cusip"]))
    return rows, []


# ---------- ADV Part 1 임원·소유주 비교 → PersonChange ----------
def _words(s: str) -> list[str]:
    return re.sub(r"[^\w\s]", " ", (s or "").upper().replace("&", " AND ")).split()


def person_key(p: dict) -> tuple[str, str]:
    """같은 사람인지 가리는 열쇠. 개인은 대문자·문장부호·호칭(JR 등) 제거 후 단어 순서를 무시('성, 이름' = '이름 성'),
    법인(DE/FE)은 단어 순서를 그대로 둔다. 개인과 법인은 따로 맞춘다."""
    words = _words(p["name"])
    if p["entity_type"] == "I":
        return "I", " ".join(sorted(w for w in words if w not in _SUFFIXES))
    return p["entity_type"] or "?", " ".join(words)


def _evidence(part: dict, label: str = "") -> dict:
    return {"source": SCHEDULE_A + label, "url": part["url"], "as_of": part["filed_date"], "page": None, "quote": None}


def _since_cut(new: dict, last_check: str | None) -> tuple[str, bool]:
    """이전본이 없을 때 '새로 취임'으로 볼 기준 연월 → (연월, 그 달 포함 여부).
    직전 점검일이 있으면 그 달 다음부터, 없으면 최신 제출일 기준 최근 NEW_OFFICER_WINDOW_MONTHS 개월 (A8)."""
    if last_check:
        return last_check[:7], False
    y, m = int(new["filed_date"][:4]), int(new["filed_date"][5:7])
    i = y * 12 + m - 1 - NEW_OFFICER_WINDOW_MONTHS
    return f"{i // 12}-{i % 12 + 1:02d}", True


def _change(kind: str, before: dict | None, after: dict | None, evidence: list[dict]) -> dict:
    return {"kind": kind, "name": (after or before)["name"], "before": before, "after": after, "evidence": evidence}


def compare_people(new: dict | None, old: dict | None, last_check: str | None) -> tuple[list[dict], list[str]]:
    """최신본 vs 직전본 AdvPart1 → (PersonChange 목록, unavailable).
    added(최신본에만)·removed(직전본에만)·title_changed·ownership_changed. 근거는 [최신본, 직전본] 순."""
    if not new:
        return [], ["임원·소유주 비교: 확인 불가 (ADV Part 1 최신본 없음)"]
    if not new["people"]:   # Part 1 이 명단을 못 읽으면 [] → 비교하면 전원 삭제가 된다
        return [], ["임원·소유주 비교: 확인 불가 (최신본 Schedule A 명단을 읽지 못함)"]
    if not old or not old["people"]:
        cut, inclusive = _since_cut(new, last_check)
        rows = [_change("added", None, p, [_evidence(new)]) for p in new["people"]
                if p["since"] and (p["since"] >= cut if inclusive else p["since"] > cut)]
        why = "이전본 없음" if not old else "확인 불가 (직전본 Schedule A 명단을 읽지 못함)"
        return rows, [f"임원 제외 여부: {why} → 취임 연월로 새 임원만 찾음"]
    keys_new = [person_key(p) for p in new["people"]]
    keys_old = [person_key(p) for p in old["people"]]
    dup = {k for ks in (keys_new, keys_old) for k in ks if ks.count(k) > 1}
    unavailable = [f"임원·소유주 비교: 같은 사람이 여러 번 나와 비교에서 뺌: "
                   f"{', '.join(sorted({p['name'] for p, k in zip(new['people'] + old['people'], keys_new + keys_old) if k in dup}))}"
                   ] if dup else []
    before = {k: p for k, p in zip(keys_old, old["people"]) if k not in dup}
    after = {k: p for k, p in zip(keys_new, new["people"]) if k not in dup}
    both = [_evidence(new), _evidence(old, " (직전본)")]
    rows = []
    for k, a in after.items():
        b = before.get(k)
        if b is None:
            rows.append(_change("added", None, a, both))
            continue
        if _words(a["title"]) != _words(b["title"]):
            rows.append(_change("title_changed", b, a, both))
        if (a["ownership_code"] or "") != (b["ownership_code"] or ""):
            rows.append(_change("ownership_changed", b, a, both))
    rows += [_change("removed", b, None, both) for k, b in before.items() if k not in after]
    return rows, unavailable
