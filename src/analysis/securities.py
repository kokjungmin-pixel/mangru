"""종목 식별 — enrich_cusips (Data · 김지유, Data 문서 B3-1).

CUSIP 목록 → 종목마다 {"ticker", "issuer_cik", "sic", "shares_outstanding",
"shares_outstanding_partial", "is_etf"}.

단계
  ① OpenFIGI: CUSIP → 티커·종목 유형 (이 파일에서 requests 로 직접 부른다. CONTRACT A12-11)
  ② 결과가 여러 개면 exchCode == "US" 를 먼저, 없으면 첫 번째
  ③ 종목 유형으로 ETF·예탁증서 판별 (값은 docs/verified.md 에서 확인한 것만 쓴다)
  ④ 티커 → 발행사 CIK   (SEC company_tickers.json, sec_get)
  ⑤ CIK → 업종 SIC       (SEC submissions, sec_get)
  ⑥ 발행주식 수           (SEC XBRL companyconcept, sec_get). 예탁증서는 건너뛰고 None

규칙
- 절대 예외를 던지지 않는다. 단계가 실패하면 그 값만 None 으로 두고 다음 종목으로 간다.
- 실패 내역은 data_cache/raw/enrich_log.jsonl 에 한 줄씩 (CUSIP, 단계, 사유).
- 찾은 결과는 data_cache/demo/security_master.json 에 저장하고 다시 묻지 않는다.
  티커·CIK·SIC·유형은 CUSIP별, 발행주식 수는 "CUSIP|분기 말일" 별.
  응답을 아예 못 받은 단계(네트워크 실패)가 섞인 종목은 저장하지 않고 다음 호출 때 다시 묻는다.
"""
import json
import logging
import os
import time
from datetime import date, datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

from src.collect.sec_client import sec_get
from src.config import DEMO_DIR, RAW_DIR, ROOT, SHARES_OUT_MAX_GAP_DAYS

log = logging.getLogger(__name__)

# ---------- 주소와 파일 ----------
OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_CONCEPT_URL = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/{taxonomy}/{tag}.json"
# 발행주식 수: 위에서부터 차례로 보고, as_of 근처 값이 있는 첫 항목을 쓴다.
# 주식 종류가 여러 개인 회사(Mastercard·Datadog 등)는 앞의 두 항목이 종류별로만 보고돼 비어 있다
# (2026-11-23 확인, docs/verified.md). 그때는 전체 주식의 분기 가중평균 주식 수로 대신한다.
SHARES_CONCEPTS = (("dei", "EntityCommonStockSharesOutstanding", "point"),
                   ("us-gaap", "CommonStockSharesOutstanding", "point"),
                   ("us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", "average"))

MASTER_PATH: Path = DEMO_DIR / "security_master.json"
LOG_PATH: Path = RAW_DIR / "enrich_log.jsonl"

# ---------- OpenFIGI 한도 (Data 문서 B3-1 ①) ----------
BATCH_WITH_KEY, BATCH_NO_KEY = 100, 10          # 요청 하나에 넣는 CUSIP 수
INTERVAL_WITH_KEY, INTERVAL_NO_KEY = 0.25, 2.5  # 요청 사이 간격(초): 분당 250회 / 25회
WAIT_ON_429_SEC = 60
MAX_ATTEMPTS = 3
TIMEOUT_SEC = 30

# ---------- ③ 종목 유형 판별 ----------
# OpenFIGI 결과의 securityType 또는 securityType2 가 아래 값이면 ETF / 예탁증서로 본다.
# 2026-11-17 실제 조회로 확인 (scripts/analysis_openfigi_probe.py, docs/verified.md):
#   SPY  78462F103 → securityType "ETP",          securityType2 "Mutual Fund"
#   AAPL 037833100 → securityType "Common Stock", securityType2 "Common Stock"
#   TSM  874039100 → securityType "ADR",          securityType2 "Depositary Receipt"
# "Mutual Fund" 는 ETF 외의 펀드에도 붙을 수 있어 ETF 판별에는 securityType "ETP" 만 쓴다.
ETF_TYPES = {"ETP"}
ADR_TYPES = {"ADR", "Depositary Receipt"}

