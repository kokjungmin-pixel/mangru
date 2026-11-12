"""공유 데이터 모양 — PM만 수정한다. docs/CONTRACT.md A6과 똑같아야 한다."""
from typing import Literal, Optional
from typing_extensions import TypedDict

# ---------- 공통 ----------
class Evidence(TypedDict):
    source: str            # "Form 13F 2026Q3" / "Form ADV Part 1A Schedule A" / "Form ADV Part 2A Item 8"
    url: str               # SEC 원문 링크
    as_of: str             # 기준일 (보고 기준일 또는 제출일)
    page: Optional[int]    # 문서 페이지 (없으면 None)
    quote: Optional[str]   # 원문 그대로의 짧은 인용 (200자 이내). 숫자 근거면 None 가능

class Plan(TypedDict):                      # ① 계획 (PM)
    manager_id: str                         # config.DEMO_MANAGERS 의 키
    manager_name: str
    has_13f: bool                           # 주식형이면 True → 13F 경로 포함
    checks: list[str]                       # ["strategy_drift", "key_person", "peer_anomaly"]
    period: str                             # 점검 반기, 예: "2026H2"

# ---------- ② 수집 (Frontend → Data) ----------
class Holding(TypedDict):
    cusip: str
    issuer: str
    title_of_class: str
    value_usd: float                        # 달러로 통일 (2023-01-03 이전 제출분은 천 달러 단위이므로 ×1000)
    shares: float
    ticker: Optional[str]
    issuer_cik: Optional[str]               # 발행사 CIK. 이게 있으면 '매핑 성공' (매핑률 계산 기준)
    sic: Optional[str]                      # 발행사 업종 SIC 코드 (4자리)
    shares_outstanding: Optional[float]     # 그 분기 말 기준 발행주식 수 (규모 구간·분할 확인용)
    shares_outstanding_partial: bool        # True면 여러 종류 주식 중 한 종류만 잡힌 값(실제보다 작은 하한값)
    is_etf: bool

class QuarterHoldings(TypedDict):
    period: str                             # "2026Q3" (보고 기준 분기)
    report_date: str                        # 분기 말일
    filed_date: str
    accession: str
    url: str
    holdings: list[Holding]                 # 옵션(PUT/CALL)·원금(PRN) 행 제외, 같은 CUSIP 합산 후

class Person(TypedDict):
    name: str
    entity_type: Optional[Literal["I", "DE", "FE"]]   # 개인 / 국내 법인 / 해외 법인 (Schedule A 표기)
    title: str
    since: Optional[str]                    # 취임 연월 "YYYY-MM"
    ownership_code: Optional[str]           # 지분 구간 코드
    is_control_person: Optional[bool]

class AdvPart1(TypedDict):
    filed_date: str
    url: str
    crd: str
    aum_usd: Optional[float]                # 규제상 운용자산 합계 (Item 5.F)
    employees: Optional[int]                # 전체 직원 수 (Item 5.A)
    private_funds: Optional[int]            # 자문하는 사모펀드 수 (Schedule D 7.B.(1) 기재 건수)
    people: list[Person]                    # Schedule A 임원·직접 소유주 (간접 소유주 Schedule B는 MVP 제외)

class AdvPart2A(TypedDict):
    filed_date: str
    url: str
    items: dict[str, str]                   # Item 번호 → 본문. 최소 "2"(중요 변경 요약), "8"(투자 전략·위험), "9"(징계)
    pages: dict[str, int]                   # Item 번호 → 시작 페이지

class HoldingChange(TypedDict):             # 최신 분기 vs 직전 분기 나란히 놓은 표 (사실만. 매매 추정은 Data가 한다)
    cusip: str
    issuer: str
    ticker: Optional[str]
    kind: Literal["new", "exit", "held"]    # 직전에 없음 / 최신에 없음 / 둘 다 있음
    shares_before: float
    shares_after: float
    value_before: float
    value_after: float
    weight_before: float
    weight_after: float

class PersonChange(TypedDict):
    kind: Literal["added", "removed", "title_changed", "ownership_changed"]
    name: str
    before: Optional[Person]
    after: Optional[Person]
    evidence: list[Evidence]

class TextChange(TypedDict):
    item: str                               # "8" 등
    before: str                             # 바뀐 문단 (직전본)
    after: str                              # 바뀐 문단 (최신본)
    material: bool                          # 실질 변경 여부 (판정 규칙은 A8)
    evidence: list[Evidence]

class ManagerData(TypedDict):
    manager_id: str
    manager_name: str
    cik: Optional[str]
    crd: Optional[str]
    quarters: list[QuarterHoldings]         # 오래된 분기 → 최신 순, 최대 14개. 13F를 내지 않으면 []
    holding_changes: list[HoldingChange]
    adv1_new: Optional[AdvPart1]
    adv1_old: Optional[AdvPart1]
    adv2a_new: Optional[AdvPart2A]
    adv2a_old: Optional[AdvPart2A]
    person_changes: list[PersonChange]
    text_changes: list[TextChange]
    item2_declares_no_change: Optional[bool]   # 최신 브로셔 Item 2가 "중요 변경 없음"이라고 적었는가
    has_new_filing: bool                    # 직전 점검 이후 새 공시가 있는가 (없으면 조기 종료)
    notes: list[str]                        # 처리 기록 (정정본 반영, 저장본 사용 등)
    unavailable: list[str]                  # 확인 불가 항목
    fetched_at: str

