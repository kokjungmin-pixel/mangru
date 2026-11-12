"""판단 기준·경로·데모 운용사 — PM만 수정한다. 값의 근거는 docs/CONTRACT.md A8."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data_cache"
DEMO_DIR = CACHE_DIR / "demo"
RAW_DIR = CACHE_DIR / "raw"
THRESHOLDS_PATH = CACHE_DIR / "thresholds.json"
FIXTURES_DIR = ROOT / "tests" / "fixtures"
FONT_DIR = ROOT / "assets" / "fonts"

# 데모 운용사 3곳: 조재연이 11/14까지 정해 주면 PM이 채운다. 그 전에는 가짜 값(demo1).
DEMO_MANAGERS = {
    "demo1": {"name": "Example Capital Management LLC", "aliases": ["Example Capital"],
              "cik": "0000000000", "crd": "000000", "has_13f": True, "last_check_date": None},
}

# LLM 온도 (A8 기본값): 심판은 같은 입력에 같은 점수가 나와야 해서 0
TEMPERATURE = {"keep": 0.2, "terminate": 0.2, "judge": 0.0, "analyst": 0.2}

HISTORY_QUARTERS = 14                  # 13F 수집 분기 수. 변화 13개 = 이번 분기 변화 1개 + 직전 3년(12개)
MIN_HISTORY_CHANGES = 4                # 자기 최대치 판정에 필요한 직전 변화의 최소 개수 (기본값)
WATCH_PERCENTILE = 0.90                # 기획서
ALERT_PERCENTILE = 0.95                # 기획서
MIN_MAPPING_RATE = 0.95                # 기획서: 매핑률(CIK까지 찾은 금액 비율) 하한
MIN_SIZE_COVERAGE = 0.90               # 발행주식 수까지 찾은 금액 비율 하한 (기본값)
SIZE_BOUNDS_USD = (2e9, 10e9)          # 소형 < 20억 달러 ≤ 중형 < 100억 달러 ≤ 대형 (기본값)
INDEX_LIKE_MIN_POSITIONS = 1500        # (기본값)
MIN_POSITIONS = 10                     # (기본값)
PEER_LEVEL_TAIL = 0.05                 # (기본값)
PEER_LEVEL_METRICS = ["small_cap_weight", "top10_concentration"]   # (기본값)
TEXT_MATERIAL_SIMILARITY = 0.85        # (기본값)
NEW_OFFICER_WINDOW_MONTHS = 6          # (기본값)
AUM_DROP = 0.30                        # 운용자산 30% 이상 감소 → 관찰 (기본값)
AUM_JUMP = 1.00                        # 운용자산 100% 이상 증가 → 관찰 (기본값)
EMPLOYEE_DROP_RATE = 0.20              # 직원 20% 이상 감소 (기본값)
EMPLOYEE_DROP_MIN = 3                  # 그리고 3명 이상 감소 (기본값)
PRIVATE_FUND_MIN_DIFF = 2              # 사모펀드 수 2개 이상 변화 (기본값)
PRIVATE_FUND_RATE = 0.25               # 그리고 직전의 25% 이상 변화 (기본값)
SHARES_OUT_MAX_GAP_DAYS = 120          # 발행주식 수 기준일과 분기 말의 허용 차이 (기본값)
SPLIT_SO_RATIO = 1.4                   # (기본값)
SPLIT_CAP_BAND = (0.7, 1.4)            # (기본값)
PRICE_JUMP_BAND = (0.55, 1.8)          # (기본값)
REBUTTAL_ROUNDS = 2                    # 기획서
EXPLAINED_MARGIN = 1                   # (기본값)
CONDITIONAL_MAX_UNEXPLAINED = 2        # (기본값)
MAX_VERIFY_RETRIES = 2                 # 기획서
API_RETRIES = 3                        # 기획서
SEC_MAX_RPS = 10                       # SEC 규정. 코드는 요청 사이 0.2초(초당 5회)로 여유 있게
MAX_LLM_CALLS_PER_RUN = 32             # 한 번 실행 LLM 호출 상한. 정상 10번(분석 2 + 토론 8) × 최대 3번(처음 + 재수행 2) + 여유 2
RAG_QUERIES = {"strategy": "investment strategy and methods of analysis"}   # (기본값)
RULE_TOKENS = {"5%", "10%", "90%", "95%"}   # 글에서 기준을 설명할 때 써도 되는 숫자 (상위 5%·10%, 커버리지 90%·95%)