EMPTY = {"ticker": None, "issuer_cik": None, "sic": None, "shares_outstanding": None,
         "shares_outstanding_partial": False, "is_etf": False}

# 테스트에서 바꿔 끼울 수 있게 모듈 속성으로 둔다
_sleep = time.sleep
_post = requests.post


# ======================================================================
# 공개 함수
# ======================================================================
def enrich_cusips(cusips: list[str], as_of: str) -> dict[str, dict]:
    """CUSIP 목록 → {CUSIP: 종목 정보}. 못 찾은 값은 None. 절대 예외를 던지지 않는다.
    as_of 는 분기 말일 "YYYY-MM-DD" (발행주식 수를 고르는 기준)."""
    try:
        return _enrich(cusips, as_of)
    except Exception as e:  # 마지막 안전장치: 어떤 경우에도 부른 쪽이 멈추지 않게
        log.exception("enrich_cusips 예상 못 한 오류")
        _log_failure("*", "enrich", f"예상 못 한 오류({type(e).__name__})")
        try:
            return {c: dict(EMPTY) for c in _clean_cusips(cusips)}
        except Exception:
            return {}


def is_etf_by_name(issuer_name: str | None) -> bool:
    """OpenFIGI 로 유형을 못 찾았을 때의 대체 규칙: 종목명에 단어 ETF 가 있으면 ETF (B3-1 ③)."""
    if not issuer_name:
        return False
    words = issuer_name.upper().replace("-", " ").replace(".", " ").replace(",", " ").split()
    return "ETF" in words


def pick_shares_outstanding(facts: list[dict], as_of: str):
    """XBRL companyconcept 응답의 units["shares"] 목록 → (값, partial).
    as_of 와 기준일(end) 차이가 SHARES_OUT_MAX_GAP_DAYS 이내인 것 중 가장 가까운 날짜.
    그 날짜에 서로 다른 값이 여러 개면 주식 종류별 값으로 보고 가장 큰 값을 '하한값'(partial=True)으로.
    (Data 문서 B3-1 코드 그대로)"""
    target = date.fromisoformat(as_of)
    by_end: dict[str, set] = {}
    for f in facts:
        try:
            gap = abs((date.fromisoformat(f["end"]) - target).days)
            val = float(f["val"])
        except (KeyError, ValueError, TypeError):
            continue
        if gap <= SHARES_OUT_MAX_GAP_DAYS and val > 0:
            by_end.setdefault(f["end"], set()).add(val)
    if not by_end:
        return None, False
    end = min(by_end, key=lambda e: abs((date.fromisoformat(e) - target).days))
    vals = by_end[end]
    return (max(vals), len(vals) > 1)


def pick_weighted_average(facts: list[dict], as_of: str) -> float | None:
    """가중평균 주식 수(기간 값) 목록 → 값 하나.
    as_of 와 기간 끝(end) 차이가 SHARES_OUT_MAX_GAP_DAYS 이내인 것 중 end 가 가장 가까운 것,
    같은 end 가 여러 개면(3개월·9개월 누적 등) 기간이 가장 짧은 것(분기 값)을 쓴다."""
    target = date.fromisoformat(as_of)
    best = None
    for f in facts:
        try:
            end = date.fromisoformat(f["end"])
            start = date.fromisoformat(f["start"]) if f.get("start") else end
            val = float(f["val"])
        except (KeyError, ValueError, TypeError):
            continue
        gap = abs((end - target).days)
        if gap > SHARES_OUT_MAX_GAP_DAYS or val <= 0:
            continue
        rank = (gap, (end - start).days)
        if best is None or rank < best[0]:
            best = (rank, val)
    return best[1] if best else None


