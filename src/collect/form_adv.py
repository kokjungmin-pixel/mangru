"""ADV 수집 (Frontend · 조재연). Frontend 문서 B3 "ADV 수집".
지금 있는 것: Part 2A 브로셔를 Item별로 나누기(split_items), Item 2 "중요 변경 없음" 판정(item2_declares_no_change).
TODO(조재연): 브로셔·Part 1 받기 → AdvPart2A·AdvPart1 → Schedule A.
"""
import re

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
