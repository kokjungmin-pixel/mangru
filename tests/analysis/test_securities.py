"""enrich_cusips 테스트 (Data 문서 B3-1). 네트워크는 쓰지 않는다: OpenFIGI·SEC 응답을 가짜로 바꾼다."""
import json

import pytest

from src.analysis import securities as sec

AAPL, SPY, TSM, BRK = "037833100", "78462F103", "874039100", "084670702"
AS_OF = "2026-06-30"

SEC_TICKERS = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 1067983, "ticker": "BRK-B", "title": "BERKSHIRE HATHAWAY INC"},
    "2": {"cik_str": 1046179, "ticker": "TSM", "title": "TAIWAN SEMICONDUCTOR"},
}
FIGI = {
    AAPL: {"data": [{"ticker": "AAPL", "exchCode": "UW", "securityType": "Common Stock"},
                    {"ticker": "AAPL", "exchCode": "US", "securityType": "Common Stock", "name": "APPLE INC"}]},
    SPY: {"data": [{"ticker": "SPY", "exchCode": "US", "securityType": "ETP"}]},
    TSM: {"data": [{"ticker": "TSM", "exchCode": "US", "securityType": "ADR"}]},
    BRK: {"data": [{"ticker": "BRK/B", "exchCode": "US", "securityType": "Common Stock"}]},
}


class FakeResp:
    def __init__(self, status, rows=None):
        self.status_code = status
        self._rows = rows

    def json(self):
        return self._rows


class Net:
    """가짜 OpenFIGI(_post)·SEC(sec_get). 호출 기록을 남긴다."""

    def __init__(self, figi=None, sec_pages=None, figi_status=200):
        self.figi = FIGI if figi is None else figi
        self.figi_status = figi_status
        self.sec_pages = sec_pages if sec_pages is not None else {}
        self.figi_calls = []
        self.figi_types = []
        self.sec_calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.figi_calls.append([j["idValue"] for j in json])
        self.figi_types.append({j["idType"] for j in json})
        if self.figi_status != 200:
            return FakeResp(self.figi_status)
        return FakeResp(200, [self.figi.get((j["idType"], j["idValue"]),
                                            self.figi.get(j["idValue"], {"warning": "No identifier found."}))
                              for j in json])

    def sec_get(self, url, kind="json"):
        self.sec_calls.append(url)
        return self.sec_pages.get(url)          # 없으면 None (= 404)


def sub_url(cik):
    return sec.SEC_SUBMISSIONS_URL.format(cik=cik)


def concept_url(cik, taxonomy, tag):
    return sec.SEC_CONCEPT_URL.format(cik=cik, taxonomy=taxonomy, tag=tag)


def default_pages():
    return {
        sec.SEC_TICKERS_URL: SEC_TICKERS,
        sub_url("0000320193"): {"sic": "3571"},
        sub_url("0001067983"): {"sic": "6331"},
        sub_url("0001046179"): {"sic": "3674"},
        concept_url("0000320193", "dei", "EntityCommonStockSharesOutstanding"):
            {"units": {"shares": [{"end": "2026-07-18", "val": 14_800_000_000}]}},
    }


@pytest.fixture
def net(tmp_path, monkeypatch):
    n = Net(sec_pages=default_pages())
    monkeypatch.setattr(sec, "MASTER_PATH", tmp_path / "security_master.json")
    monkeypatch.setattr(sec, "LOG_PATH", tmp_path / "enrich_log.jsonl")
    monkeypatch.setattr(sec, "_post", n.post)
    monkeypatch.setattr(sec, "sec_get", n.sec_get)
    monkeypatch.setattr(sec, "_sleep", lambda s: None)
    monkeypatch.setattr(sec, "_openfigi_key", lambda: None)
    return n


def log_lines():
    if not sec.LOG_PATH.exists():
        return []
    return [json.loads(x) for x in sec.LOG_PATH.read_text(encoding="utf-8").splitlines()]


