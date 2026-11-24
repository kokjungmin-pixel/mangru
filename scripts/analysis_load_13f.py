"""13F 데이터셋 적재 (Data · 김지유, Data 문서 B5 "데이터").

SEC "Form 13F Data Sets"(제출 시기별 압축 파일, 탭 구분)을 data_cache/raw/13f/ 에 받아 두고,
load_quarter(period) 로 한 보고 분기의 전체 운용사 보유 내역을 돌려준다.

명령 (PowerShell, mangru 폴더에서):
  python scripts/analysis_load_13f.py list              # 내려받을 수 있는 파일 목록
  python scripts/analysis_load_13f.py download          # 2023년 3분기 제출분부터 전부 받기 (파일당 50~95MB)
  python scripts/analysis_load_13f.py inspect           # 받은 파일의 표·열 이름·값 모양 확인 (verified.md 용)
  python scripts/analysis_load_13f.py quarter 2025Q3    # 한 분기 읽어 보고 Akre·Brown 과 맞춰 보기

규칙 (Data 문서 B5)
- 분기는 파일 이름이 아니라 SUBMISSION.PERIODOFREPORT(보고 기준일)로 나눈다.
- VALUE 는 FILING_DATE 가 2023-01-03 이후면 달러, 그 전이면 천 달러(×1000).
- 한 운용사·한 보고 분기에 제출이 여러 개면: 전체 대체 정정(RESTATEMENT)이 있으면 가장 늦은 것,
  없으면 원본(가장 늦은 원본). 추가 정정(NEW HOLDINGS)은 반영하지 않는다.
- 옵션(PUTCALL 있음)·원금(SSHPRNAMTTYPE 이 SH 가 아님) 행은 뺀다. 같은 운용사·CUSIP 은 합친다.
"""
from __future__ import annotations

import io
import re
import sys
import zipfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import RAW_DIR  # noqa: E402

LANDING_PAGES = ("https://www.sec.gov/about/dera_form-13f",
                 "https://www.sec.gov/dera/data/form-13f")
SEC_BASE = "https://www.sec.gov"
DATA_DIR: Path = RAW_DIR / "13f"
QUARTER_CACHE: Path = DATA_DIR / "quarters"
FIRST_FILE = "2023q3"            # 2023Q2 보고분이 제출된 시기부터
VALUE_IN_DOLLARS_FROM = pd.Timestamp("2023-01-03")

SUB_COLS = ["ACCESSION_NUMBER", "FILING_DATE", "SUBMISSIONTYPE", "CIK", "PERIODOFREPORT"]
COVER_COLS = ["ACCESSION_NUMBER", "ISAMENDMENT", "AMENDMENTTYPE"]
INFO_COLS = ["ACCESSION_NUMBER", "CUSIP", "VALUE", "SSHPRNAMT", "SSHPRNAMTTYPE", "PUTCALL"]
OUT_COLS = ["CIK", "PERIODOFREPORT", "CUSIP", "VALUE_USD", "SSHPRNAMT"]


# ======================================================================
# 내려받기
# ======================================================================
def list_files() -> list[tuple[str, str]]:
    """안내 페이지에서 (파일 이름, 전체 주소) 목록. 최신이 앞."""
    from src.collect.sec_client import sec_get
    for page in LANDING_PAGES:
        html = sec_get(page, "bytes", refresh=True)
        if not html:
            continue
        links = re.findall(r'href="([^"]*?form13f\.zip)"', html.decode("utf-8", "replace"), flags=re.I)
        out, seen = [], set()
        for href in links:
            url = href if href.startswith("http") else SEC_BASE + href
            name = url.rsplit("/", 1)[-1]
            if name not in seen:
                seen.add(name)
                out.append((name, url))
        if out:
            return out
    return []


def _sort_key(name: str) -> tuple[int, int]:
    """파일 이름 → (연, 월) 대략값. 2023q3_form13f.zip / 01dec2024-28feb2025_form13f.zip 둘 다."""
    m = re.match(r"(\d{4})q(\d)", name)
    if m:
        return int(m.group(1)), int(m.group(2)) * 3
    months = "jan feb mar apr may jun jul aug sep oct nov dec".split()
    m = re.match(r"\d{2}([a-z]{3})(\d{4})", name.lower())
    if m and m.group(1) in months:
        return int(m.group(2)), months.index(m.group(1)) + 1
    return 0, 0


