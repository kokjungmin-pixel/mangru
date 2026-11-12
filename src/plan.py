"""① 계획 — make_plan (PM). LLM 없이 규칙으로 운용사를 찾는다."""
from datetime import date

from src.config import DEMO_MANAGERS
from src.state import Plan

CHECKS = ["strategy_drift", "key_person", "peer_anomaly"]


def _period(today: date) -> str:
    return f"{today.year}H1" if today.month <= 6 else f"{today.year}H2"


def make_plan(request: str, today: date | None = None) -> Plan | None:
    text = request.lower()
    for mid, m in DEMO_MANAGERS.items():
        names = [m["name"], *m["aliases"]]
        if any(n.lower() in text for n in names if n):
            return {"manager_id": mid, "manager_name": m["name"], "has_13f": m["has_13f"],
                    "checks": list(CHECKS), "period": _period(today or date.today())}
    return None
