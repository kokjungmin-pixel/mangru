"""ADV 수집 (Frontend · 조재연). Frontend 문서 B3 "ADV 수집".
지금 있는 것: Part 2A 브로셔를 Item별로 나누기(split_items), Item 2 "중요 변경 없음" 판정(item2_declares_no_change),
최신본·직전본 브로셔 받기와 AdvPart2A 조립(collect_adv2a).
TODO(조재연): Part 1 받기 → AdvPart1 → Schedule A.
"""
import io
import json
import re
import zipfile
import zlib
from datetime import date, timedelta

import pdfplumber

from src.collect.sec_client import sec_get, sec_zip

# 제목 줄: "Item 8. Methods ...", "Item 2 – Material Changes". 번호 뒤 구분자 다음에 공백 + 대문자로 시작하는 제목이 와야 한다.
# 그래서 본문 속 "Item 4.E was amended"(Brown) 같은 줄은 제목이 아니다. 대소문자 무시는 쓰지 않는다("Item 8 of Form ADV").
_ITEM = re.compile(r"^[ \t]*(?:Item|ITEM)[ \t]+(\d{1,2})[ \t]*[.:–—-]?[ \t]+[A-Z].*$", re.MULTILINE)
_TOC_LEADER = re.compile(r"\.{4,}|…{2,}")                 # 목차 줄의 점선 (Akre 는 "……")
_ANOTHER_ITEM = re.compile(r"\b(?:Item|ITEM)\s+\d")        # 한 줄에 Item 이 또 나오면 본문 속 나열 (Warburg)
# Part 2B(Brochure Supplement)는 따로 시작하는 줄. 그 뒤의 "Item 2" 는 사람별 경력이라 본문이 아니다 (Akre)
_PART_2B = re.compile(r"^[ \t]*(?:Form[ \t]+ADV[ \t]+)?(?:Part[ \t]*2B|Brochure[ \t]+Supplement)[ \t]*$",
                      re.MULTILINE | re.IGNORECASE)


def _is_heading(m: re.Match) -> bool:
    line = m.group(0)
    return not _TOC_LEADER.search(line) and not _ANOTHER_ITEM.search(line, m.end(1) - m.start())


def split_items(pages: list[str]) -> tuple[dict[str, str], dict[str, int]]:
    """브로셔 페이지 텍스트 목록 → ({Item 번호: 본문}, {Item 번호: 시작 페이지}).
    목차 줄·본문 속 Item 언급·Part 2B 는 제목으로 보지 않고, 그래도 같은 번호가 여러 번이면 본문이 가장 긴 것을 고른다."""
    text, starts = "", []
    for no, p in enumerate(pages, 1):
        starts.append((len(text), no))
        text += (p or "") + "\n"
    cut = _PART_2B.search(text)
    text = text[:cut.start()] if cut else text
    ms = [m for m in _ITEM.finditer(text) if _is_heading(m)]
    best: dict[str, tuple[str, int]] = {}
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(text)
        # 목차 줄은 본문에서 뺀다: "Item 3" 제목이 없으면 목차가 Item 2 본문에 붙는다 (Akre)
        body = "\n".join(ln for ln in text[m.end():end].splitlines() if not _TOC_LEADER.search(ln)).strip()
        n = m.group(1)
        if n not in best or len(body) > len(best[n][0]):
            best[n] = (body, m.start())
    page_of = lambda pos: max(no for st, no in starts if st <= pos)
    return {n: b for n, (b, _) in best.items()}, {n: page_of(p) for n, (_, p) in best.items()}


_NO_CHANGE = re.compile(
    r"no\s+material\s+changes?|not\s+been\s+any\s+material\s+changes?|has\s+not\s+been\s+materially\s+(?:amended|changed)",
    re.IGNORECASE)


def item2_declares_no_change(item2: str | None) -> bool | None:
    """True = '중요 변경 없음' / False = 변경을 적음 / None = 판단 불가(확인 불가로 기록). 규칙은 B3 그대로."""
    if not item2:
        return None
    hit = bool(_NO_CHANGE.search(item2))
    if hit and len(item2) < 600:
        return True
    if not hit:
        return False
    return None


# ---- 브로셔 받기 → AdvPart2A ----
IAPD_FIRM_URL = ("https://api.adviserinfo.sec.gov/search/firm/{crd}"
                 "?hl=true&nrows=12&query=&r=25&sort=score+desc&wt=json")