def wanted(files: list[tuple[str, str]]) -> list[tuple[str, str]]:
    start = _sort_key(FIRST_FILE)
    return sorted([f for f in files if _sort_key(f[0]) >= start], key=lambda f: _sort_key(f[0]))


def download() -> None:
    from src.collect import sec_client
    files = wanted(list_files())
    if not files:
        print("목록을 못 받음. .env 의 SEC_CONTACT_EMAIL 과 인터넷 연결을 확인")
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"받을 파일 {len(files)}개 → {DATA_DIR}")
    for i, (name, url) in enumerate(files, 1):
        target = DATA_DIR / name
        if target.exists() and zipfile.is_zipfile(target):
            print(f"  [{i}/{len(files)}] {name} 이미 있음")
            continue
        print(f"  [{i}/{len(files)}] {name} 받는 중...", end="", flush=True)
        body = sec_client.sec_get(url, "bytes")
        if not body:
            print(" 실패 (다시 실행하면 이어서 받음)")
            continue
        target.write_bytes(body)
        try:                                   # sec_get 이 남긴 같은 내용의 저장본은 지운다(용량 두 배 방지)
            sec_client._cache_path(url).unlink(missing_ok=True)
        except Exception:
            pass
        print(f" {len(body) / 1e6:.0f}MB")


def local_zips() -> list[Path]:
    return sorted(DATA_DIR.glob("*form13f.zip"), key=lambda p: _sort_key(p.name))


# ======================================================================
# 읽기
# ======================================================================
def _member(z: zipfile.ZipFile, table: str) -> str | None:
    for n in z.namelist():
        base = n.rsplit("/", 1)[-1].upper()
        if base.startswith(table.upper() + ".") or base == table.upper():
            return n
    return None


def _read(z: zipfile.ZipFile, table: str, cols: list[str], **kw) -> pd.DataFrame:
    name = _member(z, table)
    if name is None:
        return pd.DataFrame(columns=cols)
    with z.open(name) as f:
        return pd.read_csv(io.TextIOWrapper(f, encoding="utf-8", errors="replace"), sep="\t",
                           usecols=lambda c: c in cols, dtype=str, quoting=3, keep_default_na=False, **kw)


def _read_chunks(z: zipfile.ZipFile, table: str, cols: list[str], size: int = 500_000):
    """큰 표(INFOTABLE)를 나눠 읽는다. 파일을 연 채로 한 덩어리씩 돌려준다."""
    name = _member(z, table)
    if name is None:
        return
    with z.open(name) as f:
        reader = pd.read_csv(io.TextIOWrapper(f, encoding="utf-8", errors="replace"), sep="\t",
                             usecols=lambda c: c in cols, dtype=str, quoting=3, keep_default_na=False,
                             chunksize=size)
        yield from reader


def _dates(s: pd.Series) -> pd.Series:
    d = pd.to_datetime(s, format="%d-%b-%Y", errors="coerce")
    if d.isna().all() and len(s):
        d = pd.to_datetime(s, errors="coerce")
    return d


def period_end(period: str) -> pd.Timestamp:
    """"2025Q3" → 2025-09-30."""
    m = re.fullmatch(r"(\d{4})Q([1-4])", period.strip().upper())
    if not m:
        raise ValueError(f"분기 형식은 2025Q3 처럼: {period!r}")
    return pd.Period(f"{m.group(1)}Q{m.group(2)}", freq="Q").end_time.normalize()