# ---------- B3-1 테스트 목록 ----------
def test_second_call_uses_cache_no_network(net):
    first = sec.enrich_cusips([AAPL], AS_OF)
    assert first[AAPL]["ticker"] == "AAPL"
    assert first[AAPL]["issuer_cik"] == "0000320193"
    assert first[AAPL]["sic"] == "3571"
    assert first[AAPL]["shares_outstanding"] == 14_800_000_000
    assert first[AAPL]["is_etf"] is False

    figi_before, sec_before = len(net.figi_calls), len(net.sec_calls)
    second = sec.enrich_cusips([AAPL], AS_OF)
    assert second == first
    assert len(net.figi_calls) == figi_before
    assert len(net.sec_calls) == sec_before


def test_warning_and_404_give_none_without_exception(net):
    net.sec_pages.pop(sub_url("0000320193"))     # SEC 404
    out = sec.enrich_cusips([AAPL, "000000000"], AS_OF)
    assert out["000000000"] == sec.EMPTY          # OpenFIGI warning → 전부 None
    assert out[AAPL]["ticker"] == "AAPL"
    assert out[AAPL]["sic"] is None
    steps = {(x["cusip"], x["step"]) for x in log_lines()}
    assert ("000000000", "openfigi") in steps
    assert (AAPL, "sic") in steps


def test_brk_slash_ticker_matches_sec_dash(net):
    out = sec.enrich_cusips([BRK], AS_OF)
    assert out[BRK]["ticker"] == "BRK/B"
    assert out[BRK]["issuer_cik"] == "0001067983"


def test_pick_shares_outstanding_two_values_same_date():
    facts = [{"end": "2026-06-30", "val": 150}, {"end": "2026-06-30", "val": 90}]
    assert sec.pick_shares_outstanding(facts, AS_OF) == (150, True)


def test_pick_shares_outstanding_outside_120_days():
    facts = [{"end": "2026-01-31", "val": 100}, {"end": "2026-12-31", "val": 100}]
    assert sec.pick_shares_outstanding(facts, AS_OF) == (None, False)


def test_adr_skips_shares_lookup(net):
    out = sec.enrich_cusips([TSM], AS_OF)
    assert out[TSM]["shares_outstanding"] is None
    assert out[TSM]["issuer_cik"] == "0001046179"
    assert not any("companyconcept" in u for u in net.sec_calls)


def test_etf_by_name_when_openfigi_fails():
    assert sec.is_etf_by_name("SPDR S&P 500 ETF TR") is True
    assert sec.is_etf_by_name("ISHARES TR CORE S&P ETF") is True
    assert sec.is_etf_by_name("APPLE INC") is False
    assert sec.is_etf_by_name("NETFLIX INC") is False     # 단어 안에 ETF 가 있어도 아님
    assert sec.is_etf_by_name(None) is False


# ---------- 추가 확인 ----------
def test_etf_flag_and_no_shares_lookup(net):
    out = sec.enrich_cusips([SPY], AS_OF)
    assert out[SPY]["is_etf"] is True
    assert out[SPY]["shares_outstanding"] is None


def test_openfigi_down_returns_none_and_is_not_cached(net):
    net.figi_status = 500
    out = sec.enrich_cusips([AAPL], AS_OF)
    assert out[AAPL] == sec.EMPTY
    assert len(net.figi_calls) == sec.MAX_ATTEMPTS          # 3회 시도
    net.figi_status = 200                                   # 다음 호출 때는 다시 묻는다
    assert sec.enrich_cusips([AAPL], AS_OF)[AAPL]["ticker"] == "AAPL"


def test_429_waits_one_minute(net, monkeypatch):
    waits = []
    monkeypatch.setattr(sec, "_sleep", waits.append)
    net.figi_status = 429
    sec.enrich_cusips([AAPL], AS_OF)
    assert waits == [sec.WAIT_ON_429_SEC, sec.WAIT_ON_429_SEC]


