"""② 수집 — collect (Frontend · 조재연). Frontend 문서 B3 "조립".
- demo_mode=True : data_cache/demo/<id>/manager_data.json 을 읽는다. 없으면 어떤 파일이 없는지 알려 주는 오류.
- demo_mode=False: 13F(주식형만)·ADV Part 1·ADV 2A 를 SEC 에서 받아 조립한다. 저장은 명령줄
  `python -m src.collect demo1 --live` 만 한다(테스트가 실제 모드로 돌 때 데모 저장본을 덮어쓰지 않게).
신·구본 비교는 compare.py (13F 비교표·임원 변경). TODO(조재연): ADV 2A 문구 비교(text_changes) — PM 결정 뒤.
"""
import json
from datetime import datetime, timezone

from src.collect.compare import compare_holdings, compare_people
from src.collect.form_adv import collect_adv1, collect_adv2a, item2_declares_no_change
from src.config import DEMO_DIR, DEMO_MANAGERS
from src.state import ManagerData, Plan
from src.validate import validate

DEMO_FILE = "manager_data.json"
NOT_COMPARED = "ADV 2A 문구 비교: 확인 불가 (날짜 조건·Item 2 판정·문단 나누기 PM 결정 대기, verified.md 11/21·22)"


def _has_new_filing(last_check: str | None, latest: dict[str, str | None]) -> tuple[bool, list[str]]:
    """latest: {공시 이름: 최신 제출일 또는 None(받지 못함)}. 조기 종료는 모든 공시의 제출일을 알고 전부 기준일 이하일 때만."""
    if last_check is None:
        return True, []
    known = [d for d in latest.values() if d]
    if any(d > last_check for d in known):
        return True, []
    missing = [k for k, d in latest.items() if not d]
    if missing:   # 받지 못한 공시가 새로 나왔을 수 있으니 조기 종료하지 않는다
        return True, [f"새 공시 여부: 확인 불가 ({', '.join(missing)} 제출일을 받지 못함) → 조기 종료하지 않고 점검"]
    return False, []


def collect_live(manager_id: str) -> ManagerData:
    """SEC 에서 받아 ManagerData 로 조립한다. 받지 못한 것은 unavailable 에 적고 끝까지 간다."""
    # 여기서 불러온다: 맨 위에서 부르면 analysis.securities → collect.sec_client → 이 파일 → form13f → securities 순환
    from src.collect.form13f import collect_13f
    m = DEMO_MANAGERS[manager_id]
    notes: list[str] = []
    unavailable: list[str] = []
    quarters = []
    if m["has_13f"]:
        quarters, ns, us = collect_13f(m["cik"])
        notes += ns
        unavailable += us
    else:
        notes.append("13F: 쓰지 않음 (주식형이 아님, config has_13f=False)")
    adv1_new, adv1_old, ns, us = collect_adv1(m["crd"], m["last_check_date"])
    notes += ns
    unavailable += us
    adv2a_new, adv2a_old, ns, us = collect_adv2a(m["crd"], m["last_check_date"])
    notes += ns
    unavailable += us
    item2 = item2_declares_no_change((adv2a_new or {}).get("items", {}).get("2"))
    if adv2a_new and item2 is None:
        unavailable.append("ADV 2A Item 2 '중요 변경 없음' 판정: 확인 불가")
    latest = {"ADV Part 1": (adv1_new or {}).get("filed_date"), "ADV 2A": (adv2a_new or {}).get("filed_date")}
    if m["has_13f"]:
        latest["13F"] = max((q["filed_date"] for q in quarters), default=None)
    has_new, us = _has_new_filing(m["last_check_date"], latest)
    holding_changes, u1 = compare_holdings(quarters)
    person_changes, u2 = compare_people(adv1_new, adv1_old, m["last_check_date"])
    us += u1 + u2
    data: ManagerData = {
        "manager_id": manager_id, "manager_name": m["name"], "cik": m["cik"], "crd": m["crd"],
        "quarters": quarters, "holding_changes": holding_changes,
        "adv1_new": adv1_new, "adv1_old": adv1_old, "adv2a_new": adv2a_new, "adv2a_old": adv2a_old,
        "person_changes": person_changes, "text_changes": [], "item2_declares_no_change": item2,
        "has_new_filing": has_new, "notes": notes, "unavailable": unavailable + us + [NOT_COMPARED],
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    validate(data, ManagerData)
    return data


def save_demo(data: ManagerData) -> str:
    """데모 저장본 쓰기. 형식은 CONTRACT A9 ({"fingerprint", "result"}, manager_data 는 입력이 없어 fingerprint=None)."""
    path = DEMO_DIR / data["manager_id"] / DEMO_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"fingerprint": None, "result": data}, ensure_ascii=False, indent=1), encoding="utf-8")
    return str(path)


def load_demo(manager_id: str) -> ManagerData:
    path = DEMO_DIR / manager_id / DEMO_FILE
    if not path.exists():
        raise FileNotFoundError(f"데모 저장본 없음: {path} (python -m src.collect {manager_id} --live 로 만든다)")
    data = json.loads(path.read_text(encoding="utf-8"))["result"]
    if data.get("manager_id") != manager_id:   # 다른 운용사 저장본을 잘못 넣었으면 그대로 쓰지 않는다
        raise ValueError(f"데모 저장본의 운용사가 다름: {path} 안은 {data.get('manager_id')!r}")
    validate(data, ManagerData)
    return data


def collect(plan: Plan, demo_mode: bool = True) -> ManagerData:
    return load_demo(plan["manager_id"]) if demo_mode else collect_live(plan["manager_id"])