def choose_filings(sub: pd.DataFrame, cover: pd.DataFrame) -> pd.DataFrame:
    """운용사(CIK)마다 쓸 제출 하나: RESTATEMENT 정정이 있으면 가장 늦은 것, 없으면 가장 늦은 원본."""
    s = sub[sub["SUBMISSIONTYPE"].str.upper().isin(["13F-HR", "13F-HR/A"])].copy()
    s = s.merge(cover, on="ACCESSION_NUMBER", how="left")
    is_amend = (s["SUBMISSIONTYPE"].str.upper() == "13F-HR/A") | (s["ISAMENDMENT"].fillna("").str.upper() == "Y")
    s["kind"] = "original"
    s.loc[is_amend, "kind"] = "other_amendment"
    s.loc[is_amend & s["AMENDMENTTYPE"].fillna("").str.upper().str.contains("RESTATEMENT"), "kind"] = "restatement"
    s = s[s["kind"] != "other_amendment"]                         # NEW HOLDINGS 등은 반영하지 않음
    s["rank"] = (s["kind"] == "restatement").astype(int)
    s = s.sort_values(["CIK", "rank", "FILING_DT", "ACCESSION_NUMBER"])
    return s.groupby("CIK", as_index=False).tail(1)


def load_quarter(period: str, use_cache: bool = True) -> pd.DataFrame:
    """한 보고 분기 → DataFrame(열: CIK, PERIODOFREPORT, CUSIP, VALUE_USD, SSHPRNAMT).
    옵션·원금 제외, 정정 규칙 적용, 금액 단위 통일, 같은 운용사·CUSIP 합산."""
    cache = QUARTER_CACHE / f"{period.upper()}.pkl"
    if use_cache and cache.exists():
        return pd.read_pickle(cache)

    end = period_end(period)
    subs, covers, where = [], [], {}
    for zp in local_zips():
        with zipfile.ZipFile(zp) as z:
            sub = _read(z, "SUBMISSION", SUB_COLS)
            sub["PERIOD_DT"] = _dates(sub["PERIODOFREPORT"])
            sub = sub[sub["PERIOD_DT"] == end]
            if sub.empty:
                continue
            cover = _read(z, "COVERPAGE", COVER_COLS)
            cover = cover[cover["ACCESSION_NUMBER"].isin(sub["ACCESSION_NUMBER"])]
            subs.append(sub)
            covers.append(cover)
            for a in sub["ACCESSION_NUMBER"]:
                where[a] = zp
    if not subs:
        return pd.DataFrame(columns=OUT_COLS)

    sub = pd.concat(subs, ignore_index=True).drop_duplicates("ACCESSION_NUMBER")
    sub["FILING_DT"] = _dates(sub["FILING_DATE"])
    cover = pd.concat(covers, ignore_index=True).drop_duplicates("ACCESSION_NUMBER")
    chosen = choose_filings(sub, cover)
    meta = chosen.set_index("ACCESSION_NUMBER")[["CIK", "FILING_DT"]]

    parts = []
    for zp in sorted({where[a] for a in meta.index}, key=lambda p: _sort_key(p.name)):
        accs = {a for a in meta.index if where[a] == zp}
        with zipfile.ZipFile(zp) as z:
            for chunk in _read_chunks(z, "INFOTABLE", INFO_COLS):
                chunk = chunk[chunk["ACCESSION_NUMBER"].isin(accs)]
                if not chunk.empty:
                    parts.append(chunk)
    if not parts:
        return pd.DataFrame(columns=OUT_COLS)
    info = pd.concat(parts, ignore_index=True)

    info = info[info["PUTCALL"].str.strip() == ""]                              # 옵션 제외
    info = info[info["SSHPRNAMTTYPE"].str.strip().str.upper() == "SH"]           # 원금(PRN) 제외
    info = info.join(meta, on="ACCESSION_NUMBER")
    value = pd.to_numeric(info["VALUE"], errors="coerce").fillna(0.0)
    old = info["FILING_DT"] < VALUE_IN_DOLLARS_FROM
    info["VALUE_USD"] = value.where(~old, value * 1000)
    info["SSHPRNAMT"] = pd.to_numeric(info["SSHPRNAMT"], errors="coerce").fillna(0.0)
    info["CUSIP"] = info["CUSIP"].str.strip().str.upper()
    info["CIK"] = info["CIK"].str.strip().str.lstrip("0")
    info["PERIODOFREPORT"] = end.strftime("%Y-%m-%d")

    out = (info.groupby(["CIK", "PERIODOFREPORT", "CUSIP"], as_index=False)[["VALUE_USD", "SSHPRNAMT"]].sum())
    out = out[OUT_COLS]
    try:
        QUARTER_CACHE.mkdir(parents=True, exist_ok=True)
        out.to_pickle(cache)
    except OSError:
        pass
    return out