# ---------- ③ 변화 감지 (Data → Backend) ----------
class Signal(TypedDict):
    id: str                                 # "<manager_id>-<kind>-<번호>"
    manager_id: str
    kind: Literal["strategy_drift", "key_person", "peer_anomaly"]
    level: Literal["watch", "alert"]        # 관찰 / 경보
    source_form: Literal["13F", "ADV"]
    metric: str                             # A8의 지표 이름
    unit: Literal["ratio", "usd", "count", "text"]
    before: Optional[float]                 # 직전 분기 실제 값
    after: Optional[float]                  # 최신 분기 실제 값
    change: Optional[float]                 # after - before (실제 변화)
    active_change: Optional[float]          # 매매로 생긴 변화. 13F 비중 지표의 신호 판정은 이 값으로 한다
    percentile: Optional[float]             # 전체 13F 운용사 분포에서의 위치 (0~1, 클수록 큰 변화)
    exceeds_own_3y_max: Optional[bool]
    peer_median: Optional[float]            # Peer 대비 신호일 때 전체 운용사 중앙값
    summary: str                            # 코드가 만든 사실 한 줄
    explanation: str                        # 분석 에이전트(LLM)의 설명. 숫자는 표기값만 그대로 사용
    evidence: list[Evidence]                # 1개 이상 필수

class AnalysisResult(TypedDict):
    manager_id: str
    signals: list[Signal]                   # 관찰·경보만
    debate_required: bool                   # 경보 1개 이상 또는 관찰 2개 이상
    stated_strategy: Optional[str]          # 운용사가 밝힌 전략 한 줄 요약 (의견). 토론의 판단 기준
    stated_strategy_evidence: list[Evidence]   # 그 근거가 되는 ADV 2A 원문 인용
    data_checks: list[str]                  # 데이터 검사 결과 (통과·실패·보정 내역)
    unavailable: list[str]

# ---------- ④ 토론 (Backend → PM) ----------
class Argument(TypedDict):
    signal_id: str
    claim: str                              # 논거
    evidence_idx: list[int]                 # 해당 Signal.evidence 의 인덱스 (근거 밖 인용 금지)
    falsifier: str                          # 반증 조건: 무엇이 확인되면 이 논거가 틀린가

class Rebuttal(TypedDict):
    round: int                              # 1, 2
    side: Literal["keep", "terminate"]
    signal_id: str
    text: str
    concede: bool                           # 상대에 동의했는가 (True면 입장 고정 위반)

class SideScore(TypedDict):                 # 심판 점수표 (합계 10점)
    numbers: int                            # 수치 0~3
    grounds: int                            # 근거 0~3
    rebuttal: int                           # 반박 0~2
    limits: int                             # 한계 0~2

class ChangeVerdict(TypedDict):
    signal_id: str
    keep: SideScore
    terminate: SideScore
    status: Literal["explained", "unexplained"]   # 설명됨 / 미설명 (심판 점수로 코드가 결정)
    reason: str                             # 심판의 한 줄 판정 이유

class Option(TypedDict):
    name: Literal["maintain", "conditional", "review_termination"]
    recommended: bool
    grounds: list[str]                      # 선택지별 근거 문장. 문장 끝에 [signal_id]

class DebateResult(TypedDict):
    manager_id: str
    held: bool                              # 토론을 했는가
    rounds: int
    keep_args: list[Argument]
    terminate_args: list[Argument]
    rebuttals: list[Rebuttal]
    verdicts: list[ChangeVerdict]
    unexplained_count: int
    recommendation: Literal["maintain", "conditional", "review_termination"]
    options: list[Option]                   # 항상 3개
    questions: list[str]                    # 미팅 질문 3개 (토론을 안 했으면 빈 목록)
    warnings: list[str]                     # "토론 불충분" 등
    models: dict[str, str]                  # {"keep": 모델명, "terminate": 모델명, "judge": 모델명}

# ---------- ⑤ 리포트 (PM) ----------
class ReportSentence(TypedDict):
    section: Literal["recommendation", "changes", "debate", "options", "questions"]
    text: str
    kind: Literal["fact", "opinion"]        # 사실(출처 필수) / 의견(해석)
    signal_ids: list[str]
    evidence: list[Evidence]

class ReportDraft(TypedDict):
    manager_id: str
    period: str
    as_of: str                              # 리포트 기준일
    sentences: list[ReportSentence]
    sources: list[Evidence]                 # 출처 목록 (중복 제거)

# ---------- ⑥ 검증 (Data) ----------
class Mismatch(TypedDict):
    sentence_idx: int                       # ReportDraft.sentences 의 인덱스
    token: str                              # 문제가 된 숫자 표기 또는 인용
    reason: str                             # "신호에 없는 숫자" / "원문에 없는 인용" / "신호 값이 원본과 다름"

class VerifyResult(TypedDict):
    passed: bool
    failed_step: Optional[Literal["analysis", "debate"]]   # 다시 실행할 단계 (없으면 None)
    mismatches: list[Mismatch]
    unsupported_idx: list[int]              # 근거 없는 사실 문장 → 삭제 대상
    uncited_signals: list[str]              # 리포트에 인용되지 않은 신호 id

# ---------- 그래프 상태 (PM) ----------
class AgentState(TypedDict):
    request: str
    demo_mode: bool
    plan: Optional[Plan]
    data: Optional[ManagerData]
    analysis: Optional[AnalysisResult]
    debate: Optional[DebateResult]
    draft: Optional[ReportDraft]
    verify: Optional[VerifyResult]
    retries: int                            # 검증 실패로 재수행한 횟수 (전체 합계)
    next_step: Optional[Literal["analyze", "debate", "finish"]]   # verify 노드가 정한 다음 행선지 (조건부 간선이 읽음)
    removed_sentences: list[str]            # 검증에서 삭제한 문장 (리포트에 내역 표시)
    notices: list[str]                      # 화면 알림 (조기 종료, 재시도 초과, 토론 불충분 등)
    unavailable: list[str]
    status: Literal["running", "early_exit", "done", "failed"]