def openfigi_map(cusips: list[str], id_type: str = "ID_CUSIP") -> dict[str, dict | None]:
    """CUSIP → OpenFIGI 응답 한 줄({"data": [...]} 또는 {"warning": ...}/{"error": ...}).
    묶음이 끝내 실패하면 그 묶음의 CUSIP 은 None. 예외를 던지지 않는다.
    id_type: 보통 "ID_CUSIP". 영문자로 시작하는 해외 발행사 번호(CINS)는 "ID_CINS" 로 물어야 찾아진다."""
    key = _openfigi_key()
    size = BATCH_WITH_KEY if key else BATCH_NO_KEY
    interval = INTERVAL_WITH_KEY if key else INTERVAL_NO_KEY
    headers = {"Content-Type": "application/json"}
    if key:
        headers["X-OPENFIGI-APIKEY"] = key

    out: dict[str, dict | None] = {}
    for i in range(0, len(cusips), size):
        if i > 0:
            _sleep(interval)
        batch = cusips[i:i + size]
        rows = _post_batch(batch, headers, id_type)
        for j, c in enumerate(batch):
            row = rows[j] if rows is not None and j < len(rows) else None
            out[c] = row if isinstance(row, dict) else None
    return out


def choose_figi(row: dict | None) -> dict | None:
    """② OpenFIGI 응답 한 줄에서 쓸 결과 하나: exchCode == "US" 먼저, 없으면 첫 번째."""
    data = (row or {}).get("data") or []
    data = [d for d in data if isinstance(d, dict)]
    if not data:
        return None
    for d in data:
        if d.get("exchCode") == "US":
            return d
    return data[0]


def classify(figi: dict | None) -> str:
    """③ "etf" / "adr" / "stock". figi 가 없으면 "unknown"."""
    if not figi:
        return "unknown"
    types = {figi.get("securityType"), figi.get("securityType2")}
    if types & ETF_TYPES:
        return "etf"
    if types & ADR_TYPES:
        return "adr"
    return "stock"


def normalize_ticker(t: str | None) -> str | None:
    """OpenFIGI "BRK/B" ↔ SEC "BRK-B". 대문자로, / 는 - 로."""
    if not t:
        return None
    return t.strip().upper().replace("/", "-")


# ======================================================================
# 내부: 전체 흐름
# ======================================================================
def _enrich(cusips: list[str], as_of: str) -> dict[str, dict]:
    cusips = _clean_cusips(cusips)
    master = _load_master()
    saved_secs, saved_shares = master["securities"], master["shares_outstanding"]
    changed = False

    # ①~⑤ 저장본에 없는 CUSIP만 조회
    found: dict[str, dict] = {}
    todo = [c for c in cusips if c not in saved_secs]
    if todo:
        figi = openfigi_map(todo)
        # 영문자로 시작하는 해외 발행사 번호(CINS)는 ID_CUSIP 으로는 "없음" → ID_CINS 로 다시 묻는다
        cins = [c for c in todo if c[:1].isalpha() and figi.get(c) is not None and "data" not in figi[c]]
        if cins:
            figi.update({c: r for c, r in openfigi_map(cins, "ID_CINS").items() if r is not None})
        tickers = None                       # SEC 티커 목록은 필요할 때 한 번만 받는다
        for c in todo:
            rec, complete = _identify(c, figi.get(c))
            if rec["ticker"]:
                if tickers is None:
                    tickers = _load_sec_tickers()
                complete = _fill_cik_sic(c, rec, tickers) and complete
            found[c] = rec
            if complete:
                saved_secs[c] = rec
                changed = True

    # ⑥ 발행주식 수 + 결과 조립
    result = {}
    for c in cusips:
        rec = saved_secs.get(c) or found.get(c) or {}
        item = dict(EMPTY)
        item["ticker"] = rec.get("ticker")
        item["issuer_cik"] = rec.get("issuer_cik")
        item["sic"] = rec.get("sic")
        item["is_etf"] = bool(rec.get("is_etf"))

        so_key = f"{c}|{as_of}"
        if so_key in saved_shares:
            so = saved_shares[so_key]
        else:
            so = _shares_for(c, rec, as_of)
            if c in saved_secs:              # 종목 정보가 확정된 것만 저장
                saved_shares[so_key] = so
                changed = True
        item["shares_outstanding"] = so["value"]
        item["shares_outstanding_partial"] = bool(so["partial"])
        result[c] = item

    if changed:
        _save_master(master)
    return result


