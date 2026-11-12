"""종목 식별 — enrich_cusips (Data · 김지유, 11/15~18)
TODO(김지유): OpenFIGI → CIK → SIC → XBRL 발행주식 수. 지금은 모든 값이 None인 가짜.
절대 예외를 던지지 않는다.
"""

EMPTY = {"ticker": None, "issuer_cik": None, "sic": None, "shares_outstanding": None,
         "shares_outstanding_partial": False, "is_etf": False}


def enrich_cusips(cusips: list[str], as_of: str) -> dict[str, dict]:
    return {c: dict(EMPTY) for c in cusips}
