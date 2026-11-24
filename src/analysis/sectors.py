"""SIC 코드 → 업종 대분류 (Data · 김지유, Data 문서 B2 준비 4).

SIC 앞 두 자리로 SIC 공식 대분류 10개 중 하나에 넣는다. 표는 이 파일 한 곳에만 둔다.
한계: 대분류라 거칠다(반도체와 제약이 둘 다 제조, 소프트웨어는 서비스).
더 세밀하게 바꿀 때는 PM과 상의한다.
"""

UNCLASSIFIED = "미분류"

# (앞 두 자리 시작, 끝, 업종) — 표 순서가 동점일 때의 우선순위
SECTOR_RANGES: tuple[tuple[int, int, str], ...] = (
    (1, 9, "농림어업"),
    (10, 14, "광업"),
    (15, 17, "건설"),
    (20, 39, "제조"),
    (40, 49, "운송·통신·전기가스"),
    (50, 51, "도매"),
    (52, 59, "소매"),
    (60, 67, "금융·보험·부동산"),
    (70, 89, "서비스"),
    (91, 99, "공공·기타"),
)
SECTORS: tuple[str, ...] = tuple(name for _, _, name in SECTOR_RANGES)


def sector_of(sic) -> str:
    """SIC 코드(문자열·숫자) → 업종 이름. 없거나 표에 없으면 "미분류"."""
    if sic is None:
        return UNCLASSIFIED
    digits = "".join(ch for ch in str(sic).strip() if ch.isdigit())
    if not digits:
        return UNCLASSIFIED
    digits = digits.zfill(4)                  # "100" 같은 3자리는 앞에 0이 빠진 것
    two = int(digits[:2])
    for lo, hi, name in SECTOR_RANGES:
        if lo <= two <= hi:
            return name
    return UNCLASSIFIED