BROCHURE_URL = "https://files.adviserinfo.sec.gov/IAPD/Content/Common/crd_iapd_Brochure.aspx?BRCHR_VRSN_ID={vid}"
# 월별 브로셔 묶음(그달에 제출된 브로셔 전부). 3월처럼 큰 달은 _1_of_2, _2_of_2 로 나뉜다 (verified.md)
BROCHURE_ZIP_URL = "https://reports.adviserinfo.sec.gov/reports/foia/advBrochures/{y}/ADV_Brochures_{y}_{m}.zip"
_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December")
ZIP_FROM = date(2025, 1, 1)      # 이 달부터 IAPD 묶음. 그 전은 sec.gov 묶음(주소 규칙이 달마다 다름)
LOOKBACK_MONTHS = 15             # 연 1회 갱신이 의무라 15개월이면 직전본이 한 번은 있다
ITEMS_KEPT = ("2", "8", "9")     # B3: 2·8 은 반드시, 9 는 찾으면 넣는다


def _mdy(s: str) -> str:
    m, d, y = map(int, s.split("/"))
    return date(y, m, d).isoformat()


def _month_zips(y: int, mo: int) -> list[tuple[str, zipfile.ZipFile]] | None:
    """그달 브로셔 묶음 [(주소, ZipFile)]. 하나도 못 받으면 None."""
    m = _MONTHS[mo - 1]
    url = BROCHURE_ZIP_URL.format(y=y, m=m)
    if z := sec_zip(url):
        return [(url, z)]
    for n in (2, 3, 4):
        urls = [BROCHURE_ZIP_URL.format(y=y, m=f"{m}_{i}_of_{n}") for i in range(1, n + 1)]
        if first := sec_zip(urls[0]):
            rest = [(u, sec_zip(u)) for u in urls[1:]]
            return None if any(z is None for _, z in rest) else [(urls[0], first), *rest]
    return None


def brochure_before(crd: str, as_of: str) -> tuple[dict | None, list[str], list[str]]:
    """as_of 당일 또는 그 전에 낸 마지막 브로셔 → ({"filed_date", "url", "pdf"}, notes, unavailable).
    as_of 달부터 한 달씩 거슬러 월별 묶음 목차에서 "{CRD}_{브로셔ID}_{버전}_{YYYYMMDD}.pdf" 를 찾는다."""
    d = date.fromisoformat(as_of)
    y, mo = d.year, d.month
    for _ in range(LOOKBACK_MONTHS):
        if date(y, mo, 1) < ZIP_FROM:
            # shortcut: 2024년 이전 묶음은 아직 안 읽는다. 직전 점검일이 2025년 전인 운용사가 생기면 sec.gov 묶음을 붙일 것
            return None, [], [f"ADV 2A 직전본: 확인 불가 (2025년 1월 전 브로셔 묶음은 아직 읽지 않음, 기준일 {as_of})"]
        zips = _month_zips(y, mo)
        if zips is None:   # 이 달을 건너뛰면 이 달에 낸 직전본을 놓치고 더 오래된 것과 비교하게 된다
            return None, [], [f"ADV 2A 직전본: 확인 불가 ({y}-{mo:02d} 브로셔 묶음을 받지 못함)"]
        found = []
        for zip_url, z in zips:
            for name in z.namelist():
                parts = name.rsplit("/", 1)[-1].removesuffix(".pdf").split("_")
                if len(parts) == 4 and parts[0] == crd and parts[3].isdigit() and len(parts[3]) == 8:
                    filed = f"{parts[3][:4]}-{parts[3][4:6]}-{parts[3][6:]}"
                    if filed <= as_of:
                        found.append((filed, int(parts[2]) if parts[2].isdigit() else 0, name, zip_url, z))
        if found:
            # 같은 브로셔를 다시 내면 브로셔 ID 가 새로 붙는다(Akre·Brown 2026-03-30 → 03-31) → 가장 늦게 낸 것.
            # shortcut: 상품별로 브로셔를 따로 내는 운용사는 구분하지 못한다. 그런 곳이 생기면 매핑 CSV 의 BrochureName 으로 맞출 것
            filed, _, name, zip_url, z = max(found, key=lambda f: f[:3])
            notes = [f"ADV 2A 직전본: 브로셔 파일 {len(found)}개 중 가장 늦게 낸 것 사용 ({name})"] if len(found) > 1 else []
            try:
                pdf = z.read(name)   # 여기서도 범위 요청을 보낸다
            except (OSError, zipfile.BadZipFile, zlib.error) as e:
                return None, notes, [f"ADV 2A 직전본: 확인 불가 ({name} 을 받지 못함: {type(e).__name__})"]
            return {"filed_date": filed, "url": f"{zip_url}#{name}", "pdf": pdf}, notes, []
        y, mo = (y, mo - 1) if mo > 1 else (y - 1, 12)
    return None, [], [f"ADV 2A 직전본: 확인 불가 (기준일 {as_of} 전 {LOOKBACK_MONTHS}개월 묶음에 없음)"]