def _identify(cusip: str, row: dict | None) -> tuple[dict, bool]:
    """①~③. (종목 기록, 응답을 제대로 받았는가)."""
    rec = {"ticker": None, "issuer_cik": None, "sic": None, "is_etf": False, "is_adr": False,
           "name": None, "security_type": None, "security_type2": None}
    if row is None:
        _log_failure(cusip, "openfigi", "응답 없음(요청 실패)")
        return rec, False
    if "data" not in row:
        reason = row.get("warning") or row.get("error") or "결과 없음"
        _log_failure(cusip, "openfigi", str(reason)[:200])
        return rec, True                     # OpenFIGI 가 "없다"고 답한 것은 확정된 결과
    figi = choose_figi(row)
    if figi is None:
        _log_failure(cusip, "openfigi", "data 가 비어 있음")
        return rec, True
    kind = classify(figi)
    rec.update(ticker=figi.get("ticker") or None, name=figi.get("name"),
               security_type=figi.get("securityType"), security_type2=figi.get("securityType2"),
               is_etf=(kind == "etf"), is_adr=(kind == "adr"))
    if not rec["ticker"]:
        _log_failure(cusip, "openfigi", "티커 없음")
    return rec, True


def _fill_cik_sic(cusip: str, rec: dict, tickers: dict | None) -> bool:
    """④⑤. rec 를 채운다. 응답을 제대로 받았으면 True."""
    if tickers is None:
        _log_failure(cusip, "cik", "SEC 티커 목록을 못 받음")
        return False
    cik = tickers.get(normalize_ticker(rec["ticker"]))
    if cik is None:
        _log_failure(cusip, "cik", f"SEC 티커 목록에 없음({rec['ticker']})")
        return True
    rec["issuer_cik"] = cik

    sub = _safe_sec_get(SEC_SUBMISSIONS_URL.format(cik=cik))
    if not isinstance(sub, dict):
        _log_failure(cusip, "sic", "submissions 응답 없음")
        return False
    sic = str(sub.get("sic") or "").strip()
    rec["sic"] = sic or None
    if not sic:
        _log_failure(cusip, "sic", "sic 비어 있음")
    return True


def _shares_for(cusip: str, rec: dict, as_of: str) -> dict:
    """⑥ {"value": float|None, "partial": bool}. 예탁증서·ETF·CIK 없음은 조회하지 않는다."""
    none = {"value": None, "partial": False}
    if rec.get("is_adr"):
        return none                           # 예탁증서 1주 ≠ 원주 1주 → 시가총액이 틀어진다
    if rec.get("is_etf") or not rec.get("issuer_cik"):
        return none
    try:
        date.fromisoformat(as_of)
    except (TypeError, ValueError):
        _log_failure(cusip, "shares", f"as_of 형식 오류({as_of!r})")
        return none

    for taxonomy, tag, kind in SHARES_CONCEPTS:
        resp = _safe_sec_get(SEC_CONCEPT_URL.format(cik=rec["issuer_cik"], taxonomy=taxonomy, tag=tag))
        if resp is None:
            continue                          # 404(그 항목 없음) → 다음 항목
        facts = ((resp or {}).get("units") or {}).get("shares") or []
        if kind == "point":
            value, partial = pick_shares_outstanding(facts, as_of)
        else:
            value, partial = pick_weighted_average(facts, as_of), False
        if value is not None:
            return {"value": value, "partial": partial}
    _log_failure(cusip, "shares", f"XBRL 발행주식 수: {as_of} ±{SHARES_OUT_MAX_GAP_DAYS}일 안의 값 없음")
    return none