def test_batches_of_10_without_key(net):
    cusips = [f"{i:09d}" for i in range(1, 26)]
    sec.enrich_cusips(cusips, AS_OF)
    assert [len(b) for b in net.figi_calls] == [10, 10, 5]


def test_us_exchange_preferred():
    row = {"data": [{"exchCode": "UN", "ticker": "X1"}, {"exchCode": "US", "ticker": "X2"}]}
    assert sec.choose_figi(row)["ticker"] == "X2"
    assert sec.choose_figi({"data": [{"exchCode": "UN", "ticker": "X1"}]})["ticker"] == "X1"


def test_us_gaap_fallback_when_dei_missing(net):
    net.sec_pages.pop(concept_url("0000320193", "dei", "EntityCommonStockSharesOutstanding"))
    net.sec_pages[concept_url("0000320193", "us-gaap", "CommonStockSharesOutstanding")] = {
        "units": {"shares": [{"end": "2026-06-27", "val": 14_900_000_000}]}}
    assert sec.enrich_cusips([AAPL], AS_OF)[AAPL]["shares_outstanding"] == 14_900_000_000


def test_never_raises_on_bad_input(net, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(sec, "openfigi_map", boom)
    assert sec.enrich_cusips([AAPL], AS_OF) == {AAPL: sec.EMPTY}
    assert sec.enrich_cusips(None, AS_OF) == {}
    assert sec.enrich_cusips([AAPL], "잘못된날짜")[AAPL]["ticker"] is None


def test_return_shape_matches_contract(net):
    out = sec.enrich_cusips([AAPL, SPY], AS_OF)
    for v in out.values():
        assert set(v) == set(sec.EMPTY)


# ---------- 2026-11-23: 해외 발행사 번호, 주식 종류가 여러 개인 회사 ----------
CAMT = "M20791105"


def test_foreign_cins_retried_with_id_cins(net):
    net.figi = dict(FIGI)
    net.figi[("ID_CINS", CAMT)] = {"data": [{"ticker": "CAMT", "exchCode": "US", "securityType": "Common Stock"}]}
    net.sec_pages[sec.SEC_TICKERS_URL] = {**SEC_TICKERS, "9": {"cik_str": 1109138, "ticker": "CAMT", "title": "CAMTEK"}}
    out = sec.enrich_cusips([CAMT, AAPL], AS_OF)
    assert out[CAMT]["ticker"] == "CAMT"
    assert out[CAMT]["issuer_cik"] == "0001109138"
    assert net.figi_types[-1] == {"ID_CINS"}
    assert net.figi_calls[-1] == [CAMT]                     # 숫자로 시작하는 AAPL 은 다시 묻지 않음


def test_numeric_cusip_not_retried_as_cins(net):
    sec.enrich_cusips(["000000000"], AS_OF)
    assert all(t == {"ID_CUSIP"} for t in net.figi_types)


def test_multi_class_uses_weighted_average_quarter(net):
    cik = "0000320193"
    net.sec_pages[concept_url(cik, "dei", "EntityCommonStockSharesOutstanding")] = {
        "units": {"shares": [{"end": "2010-10-27", "val": 1}]}}          # 오래된 값만 있음
    net.sec_pages[concept_url(cik, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic")] = {
        "units": {"shares": [
            {"start": "2026-01-01", "end": "2026-06-30", "val": 890},     # 6개월 누적
            {"start": "2026-04-01", "end": "2026-06-30", "val": 883},     # 분기 → 이것
            {"start": "2025-04-01", "end": "2025-06-30", "val": 900},
        ]}}
    out = sec.enrich_cusips([AAPL], AS_OF)[AAPL]
    assert out["shares_outstanding"] == 883
    assert out["shares_outstanding_partial"] is False


def test_pick_weighted_average_outside_window():
    facts = [{"start": "2025-10-01", "end": "2025-12-31", "val": 5}]
    assert sec.pick_weighted_average(facts, AS_OF) is None