def _pdf_pages(pdf: bytes) -> list[str]:
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        return [p.extract_text() or "" for p in doc.pages]


def parse_brochure(pdf: bytes, filed_date: str, url: str) -> tuple[dict | None, list[str]]:
    """브로셔 PDF → (AdvPart2A, unavailable). Item 2·8 제목을 못 찾으면 넣지 않고 unavailable 에 적는다."""
    try:
        pages = _pdf_pages(pdf)
    except Exception as e:  # noqa: BLE001 — 외부 PDF 라 pdfplumber 가 여러 종류의 예외를 던진다
        return None, [f"ADV 2A 브로셔({filed_date}): 확인 불가 (PDF를 읽지 못함: {type(e).__name__})"]
    items, starts = split_items(pages)
    kept = [n for n in ITEMS_KEPT if n in items]
    unavailable = [f"ADV 2A Item {n}({filed_date}본): 확인 불가 (제목을 찾지 못함)" for n in ("2", "8") if n not in items]
    return {"filed_date": filed_date, "url": url,
            "items": {n: items[n] for n in kept}, "pages": {n: starts[n] for n in kept}}, unavailable


def latest_brochure(crd: str) -> tuple[dict | None, list[str]]:
    """IAPD 회사 상세 API 에서 가장 늦게 낸 브로셔 → ({"filed_date", "url"}, notes). 없으면 None."""
    d = sec_get(IAPD_FIRM_URL.format(crd=crd))
    try:
        ia = json.loads(d["hits"]["hits"][0]["_source"]["iacontent"])
        details = [(_mdy(b["dateSubmitted"]), b["brochureVersionID"]) for b in ia["brochures"]["brochuredetails"]]
    except (TypeError, KeyError, IndexError, ValueError, AttributeError):
        return None, []
    if not details:
        return None, []
    filed, vid = max(details)
    notes = [f"ADV 2A 최신본: IAPD 브로셔 {len(details)}개 중 가장 늦게 낸 것 사용 (버전 {vid})"] if len(details) > 1 else []
    return {"filed_date": filed, "url": BROCHURE_URL.format(vid=vid)}, notes


def collect_adv2a(crd: str, last_check_date: str | None) -> tuple[dict | None, dict | None, list[str], list[str]]:
    """CRD → (최신본 AdvPart2A, 직전본 AdvPart2A, notes, unavailable). 예외 없이 끝까지 간다.
    직전본 = last_check_date 당일 또는 그 전에 낸 마지막 브로셔(없으면 최신본 바로 전 브로셔)."""
    meta, notes = latest_brochure(crd)
    if meta is None:
        return None, None, notes, ["ADV 2A 최신본: 확인 불가 (IAPD 브로셔 목록 응답 없음)"]
    pdf = sec_get(meta["url"], kind="bytes")
    if not pdf:
        return None, None, notes, [f"ADV 2A 최신본: 확인 불가 (브로셔를 받지 못함: {meta['url']})"]
    new, unavailable = parse_brochure(pdf, meta["filed_date"], meta["url"])
    as_of = last_check_date or (date.fromisoformat(meta["filed_date"]) - timedelta(days=1)).isoformat()
    got, ns, us = brochure_before(crd, as_of)
    notes += ns
    unavailable += us
    old = None
    if got:
        old, us = parse_brochure(got["pdf"], got["filed_date"], got["url"])
        unavailable += us
    return new, old, notes, unavailable