# ======================================================================
# 내부: 네트워크
# ======================================================================
def _openfigi_key() -> str | None:
    load_dotenv(ROOT / ".env", override=False)
    return os.getenv("OPENFIGI_API_KEY", "").strip() or None


def _post_batch(batch: list[str], headers: dict, id_type: str = "ID_CUSIP") -> list | None:
    """OpenFIGI 요청 한 번(최대 3회 시도). 응답 목록 또는 None."""
    body = [{"idType": id_type, "idValue": c} for c in batch]
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = _post(OPENFIGI_URL, json=body, headers=headers, timeout=TIMEOUT_SEC)
        except requests.RequestException as e:
            reason, wait = f"연결 오류({type(e).__name__})", 2
        else:
            if resp.status_code == 200:
                try:
                    rows = resp.json()
                except ValueError:
                    rows = None
                if isinstance(rows, list):
                    return rows
                reason, wait = "응답이 목록이 아님", 2
            elif resp.status_code == 429:
                reason, wait = "HTTP 429(요청 과다)", WAIT_ON_429_SEC
            else:
                reason, wait = f"HTTP {resp.status_code}", 2
        log.warning("OpenFIGI 실패 %d/%d: %s", attempt, MAX_ATTEMPTS, reason)
        if attempt < MAX_ATTEMPTS:
            _sleep(wait)
    for c in batch:
        _log_failure(c, "openfigi", f"{MAX_ATTEMPTS}회 실패")
    return None


def _safe_sec_get(url: str):
    try:
        return sec_get(url, "json")
    except Exception as e:  # sec_get 은 예외를 안 던지기로 했지만 혹시 몰라
        log.warning("sec_get 예외(%s): %s", type(e).__name__, url)
        return None


def _load_sec_tickers() -> dict[str, str] | None:
    """④ SEC company_tickers.json → {티커(대문자, - 형식): CIK 10자리}."""
    data = _safe_sec_get(SEC_TICKERS_URL)
    if not isinstance(data, dict):
        return None
    out = {}
    for row in data.values():
        try:
            t = normalize_ticker(row["ticker"])
            out.setdefault(t, f"{int(row['cik_str']):010d}")
        except (KeyError, TypeError, ValueError):
            continue
    return out


# ======================================================================
# 내부: 파일
# ======================================================================
def _clean_cusips(cusips) -> list[str]:
    """대문자·공백 제거, 중복 제거(순서 유지)."""
    out = []
    for c in cusips or []:
        if isinstance(c, str) and c.strip():
            c = c.strip().upper()
            if c not in out:
                out.append(c)
    return out


def _load_master() -> dict:
    try:
        m = json.loads(MASTER_PATH.read_text(encoding="utf-8"))
        if isinstance(m, dict):
            m.setdefault("securities", {})
            m.setdefault("shares_outstanding", {})
            return m
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as e:
        log.warning("security_master.json 을 못 읽어 새로 만듦(%s)", type(e).__name__)
    return {"securities": {}, "shares_outstanding": {}}


def _save_master(master: dict) -> None:
    try:
        MASTER_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = MASTER_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(master, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        tmp.replace(MASTER_PATH)
    except OSError as e:
        log.warning("security_master.json 저장 실패(%s)", type(e).__name__)


def _log_failure(cusip: str, step: str, reason: str) -> None:
    line = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "cusip": cusip, "step": step, "reason": reason}
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    except OSError:
        log.warning("enrich_log 기록 실패: %s", line)