# ======================================================================
# 확인용 명령
# ======================================================================
def inspect() -> None:
    zips = local_zips()
    if not zips:
        print("받은 파일이 없음. 먼저 download")
        return
    print(f"받은 파일 {len(zips)}개: {[p.name for p in zips]}")
    zp = zips[-1]
    print(f"\n== {zp.name} 안의 표와 첫 줄(열 이름)")
    with zipfile.ZipFile(zp) as z:
        for n in z.namelist():
            with z.open(n) as f:
                head = f.readline().decode("utf-8", "replace").rstrip()
            print(f"  {n}: {head[:200]}")
        sub = _read(z, "SUBMISSION", SUB_COLS)
        cover = _read(z, "COVERPAGE", COVER_COLS)
        info = _read(z, "INFOTABLE", INFO_COLS, nrows=200_000)
    print("\n== SUBMISSION 값 모양")
    print("  FILING_DATE 예:", sub["FILING_DATE"].head(3).tolist())
    print("  PERIODOFREPORT 예:", sub["PERIODOFREPORT"].head(3).tolist())
    print("  SUBMISSIONTYPE 종류:", sub["SUBMISSIONTYPE"].value_counts().to_dict())
    print("  PERIODOFREPORT 상위:", sub["PERIODOFREPORT"].value_counts().head(5).to_dict())
    print("\n== COVERPAGE 값 모양")
    print("  ISAMENDMENT 종류:", cover["ISAMENDMENT"].value_counts().to_dict())
    print("  AMENDMENTTYPE 종류:", cover["AMENDMENTTYPE"].value_counts().to_dict())
    print("\n== INFOTABLE 값 모양 (앞 20만 줄)")
    print("  SSHPRNAMTTYPE 종류:", info["SSHPRNAMTTYPE"].value_counts().to_dict())
    print("  PUTCALL 종류:", info["PUTCALL"].value_counts().to_dict())
    print("  VALUE 예:", info["VALUE"].head(5).tolist(), " CUSIP 예:", info["CUSIP"].head(3).tolist())


def show_quarter(period: str) -> None:
    import json
    from src.config import DEMO_DIR
    df = load_quarter(period, use_cache=False)
    print(f"{period}: 운용사 {df['CIK'].nunique():,}곳, {len(df):,}줄, 금액 합 ${df['VALUE_USD'].sum() / 1e12:.1f}조 달러")
    for demo in sorted(DEMO_DIR.glob("demo*/manager_data.json")):
        data = json.loads(demo.read_text(encoding="utf-8"))
        data = data.get("result", data)
        cik = str(data.get("cik") or "").lstrip("0")
        q = next((x for x in data.get("quarters") or [] if x["period"] == period.upper()), None)
        if not cik or q is None:
            continue
        mine = df[df["CIK"] == cik].set_index("CUSIP")
        theirs = {h["cusip"]: h for h in q["holdings"]}
        both = set(mine.index) & set(theirs)
        diff = [c for c in both if abs(mine.at[c, "VALUE_USD"] - theirs[c]["value_usd"]) > 1]
        print(f"\n  {data.get('manager_name')} (CIK {cik}): 데이터셋 {len(mine)}종목 / 저장본 {len(theirs)}종목, "
              f"겹침 {len(both)}, 금액 다른 종목 {len(diff)}")
        print(f"    금액 합: 데이터셋 ${mine['VALUE_USD'].sum():,.0f} / 저장본 ${sum(h['value_usd'] for h in theirs.values()):,.0f}")


def main(argv: list[str]) -> None:
    cmd = argv[0] if argv else ""
    if cmd == "list":
        files = list_files()
        sel = {n for n, _ in wanted(files)}
        for name, url in files:
            print(("* " if name in sel else "  ") + name)
        print(f"\n전체 {len(files)}개, 받을 것(*) {len(sel)}개")
    elif cmd == "download":
        download()
    elif cmd == "inspect":
        inspect()
    elif cmd == "quarter" and len(argv) > 1:
        show_quarter(argv[1])
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
