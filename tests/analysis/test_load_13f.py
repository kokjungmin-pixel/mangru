"""13F 데이터셋 읽기 테스트 (Data 문서 B5). 작은 가짜 압축 파일로 정정 규칙·단위·제외 규칙을 확인한다."""
import importlib.util
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("analysis_load_13f", ROOT / "scripts" / "analysis_load_13f.py")
L = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(L)


def tsv(header, rows):
    return "\t".join(header) + "\n" + "\n".join("\t".join(r) for r in rows) + "\n"


def make_zip(path, sub_rows, cover_rows, info_rows):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("SUBMISSION.tsv", tsv(["ACCESSION_NUMBER", "FILING_DATE", "SUBMISSIONTYPE", "CIK", "PERIODOFREPORT"], sub_rows))
        z.writestr("COVERPAGE.tsv", tsv(["ACCESSION_NUMBER", "REPORTCALENDARORQUARTER", "ISAMENDMENT", "AMENDMENTNO", "AMENDMENTTYPE"], cover_rows))
        z.writestr("INFOTABLE.tsv", tsv(["ACCESSION_NUMBER", "INFOTABLE_SK", "NAMEOFISSUER", "CUSIP", "VALUE", "SSHPRNAMT", "SSHPRNAMTTYPE", "PUTCALL"], info_rows))


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "DATA_DIR", tmp_path)
    monkeypatch.setattr(L, "QUARTER_CACHE", tmp_path / "quarters")
    # 파일 1: 2025Q3 원본들
    make_zip(tmp_path / "01sep2025-30nov2025_form13f.zip",
             sub_rows=[
                 ["A1", "14-NOV-2025", "13F-HR", "0000000111", "30-SEP-2025"],   # 운용사 111 원본
                 ["A2", "14-NOV-2025", "13F-HR", "0000000222", "30-SEP-2025"],   # 운용사 222 원본
                 ["A3", "20-NOV-2025", "13F-HR/A", "0000000222", "30-SEP-2025"],  # 222 추가 정정 → 무시
                 ["A9", "14-AUG-2025", "13F-HR", "0000000111", "30-JUN-2025"],   # 다른 분기
                 ["N1", "14-NOV-2025", "13F-NT", "0000000333", "30-SEP-2025"],   # 보유 없음 신고
             ],
             cover_rows=[["A1", "30-SEP-2025", "N", "", ""], ["A2", "30-SEP-2025", "N", "", ""],
                         ["A3", "30-SEP-2025", "Y", "1", "NEW HOLDINGS"], ["A9", "30-JUN-2025", "N", "", ""],
                         ["N1", "30-SEP-2025", "N", "", ""]],
             info_rows=[
                 ["A1", "1", "X", "037833100", "1000", "10", "SH", ""],
                 ["A1", "2", "X", "037833100", "500", "5", "SH", ""],          # 같은 CUSIP → 합산
                 ["A1", "3", "X", "037833100", "300", "3", "SH", "Put"],       # 옵션 → 제외
                 ["A1", "4", "X", "912828XX1", "900", "900", "PRN", ""],       # 원금 → 제외
                 ["A2", "1", "Y", "594918104", "2000", "20", "SH", ""],
                 ["A3", "1", "Y", "023135106", "7777", "7", "SH", ""],
                 ["A9", "1", "X", "037833100", "1", "1", "SH", ""],
             ])
    # 파일 2: 다음 시기에 들어온 111 의 전체 대체 정정 → 이걸 써야 함
    make_zip(tmp_path / "01dec2025-28feb2026_form13f.zip",
             sub_rows=[["R1", "05-DEC-2025", "13F-HR/A", "0000000111", "30-SEP-2025"]],
             cover_rows=[["R1", "30-SEP-2025", "Y", "1", "RESTATEMENT"]],
             info_rows=[["R1", "1", "X", "037833100", "1600", "16", "SH", ""]])
    return tmp_path


def test_load_quarter_rules(data):
    df = L.load_quarter("2025Q3", use_cache=False)
    assert list(df.columns) == L.OUT_COLS
    rows = {(r.CIK, r.CUSIP): (r.VALUE_USD, r.SSHPRNAMT) for r in df.itertuples()}
    assert rows == {("111", "037833100"): (1600.0, 16.0),     # RESTATEMENT 정정본
                    ("222", "594918104"): (2000.0, 20.0)}     # 원본 (NEW HOLDINGS 무시)
    assert set(df["PERIODOFREPORT"]) == {"2025-09-30"}


def test_original_used_when_no_restatement(data):
    (data / "01dec2025-28feb2026_form13f.zip").unlink()
    df = L.load_quarter("2025Q3", use_cache=False)
    row = df[(df.CIK == "111")].iloc[0]
    assert row.VALUE_USD == 1500.0 and row.SSHPRNAMT == 15.0  # 옵션·원금 빼고 같은 CUSIP 합산


def test_old_filings_in_thousands(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "DATA_DIR", tmp_path)
    monkeypatch.setattr(L, "QUARTER_CACHE", tmp_path / "quarters")
    make_zip(tmp_path / "2022q4_form13f.zip",
             sub_rows=[["B1", "14-NOV-2022", "13F-HR", "0000000444", "30-SEP-2022"]],
             cover_rows=[["B1", "30-SEP-2022", "N", "", ""]],
             info_rows=[["B1", "1", "Z", "037833100", "5", "100", "SH", ""]])
    df = L.load_quarter("2022Q3", use_cache=False)
    assert df.iloc[0].VALUE_USD == 5000.0


def test_cache_roundtrip(data):
    first = L.load_quarter("2025Q3")
    assert (data / "quarters" / "2025Q3.pkl").exists()
    assert L.load_quarter("2025Q3").equals(first)


def test_period_end_and_file_order():
    assert str(L.period_end("2025q3").date()) == "2025-09-30"
    names = ["01dec2024-28feb2025_form13f.zip", "2023q3_form13f.zip", "2024q1_form13f.zip", "2022q4_form13f.zip"]
    picked = [n for n, _ in L.wanted([(n, "u") for n in names])]
    assert picked == ["2023q3_form13f.zip", "2024q1_form13f.zip", "01dec2024-28feb2025_form13f.zip"]
