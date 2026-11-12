# 망루 개발 기획서 — Data (김지유)

> **사람용 안내:** 이 파일을 AI 코딩 도구(Claude Code 등)에 통째로 넣고 "C장 순서대로 시작해줘"라고 하면 된다. A장은 4개 파트가 똑같이 갖고 있는 공통 계약이고, B장이 내 파트 상세다.
>
> **AI에게:** 너는 「망루」 프로젝트의 **Data 파트(데이터 분석 에이전트·검증 에이전트)** 개발을 돕는다. 이 문서 전체를 읽고 A장의 계약(데이터 모양, 함수 이름·입출력, 절대 규칙)을 반드시 지켜라. `src/analysis/`(종목 식별 `securities.py` 포함), `prompts/analysis/`, `scripts/analysis_*`, `tests/analysis/`, `data_cache/thresholds.json`, `data_cache/demo/<id>/analysis.json`, `data_cache/demo/security_master.json`, `data_cache/raw/enrich_log.jsonl`, `docs/metrics.md`, `docs/number_audit.md`, `docs/notes/data.md` 밖의 파일은 수정하지 마라. 계약이 모호하거나 바꿔야 할 것 같으면 코드를 짜기 전에 사용자에게 먼저 물어라. 계산식은 B2에 적힌 그대로 구현하고, 식을 바꾸고 싶으면 먼저 물어라. 작업은 C장 순서로 진행하라.

## 0. 내 파트 한눈에

- **맡은 것:** 종목 식별 도구 + ③ 변화 감지(지표 계산 → 신호 판정 → 설명문) + 기준값 계산 + ⑥ 검증
- **내가 만드는 함수:** `enrich_cusips(cusips, as_of)`(Frontend의 수집 도구가 부름), `analyze(data, plan) -> AnalysisResult`, `verify_report(draft, analysis, debate, data) -> VerifyResult`
- **내 입력:** Frontend의 `ManagerData`(공시 원본과 비교표). **내 출력을 받는 곳:** Backend(토론), PM(리포트·그래프)
- **중요한 점:** 토론과 리포트에 나오는 **모든 숫자**가 여기서 나온다. 숫자가 틀리면 전체가 틀린다. 계산은 전부 코드로 하고, LLM은 계산된 결과를 설명하는 데만 쓴다

---

# A. 공통 계약 (4개 파트 문서에 똑같이 들어 있음)

> 기준 문서: 2026-11-12 제출한 예선 기획서 「망루」 제출본(10쪽). 기획서에 적힌 규칙은 그대로 옮겼고, 기획서에 숫자가 없는 규칙은 PM이 정한 **기본값**을 근거와 함께 A8에 적었다(`기본값` 표시). 기본값은 12/5 점검에서 실제 결과로 근거가 생길 때만 바꾼다.
>
> 이 장을 바꾸고 싶으면 코드를 먼저 고치지 말고 PM(김정민)에게 요청한다. 레포가 생긴 뒤에는 `docs/CONTRACT.md` 가 원본이고, 파트 문서의 A장은 그 사본이다.

## A1. 프로젝트 요약

| 항목 | 내용 |
|---|---|
| 서비스 | **망루** — 위탁운용사 변화 감지·토론 AI Agent (팀 망루지기) |
| 대회 | 국부펀드 KIC AI 에이전트 공모전. 본선 제출 **12/22 10:00**, 발표 **12/29** |
| 문제 | KIC는 외부 위탁운용사 204곳을 반기마다 점검한다. 반기 사이에 생긴 전략 이탈·인력 변동은 놓치기 쉽다 |
| 하는 일 | SEC 공시(Form 13F, Form ADV)에서 변화를 감지 → 변화를 근거로 '유지 측 vs 해지 측' AI 토론 → `유지 / 조건부 유지 / 해지 검토` 선택지별 근거를 담은 1장 점검 리포트 |
| 사용자 | KIC 위탁운용·리스크관리 담당자. 입력 예: "○○ Capital 반기 점검 준비해줘" |
| 차별점 | 요약 도구가 아니라 **토론 도구**. 운용사가 낸 자료가 아니라 **공시만으로 독립 확인**. 최종 결정은 사람 |
| 기술 (기획서 ④) | Python, LangGraph, LLM API(Claude·GPT), Chroma(RAG), SQLite(Memory, Should), Streamlit, GitHub |

## A2. 처리 흐름 (기획서 ③ Workflow)

```
입력 → ①계획 → ②수집 → ③변화 감지 → ④토론 → ⑤점검 리포트 → ⑥검증 ─통과→ PDF
                              ↑__ 검증 실패 시 해당 단계부터 재수행 (전체 합쳐 최대 2회) __|
```

| 단계 | 하는 일 (기획서 문구 기준) | 담당 | 함수 |
|---|---|---|---|
| ① 계획 | 요청을 해석해 경로 선택. 주식형이면 13F 포함, 새 공시가 없으면 조기 종료 | PM | `make_plan` |
| ② 수집 | EDGAR·IAPD에서 최신·직전 공시 자동 수집 (실패 시 대체 경로), 신·구본 비교표 | Frontend | `collect` |
| ③ 변화 감지 | 전략·인력·Peer 이상을 **코드로** 계산. 데이터 검사 통과 + 기준 초과 시 신호 | Data | `analyze` |
| ④ 토론 | **운용사당 토론 1회.** 변화마다 찬반 논거 + 반증 조건. 심판이 점수표로 판정 | Backend | `run_debate` |
| ⑤ 점검 리포트 | 선택지별 근거 + 미팅 질문 3개 + 출처·기준일 | PM | `draft_report`, `render_pdf` |
| ⑥ 검증 | 숫자·인용을 원문과 대조, 모든 신호 인용 확인, 근거 없는 문장 삭제(내역 표시) | Data | `verify_report` |
| 화면 | 입력, 단계별 진행 상황, 결과 카드, PDF 다운로드 | Frontend | `src/app.py` |

"새 공시가 없으면 조기 종료"는 기획서에서 ① 계획에 속한다. 새 공시 여부는 공시 목록을 조회해야 알 수 있으므로, 구현에서는 수집 단계가 가장 먼저 목록만 확인해 `has_new_filing` 을 채우고 그래프가 바로 종료한다. 화면에는 계획 단계의 결과로 보여 준다.

## A3. 파트와 담당

| 파트 | 담당 | 범위 |
|---|---|---|
| Frontend | 조재연 | UI·UX + 공시 수집 도구(SEC 요청 공용 함수 포함) + 신·구본 비교 |
| Backend | 임동욱 | 토론 에이전트(유지 측·해지 측·심판), 선택지, 미팅 질문, LLM 호출 모듈 |
| Data | 김지유 | 종목 식별 도구, 데이터 분석 에이전트(지표·신호·설명), 기준값, 검증 에이전트 |
| PM | 김정민 | 레포·계약 관리, API 키·계정 준비, LangGraph 연결, 리포트·PDF, 근거 검색(RAG), 통합 테스트, 발표 준비 |

## A4. 절대 규칙

1. **숫자는 코드로 계산한다.** LLM은 계산하지 않고 숫자를 만들지 않는다. LLM에게는 코드가 미리 표기해 둔 값(예: `27%`, `+15%p`)을 주고 **그대로 옮겨 쓰게** 한다.
2. **수치·사실 문장마다 원문 출처**(문서명, URL, 기준일)를 붙인다. 해석은 `opinion`(의견)으로 구분한다. 출처 없는 사실 문장은 리포트에 넣지 않는다.
3. 데이터가 없거나 막히면 지어내지 않고 **`확인 불가`** 로 표시하고 계속 진행한다.
4. API 키·개인정보를 코드·문서·커밋·로그에 넣지 않는다. 로컬은 `.env`, 배포는 Streamlit secrets.
5. SEC 접근 규칙: **초당 10회 이하**, 모든 요청에 `User-Agent: Mangru-Team <연락 이메일>` 헤더. API 오류는 최대 3회 시도 후 캐시 사용, 그래도 없으면 `확인 불가`.
6. 공시는 링크와 짧은 인용(200자 이내)만 쓴다. 개인정보는 공시에 나온 수준만 쓴다.
7. **자기 파트 폴더만 수정한다.** 다른 파트 코드를 고쳐야 하면 담당자에게 요청한다.
8. 최종 결정은 담당자(사람)다. 에이전트의 권고는 공시 변화에 한정한다(성과·계약 판단은 하지 않는다).

## A5. 개발 환경과 폴더

### 환경 (전원 동일하게)
- Python **3.11**, 가상환경(`python -m venv .venv`), `pip install -r requirements-dev.txt`, 테스트는 `pytest`.
- 파일을 읽고 쓸 때 항상 `encoding="utf-8"` 을 적는다(윈도우에서 한글이 깨지는 것을 막는다). JSON 저장은 `ensure_ascii=False`. 경로는 `pathlib.Path` 로.
- 라이브러리는 아래 목록만 쓴다. 더 필요하면 PM에게 요청한다.

| 용도 | 라이브러리 | 고른 이유 |
|---|---|---|
| 에이전트 흐름 | `langgraph` | 기획서에 명시. 분기·재시도를 그래프로 표현 |
| 화면 | `streamlit` | 기획서에 명시. 파이썬만으로 화면 |
| 표 계산 | `pandas` | 지표 계산 |
| HTTP | `requests` | SEC·OpenFIGI 호출 |
| XML | 표준 라이브러리 `xml.etree.ElementTree` | 13F 정보표. 추가 설치 없음 |
| PDF 읽기 | `pdfplumber` | 페이지 번호와 함께 텍스트 추출 |
| PDF 만들기 | `fpdf2` | 순수 파이썬, 한글 TTF 폰트 등록이 간단 |
| LLM | `anthropic`, `openai` | 유지 측·해지 측에 서로 다른 회사 모델 (기획서 규칙) |
| 형식 검사 | `pydantic`, `typing_extensions` | `state.py` 모양대로 JSON이 맞는지 한 줄로 검사 |
| 설정 | `python-dotenv` | `.env` 읽기 |
| 테스트 | `pytest` (dev) | |
| 근거 검색 | `chromadb` (dev 전용) | 기획서에 명시. **로컬에서만** 쓰고 배포 서버에는 설치하지 않는다(A9) |

- `requirements.txt` = 배포 서버용(위 표에서 dev 표시가 없는 것), `requirements-dev.txt` = 그것 + `pytest`, `chromadb`. 버전은 설치한 실제 버전으로 고정한다.

### 폴더와 소유권
```
mangru/
  CLAUDE.md               # AI 코딩 도구가 매번 읽는 공통 규칙 (PM)
  docs/                   # CONTRACT.md(이 장), parts/, decisions.md, verified.md, notes/ (PM. notes/<파트>.md 는 각 파트)
  requirements.txt, requirements-dev.txt, .env.example   (PM)
  assets/fonts/           # PDF용 한글 폰트 (PM)
  src/
    state.py              # 공유 데이터 모양 — PM만 수정
    config.py             # 데모 운용사 목록, 경로, 판단 기준 상수 — PM만 수정
    validate.py           # validate(obj, 타입) 형식 검사 — PM
    llm.py                # 모델 호출 한 곳 — Backend
    collect/              # Frontend: 수집 도구, 신·구본 비교
    analysis/             # Data: 지표, 신호, 설명, 검증
    debate/               # Backend: 유지 측·해지 측·심판, 선택지, 미팅 질문
    rag/                  # PM: 근거 검색 (Chroma)
    report/               # PM: 리포트 초안, PDF, format.py(숫자 표기)
    plan.py               # PM: make_plan (규칙 기반)
    graph.py              # PM: LangGraph 연결, stream_run
    app.py, ui/           # Frontend: Streamlit 화면
  prompts/debate/ (Backend), prompts/analysis/ (Data)
  scripts/                # 파트별 스크립트 (파일명 앞에 collect_/analysis_/debate_/rag_)
  data_cache/
    raw/                  # 원본 대용량. .gitignore, 올리지 않음
    demo/<manager_id>/    # 데모 3곳의 작은 파일. GitHub에 올림
    thresholds.json       # 기준값 사전 계산 파일 (Data). GitHub에 올림
  logs/                   # .gitignore
  tests/fixtures/ (PM), tests/collect/ analysis/ debate/ integration/
```
- 브랜치: `feat/<파트>-<기능>`. `main` 에 직접 푸시하지 않는다. PR은 PM이 합친다.
- 레포가 아직 없으면 로컬에 같은 구조로 만들어 시작하고, PM 레포가 생기면 옮긴다.

## A6. 공유 데이터 모양 — `src/state.py`

> PM만 수정한다. 필드를 임의로 추가·삭제·이름 변경하지 않는다. 비율은 항상 0~1(예: 0.27), 금액은 달러, 날짜는 `YYYY-MM-DD`, 분기는 `2026Q3`. `typing_extensions.TypedDict` 를 쓰는 이유는 pydantic이 파이썬 3.11에서 이 형태만 검사할 수 있기 때문이다.

```python
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
```

## A7. 함수 계약

각 파트는 아래 **이름·입력·출력**만 지키면 내부 구현은 자유다. 모듈끼리는 이 함수로만 연결한다. 함수 경계에서 `validate(결과, 타입)` 으로 모양을 검사한다.

| 함수 | 파트 | 위치 | 하는 일 |
|---|---|---|---|
| `make_plan(request: str) -> Plan \| None` | PM | `src/plan.py` | 요청 문장 → 대상 운용사·경로. 운용사를 못 찾으면 `None`. LLM 없음 |
| `collect(plan: Plan, demo_mode: bool = True) -> ManagerData` | Frontend | `src/collect/__init__.py` | 공시 원본 수집 + 신·구본 비교표 |
| `sec_get(url: str, kind: Literal["json", "bytes"] = "json") -> dict \| bytes \| None` | Frontend | `src/collect/sec_client.py` | 모든 SEC 요청은 이 함수로. User-Agent, 요청 간격 0.2초, 3회 시도, 원본 저장. 404·끝내 실패하면 `None`(예외 없음). 11/16까지 올림 |
| `enrich_cusips(cusips: list[str], as_of: str) -> dict[str, dict]` | Data | `src/analysis/securities.py` | CUSIP → `{"ticker", "issuer_cik", "sic", "shares_outstanding", "shares_outstanding_partial", "is_etf"}`. `as_of` 는 분기 말일. **절대 예외를 던지지 않는다**(못 찾은 값은 `None`). 결과는 캐시. Data의 기준값 스크립트도 이 함수를 쓴다 |
| `analyze(data: ManagerData, plan: Plan) -> AnalysisResult` | Data | `src/analysis/__init__.py` | 지표 계산 → 신호 → 설명 → 토론 필요 여부 |
| `build_index(manager_id: str, adv2a: AdvPart2A) -> int` | PM | `src/rag/__init__.py` | ADV 2A 문단을 근거 검색 색인에 넣고 넣은 개수를 돌려줌 (실제 모드에서만) |
| `search_evidence(manager_id: str, query: str, k: int = 3) -> list[Evidence]` | PM | `src/rag/__init__.py` | ADV 2A에서 관련 문단 찾기. 색인이 없거나 `chromadb` 가 없으면 빈 목록 |
| `run_debate(analysis: AnalysisResult, data: ManagerData, demo_mode: bool = True) -> DebateResult` | Backend | `src/debate/__init__.py` | 토론·판정·선택지·미팅 질문 |
| `draft_report(state: AgentState) -> ReportDraft` | PM | `src/report/draft.py` | 리포트 초안 조립 |
| `verify_report(draft: ReportDraft, analysis: AnalysisResult, debate: DebateResult, data: ManagerData) -> VerifyResult` | Data | `src/analysis/verify.py` | 초안 검증 |
| `apply_verify(draft: ReportDraft, verify: VerifyResult, drop_mismatched: bool) -> tuple[ReportDraft, list[str]]` | PM | `src/report/draft.py` | 근거 없는 문장(항상)과 불일치 문장(재수행을 못 할 때)을 뺀 초안 + 뺀 문장 목록 |
| `render_pdf(state: AgentState) -> bytes` | PM | `src/report/pdf.py` | 검증을 거친 상태 → PDF |
| `stream_run(request: str, demo_mode: bool = True) -> Iterator[dict]` | PM | `src/graph.py` | 단계가 끝날 때마다 `{"step": 단계명, "state": AgentState}`. 화면이 이걸 받아 그린다 |
| `call_llm(role, system, user, json_keys=None, temperature=None) -> dict \| str` | Backend | `src/llm.py` | 모든 LLM 호출은 이 함수 하나로. `role` 은 `"keep" / "terminate" / "judge" / "analyst"` |
| `reset_call_count() -> None` | Backend | `src/llm.py` | 실행 시작 때 LLM 호출 수를 0으로 (`stream_run` 이 부름) |
| `validate(obj, type_) -> None` | PM | `src/validate.py` | `state.py` 모양과 다르면 예외 |

- `stream_run` 의 `step` 값: `"plan"`, `"collect"`, `"analyze"`, `"debate"`, `"draft"`, `"verify"`, `"done"`.
- **mock 먼저:** 각 파트는 자기 함수의 가짜 버전(샘플 JSON을 돌려줌)을 가장 먼저 올린다. 그래야 다른 파트를 기다리지 않고 연결할 수 있다.

### 숫자 표기와 숫자 검사 — `src/report/format.py` (PM이 11/16까지 만들고 모든 파트가 쓴다)

아래 코드를 **그대로** 쓴다(실행해서 예시가 맞는 것을 확인했다). 반올림은 `round()` 가 아니라 `Decimal` 사사오입이다. `round()` 는 5를 짝수 쪽으로 보내 값이 달라질 수 있다.

```python
import re
from decimal import Decimal, ROUND_HALF_UP

from src.config import RULE_TOKENS


def _r1(x) -> Decimal:
    """소수 첫째 자리 사사오입. round()는 쓰지 않는다."""
    return Decimal(str(x)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def _s(d: Decimal) -> str:
    t = format(d, "f")
    return t[:-2] if t.endswith(".0") else t


def fmt_ratio(x: float) -> str:                       # 0.27 -> "27%"
    return _s(_r1(Decimal(str(x)) * 100)) + "%"


def fmt_signed_ratio(x: float) -> str:                # -0.35 -> "-35%" (증감률)
    q = _r1(Decimal(str(x)) * 100)
    return ("+" if q > 0 else "-" if q < 0 else "") + _s(abs(q)) + "%"


def fmt_pp(d: float) -> str:                          # 0.15 -> "+15%p"
    q = _r1(Decimal(str(d)) * 100)
    return ("+" if q > 0 else "-" if q < 0 else "") + _s(abs(q)) + "%p"


def fmt_change_pp(b: float, a: float) -> str:         # "12% → 27% (+15%p)"
    return f"{fmt_ratio(b)} → {fmt_ratio(a)} ({fmt_pp(a - b)})"


def fmt_top_pct(p: float) -> str:                     # 0.97 -> "상위 3%"
    return "상위 " + fmt_ratio(1 - p)


def fmt_multiple(a: float, b: float):                 # 0.27, 0.14 -> "1.9배"
    if not b:
        return None
    return _s(_r1(Decimal(str(a)) / Decimal(str(b)))) + "배"


def fmt_usd(x: float) -> str:                         # 1.2e9 -> "$1.2B"
    for unit, base in (("B", Decimal("1e9")), ("M", Decimal("1e6")), ("K", Decimal("1e3"))):
        if abs(Decimal(str(x))) >= base:
            return "$" + _s(_r1(Decimal(str(x)) / base)) + unit
    return "$" + _s(_r1(x))


def fmt_count(n: int, unit: str) -> str:              # 1234, "명" -> "1,234명"
    return f"{int(n):,}{unit}"


# 검사 대상 표기: $금액, %p, %, 배, 명 (리포트 검증에서는 건·점도)
# '개'는 "4개 분기" 같은 일반 표현과 겹쳐서 검사하지 않는다
_TOKEN = re.compile(
    r"\$\d+(?:\.\d+)?[KMB]?"
    r"|[+\-]?\d+(?:\.\d+)?%p"
    r"|[+\-]?\d+(?:\.\d+)?%"
    r"|\d+(?:\.\d+)?배"
    r"|\d{1,3}(?:,\d{3})+(?:명|건|점)|\d+(?:명|건|점)"
)


def number_tokens(text: str, include_report_units: bool = False) -> list[str]:
    toks = _TOKEN.findall(text.replace("−", "-"))
    if not include_report_units:
        toks = [t for t in toks if not (t.endswith("건") or t.endswith("점"))]
    return toks


def _both_signs(out: set, t):
    if t:
        out.add(t)
        out.add(t.lstrip("+-"))


def allowed_tokens(sig: dict) -> set[str]:
    """그 신호에 대해 글에 써도 되는 숫자 표기의 집합."""
    out = set(RULE_TOKENS) | set(number_tokens(sig["summary"]))   # summary는 코드가 만든 문장이라 믿는다
    b, a = sig["before"], sig["after"]
    if sig["unit"] == "ratio":
        for v in (b, a, sig["peer_median"]):
            if v is not None:
                out.add(fmt_ratio(v))
        for d in (sig["change"], sig["active_change"]):
            if d is not None:
                _both_signs(out, fmt_pp(d))
        if a is not None and sig["peer_median"]:
            out.add(fmt_multiple(a, sig["peer_median"]))
    elif sig["unit"] in ("usd", "count"):
        for v in (b, a):
            if v is not None:
                out.add(fmt_usd(v) if sig["unit"] == "usd" else fmt_count(v, "명"))
        if b and a is not None:
            _both_signs(out, fmt_signed_ratio((a - b) / b))
        if sig["unit"] == "count" and b is not None and a is not None:
            out.add(fmt_count(abs(a - b), "명"))
    if sig["percentile"] is not None:
        out.add(fmt_ratio(1 - sig["percentile"]))
    return out


def unknown_numbers(text: str, signals: list[dict]) -> list[str]:
    """글 속 숫자 중 관련 신호들로 설명되지 않는 것 (빈 목록이면 통과)."""
    allowed = set().union(*(allowed_tokens(s) for s in signals)) if signals else set(RULE_TOKENS)
    return [t for t in number_tokens(text) if t not in allowed]
```

| 호출 | 결과 |
|---|---|
| `fmt_ratio(0.27)`, `fmt_ratio(0.1225)` | `27%`, `12.3%` |
| `fmt_pp(0.15)`, `fmt_pp(-0.0216)`, `fmt_pp(0)` | `+15%p`, `-2.2%p`, `0%p` |
| `fmt_change_pp(0.12, 0.27)` | `12% → 27% (+15%p)` |
| `fmt_top_pct(0.97)` | `상위 3%` |
| `fmt_multiple(0.27, 0.14)`, `fmt_multiple(0.27, 0)` | `1.9배`, `None` |
| `fmt_usd(1.2e9)`, `fmt_usd(850e6)` | `$1.2B`, `$850M` |
| `fmt_signed_ratio(-0.35)`, `fmt_count(1234, "명")` | `-35%`, `1,234명` |
| `number_tokens("소형주 비중 12% → 27% (+15%p), 상위 3%")` | `["12%", "27%", "+15%p", "3%"]` |
| `unknown_numbers("…31%까지 갈 수 있다", [A11의 소형주 신호])` | `["31%"]` |

**숫자 검사 방법 (Backend·Data가 똑같이 쓴다):** `unknown_numbers(글, 그 운용사의 신호 전체)` 가 빈 목록이면 통과다. 신호 하나가 아니라 **전체**를 넘기는 이유: 기획서 예시처럼 "인력 변동과 전략 이탈이 같은 시기"라고 두 신호를 엮는 논거가 정상이기 때문이다. 하나라도 있으면 "신호에 없는 숫자"다. 리포트 검증에서는 `건`(개수)·`점`(심판 점수)도 따로 확인한다(Data 문서 B6). 한계: `개`, `년`, `일` 은 "4개 분기", "3년", "45일" 같은 일반 표현과 겹쳐 검사하지 않는다.

## A8. 판단 기준 (기획서 ③·⑤) — `src/config.py`

값은 모두 `config.py` 상수로 두고 코드에 직접 쓰지 않는다.

### 13F 지표와 "분기 변화폭" (Data)
13F 지표는 ETF를 뺀 보유 주식만으로 계산한다. 비중 = 종목 금액 ÷ (ETF 제외) 전체 금액.

| 기준값 이름 | 변화폭의 뜻 | 신호의 `metric` |
|---|---|---|
| `sector_shift` | 업종별 **매매 기준 비중 변화**의 절댓값 중 가장 큰 것 | `sector_weight:<그 업종>` |
| `size_shift` | 소형·중형·대형 3구간별 매매 기준 비중 변화의 절댓값 중 가장 큰 것 | `small_cap_weight` / `mid_cap_weight` / `large_cap_weight` |
| `concentration_change` | 상위 10종목 비중 합의 매매 기준 변화(절댓값) | `top10_concentration` |
| `turnover` | 분기 회전율 그 자체 (매매 규모) | `turnover` |

- **매매 기준 변화(`active_change`)** = 실제 최신 비중 − "직전 분기 주식 수를 그대로 들고 있었다면 최신 주가에서 나왔을 비중". 주가만 변해서 생긴 비중 변화를 빼기 위한 것이다(기획서 ⑤ "매매 변화만 신호"). 계산식과 손 계산 예시는 Data 문서 B2.
- 업종 = SIC 코드의 공식 대분류 10개(Data 문서 B2 표). 규모 3구간 경계는 `SIZE_BOUNDS_USD`.
- 13F 신호는 기획서대로 **매매로 생긴 변화만** 신호로 본다(`active_change` 로 판정).

### 신호 등급 (기획서 문구 그대로)
- **관찰(`watch`)**: 변화폭이 전체 13F 운용사(인덱스형 제외) 분포의 **상위 10%** 이면서 **자기 3년 최대치 초과**
- **경보(`alert`)**: **상위 5%** 또는 **ADV 임원·소유주 변경**
- 자기 3년 최대치 = 그 운용사의 **이번 분기를 뺀 직전 12개 분기 변화폭** 중 최댓값. 그래서 13F는 14개 분기를 모은다. 직전 변화가 `MIN_HISTORY_CHANGES`(4)개 미만이면 판정할 수 없으므로 관찰 신호를 내지 않고 `확인 불가` 에 적는다. 4~11개면 있는 만큼으로 판정하고 `data_checks` 에 개수를 적는다.
- 데이터 검사(기획서 ⑤ "매핑률 95% 미만은 확인 불가"): **매핑률** = 발행사 CIK까지 찾은 종목의 금액 ÷ 전체 금액(ETF 제외). 95% 미만이면 업종·규모 지표는 `확인 불가`. 규모는 추가로 **발행주식 수까지 찾은 금액 비율이 90% 미만**이면 `확인 불가`(`기본값`, 해외 예탁증서·여러 종류 주식 발행사는 주식 수를 안전하게 못 구하는 경우가 있어 매핑률보다 낮게 둠). 집중도·회전율은 매핑 없이 계산되므로 항상 계산한다.
- **토론 개시: 경보 1개 이상 또는 관찰 2개 이상** (`debate_required`)
- 보정 목표(기획서 ⑥): 분기당 토론 대상이 전체 운용사의 10% 안팎

### 기획서에 등급이 없어 기본값으로 정한 신호
기획서 ③의 경보 정의(상위 5% 또는 임원·소유주 변경)를 넓히지 않기 위해, 아래 신호는 모두 **관찰**로만 둔다. 관찰 2개가 모이면 토론이 열린다.

| 신호 (`metric`) | 종류(`kind`) | 규칙 (기본값) | 등급 | 근거 |
|---|---|---|---|---|
| `peer_level:<지표>` | `peer_anomaly` | `small_cap_weight`, `top10_concentration` 의 **수준**이 전체 13F 운용사 분포의 위 5% 또는 아래 5% | 관찰 | 기획서 4쪽 예시 "소형주 비중이 중앙값의 약 2배". 꼬리 크기는 경보 기준(상위 5%)과 같게 |
| `strategy_text_changed` | `strategy_drift` | ADV 2A Item 8(투자 전략·위험)에 실질 변경 | 관찰 | 기획서 ⑤ "투자 전략 문구, 실질 변경만 판정" |
| `item2_mismatch` | `strategy_drift` | Item 2가 "중요 변경 없음"인데 Item 8에 실질 변경 | 관찰 | 기획서 ⑤ "Item 2와 본문의 불일치" |
| `aum_change` | `strategy_drift` | 직전 ADV 대비 운용자산이 **30% 이상 감소** 또는 **100% 이상 증가** | 관찰 | 주식시장만으로 1년에 20%대 하락은 생길 수 있어(2022년 S&P 500 약 −19%) 그보다 큰 감소만 본다. 1년에 두 배 이상 증가는 운용 역량 대비 급성장 |
| `employee_drop` | `key_person` | 직원 수가 **20% 이상 감소** 이면서 **3명 이상 감소** | 관찰 | 인력 이탈 신호. 소형 운용사에서 1~2명 변동은 제외 |
| `private_fund_change` | `strategy_drift` | 사모펀드 수가 **2개 이상** 이면서 **직전의 25% 이상** 늘거나 줄어듦 | 관찰 | 사업 범위·전략 확장의 신호. 펀드 1개 신설·청산은 흔해서 제외 |

- AUM·직원 수·사모펀드 수 신호는 ADV Part 1의 신·구본(보통 1년 간격) 비교라서 13F 분기 신호와 기간이 다르다. `summary` 에 두 제출일을 적는다.
- ADV 2A 실질 변경 판정: 문단을 정규화(소문자, 공백 정리, 숫자·날짜 제거)한 뒤 직전본의 가장 비슷한 문단과의 유사도(`difflib.SequenceMatcher.ratio`)가 `TEXT_MATERIAL_SIMILARITY`(0.85) 미만이거나, 200자 이상 문단이 새로 생기거나 사라졌으면 `material=True`.
- 이전본이 없을 때 신규 임원 판정: 취임 연월이 직전 점검일 이후(직전 점검일이 없으면 최신 공시 제출일 기준 최근 6개월 = 반기 점검 주기).

### 기본값과 근거 (12/5 점검 때 실제 결과로 근거가 생기면 바꾼다)
| 값 | 기본값 | 근거 |
|---|---|---|
| `EXPLAINED_MARGIN` | 1점 | 동점이면 유지 측이 변화를 설명하지 못한 것으로 보고 사람이 보게 한다(보수적) |
| `CONDITIONAL_MAX_UNEXPLAINED` | 2건 | 기획서 4쪽 예시 "변화 3건 중 미설명 2건 → 조건부 유지"와 일치. 3건 이상이면 해지 검토 |
| `SIZE_BOUNDS_USD` | 20억·100억 달러 | 미국 시장에서 흔히 쓰는 소형·중형·대형 구분 |
| `INDEX_LIKE_MIN_POSITIONS` | 1,500종목 | 단일 전략 액티브 운용사가 1,500종목 이상 들고 있는 경우는 드물다. 전체시장 지수 추종형을 걸러낸다 |
| `MIN_POSITIONS` | 10종목 | 10종목 미만이면 상위 10종목 비중이 항상 100%라 분포를 왜곡 |
| `TEXT_MATERIAL_SIMILARITY` | 0.85 | 단어 몇 개만 고친 문단은 0.9 이상이 나와 걸러지고, 문장이 바뀌면 그 아래로 떨어진다. 데모 3곳에서 오탐을 보고 조정 |
| `SHARES_OUT_MAX_GAP_DAYS` | 120일 | 분기 보고서 표지의 주식 수 기준일은 분기 말 뒤 1~2달이라 한 분기 + 여유 |
| `MIN_HISTORY_CHANGES` | 4개 | 최소 1년치 변화가 있어야 "자기 최대치"가 의미 있다 |
| `SPLIT_SO_RATIO`, `SPLIT_CAP_BAND`, `PRICE_JUMP_BAND` | 1.4 / 0.7~1.4 / 0.55~1.8 | 가장 흔한 3대2 분할(×1.5)부터 잡고, 분할이 아닌 실적 충격(보통 ±40% 이내)과 구분 |
| LLM 온도 | 심판 0, 나머지 0.2 | 심판은 같은 입력에 같은 점수가 나와야 한다 |
| 토론 품질 반복 시험 | 3회 | 3회 모두 같은 권고면 통과, 2회면 프롬프트 점검 후 3회 재시험 |
| RAG 질의 | `"investment strategy and methods of analysis"` | ADV 2A Item 8 제목이 "Methods of Analysis, Investment Strategies and Risk of Loss" |

### 토론 (Backend) — 기획서 문구 그대로
- 운용사당 토론 **1회**. 변화(신호)마다 양측이 논거 + 반증 조건
- 입장 고정: 해지 측은 끝까지 해지 측, 유지 측은 끝까지 유지 측
- 판단 기준: 운용사가 밝힌 전략(ADV Part 2A) 대비
- 유지 측과 해지 측은 **서로 다른 LLM**. 독립 작성 → 반박 2회
- 심판 점수표 10점: 수치 3 · 근거 3 · 반박 2 · 한계 2. 심판에게는 **익명·무작위 순서**로 보여 준다
- 판정: 변화별 설명됨·미설명. 구현은 `유지 측 총점 − 해지 측 총점 ≥ EXPLAINED_MARGIN`(1) 이면 설명됨
- 선택지: 미설명 변화 개수로 결정. 구현은 0건 → 유지 / 1~2건 → 조건부 유지 / 3건 이상 → 해지 검토
- **13F 신호만으로는 해지 검토를 권고하지 않는다:** 미설명 변화가 전부 13F 신호면 조건부 유지로 낮춘다
- 1라운드(반박 1회차)에서 한쪽이 상대에 동의하면 `"토론 불충분"` 경고 (재토론은 하지 않는다. 운용사당 1회)

### 종료·재시도 (PM) — 기획서 문구 그대로
- 종료: 모든 항목 완료 + 검증 통과
- 검증 실패 시 해당 단계부터 재수행, **전체 합쳐 최대 2회**(횟수를 상태에 기록). 초과하면 알림
- 데이터 부족 시 `확인 불가`. 새 공시가 없으면 조기 종료

```python
# src/config.py (요약). "기본값"은 A8 표의 근거를 따른다
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
```

## A9. 데모 모드, 캐시, 배포

- 기본은 **데모 모드(`demo_mode=True`)**: 미리 만들어 둔 `data_cache/demo/<manager_id>/` 파일로 돈다. 네트워크와 API 키가 없어도 끝까지 돌아가야 한다. 시연과 배포본은 이 모드다.
- **실제 모드(`demo_mode=False`)** 는 로컬에서 쓴다: 수집 도구가 SEC에서 실제로 받아오고 LLM을 실제로 호출하며, 결과를 같은 위치에 저장한다. 데모 저장본은 실제 모드를 미리 돌려 만든 것이다.
- 캐시 파일(각 파트가 자기 파일만 쓴다). 각 파일은 `{"fingerprint": <입력 JSON의 sha256>, "result": {...}}` 형태로 저장한다. 입력이 달라졌는데 옛 저장본을 쓰면 `notices` 에 "저장본이 현재 입력과 다름"을 넣는다.

| 파일 | 내용 | 입력(지문 대상) | 파트 |
|---|---|---|---|
| `demo/<id>/manager_data.json` | `ManagerData` | 없음 | Frontend |
| `demo/<id>/analysis.json` | `AnalysisResult` | `manager_data` | Data |
| `demo/<id>/debate.json` | `DebateResult` | `analysis` | Backend |
| `thresholds.json` | 기준값, 계산일, 표본 수 | 없음 | Data |
| `demo/security_master.json` | 종목 식별 결과 (CUSIP별) | 없음 | Data |

- **배포 서버(Streamlit Community Cloud)** 는 메모리가 작고 재시작하면 새로 만든 파일이 사라진다. 그래서:
  - 큰 계산(전체 13F 분포)은 로컬에서 미리 하고 결과 파일만 올린다.
  - `chromadb` 는 배포 서버에 설치하지 않는다(무겁고, 서버의 sqlite 버전과 맞지 않아 오류가 나는 일이 알려져 있다). 근거 검색 결과는 `analysis.json` 에 이미 들어 있으므로 데모 모드에는 필요 없다. `src/rag/` 는 `chromadb` 를 함수 안에서 불러오고, 없으면 빈 목록을 돌려준다.
  - 배포본에서 실제 모드 스위치는 API 키가 secrets에 있을 때만 보인다.

## A10. 일정과 마일스톤

| 날짜 | 마일스톤 | 통과 기준 |
|---|---|---|
| 11/15 | 데이터 형식 확정 | `src/state.py` + `tests/fixtures/` 샘플이 레포에 있고 4개 파트가 같은 샘플로 개발 시작 |
| 11/24 | 파트별 동작 확인 | 수집 도구·찬반 토론·지표 계산·LangGraph 뼈대·리포트 PDF가 각자 샘플 입력으로 돌아감 |
| 11/29 | E2E v0 | 운용사 1곳으로 입력 → 리포트까지 오류 없이 실행 (품질은 낮아도 됨) |
| 12/3 | 본선 진출 발표 | 본선 공지(AI 코드 사용 규정 등)를 함께 확인 |
| 12/5 | 기본값 점검 | A8의 기본값으로 데모 3곳과 분포를 돌려 보고, 근거가 생긴 것만 바꿔 `docs/decisions.md` 에 기록 |
| 12/6 | **데모 완성 (E2E v1)** | 3곳 모두 실제 데이터로 입력 → 리포트 PDF까지 화면에서 실행 |
| 12/13 | **기능 동결** | 이후(시험 기간)에는 버그 수정만 |
| 12/21 | 최종 점검 | 다른 기기에서 데모 URL·GitHub·발표 PDF·시연 영상 확인 후 밤에 제출 |
| 12/22 10:00 | 본선 제출 마감 | |
| 12/29 | 본선 발표 | |

**기획서 ⑥의 1·2·3주차와 실제 일정의 대응**

| 기획서 ⑥ | 그 단계의 완료 조건(기획서) | 실제 기간 | 파트별 할 일 |
|---|---|---|---|
| 1주차 데이터 파이프라인 | 13F 데이터셋 3년 적재·종목 매핑 + 운용사 3곳 ADV 확보(IAPD·SEC 저장본) | 11/13~11/24 | FE 수집 도구·ADV 확보 / Data 종목 식별·13F 데이터셋 적재·지표 계산 / PM 계약·API 키·뼈대·표기 함수 / BE 모델·찬반 토론 v1 |
| 2주차 분석·토론 에이전트 | 기준값 계산·보정(분기당 토론 대상 10% 안팎) + 토론 결과 | 11/22~12/5 | FE 변화 비교 / Data 신호·기준값 / BE 심판·선택지 / PM 노드 연결·리포트·RAG → 11/29 E2E v0 |
| 3주차 리포트·검증·UI 배포 | 데모 URL 작동 + 시연 영상·README | 12/1~12/13 | FE 화면 연결·배포 / Data 검증 / BE 안전장치·프롬프트 고정 / PM 통합 테스트 → 12/6 데모 완성, 12/13 동결 |
| 제출 | 12/22 | 12/14~12/22 | 시험 기간: 버그 수정, 시연 영상, 발표 PDF, 제출 |

기획서의 "1주차"는 단계 이름이고, 실제로는 시작일(11/13)부터 제출일(12/22)까지 약 5주 반 중 기능 개발에 4주(11/13~12/13)를 쓰고 시험 기간을 버퍼로 둔다.

**범위 구분 (기획서 ⑥)**
- Must: 사용자 입력으로 작동 / 3곳 공시 자동 수집 / 13F 지표(분기 변화 + 전체 13F 운용사 대비) / ADV 변경 탐지(Part 1·2A 신·구본 비교) / 운용사별 찬반 토론 + 선택지 3개 / 1장 점검 리포트 + 질문 + 출처 / Streamlit 웹 데모
- 기획서 ④에 적은 기술이라 일정에 넣은 것: 근거 검색(RAG, PM, 12/1~5). 안 되면 Item 8 본문을 직접 쓰는 방식으로 돌아가고 발표에서 밝힌다
- Should(12/13 기능 동결 전에 Must가 전부 끝났을 때만. 그 전에는 시작하지 않는다): 동일 전략 Peer 5곳 정밀 비교(Data), 점검 이력 Memory(PM, SQLite). 못 하면 발표에서 확장 계획으로 말한다

막혔을 때 줄이는 순서: Should 두 개 → RAG → ADV 2A는 Item 2·8만 → 업종·규모 기준값을 임시값으로(발표에서 밝힘). 수집·토론·리포트·화면은 줄이지 않는다.

## A11. 계약 샘플 (예선 기획서 4쪽 예시 화면 기준, 수치는 가상)

```json
{
  "signals": [
    {"id": "demo1-key_person-1", "manager_id": "demo1", "kind": "key_person", "level": "alert",
     "source_form": "ADV", "metric": "officer_removed", "unit": "text",
     "before": null, "after": null, "change": null, "active_change": null,
     "percentile": null, "exceeds_own_3y_max": null, "peer_median": null,
     "summary": "공동 CIO가 임원 명단에서 제외됨",
     "explanation": "최신 ADV Part 1 임원 명단에 직전 본의 공동 CIO가 없습니다.",
     "evidence": [{"source": "Form ADV Part 1A Schedule A", "url": "https://adviserinfo.sec.gov/...", "as_of": "2026-09-30", "page": null, "quote": null}]},
    {"id": "demo1-strategy_drift-1", "manager_id": "demo1", "kind": "strategy_drift", "level": "alert",
     "source_form": "13F", "metric": "small_cap_weight", "unit": "ratio",
     "before": 0.12, "after": 0.27, "change": 0.15, "active_change": 0.14,
     "percentile": 0.97, "exceeds_own_3y_max": true, "peer_median": null,
     "summary": "소형주 비중 12% → 27% (+15%p), 매매 기준 +14%p, 전체 13F 운용사 분기 변화폭 상위 3%",
     "explanation": "소형주 비중이 한 분기에 15%p 늘었고, 그중 14%p가 매매로 생긴 변화입니다.",
     "evidence": [{"source": "Form 13F 2026Q3", "url": "https://www.sec.gov/Archives/edgar/data/...", "as_of": "2026-09-30", "page": null, "quote": null}]},
    {"id": "demo1-peer_anomaly-1", "manager_id": "demo1", "kind": "peer_anomaly", "level": "watch",
     "source_form": "13F", "metric": "peer_level:small_cap_weight", "unit": "ratio",
     "before": null, "after": 0.27, "change": null, "active_change": null,
     "percentile": 0.96, "exceeds_own_3y_max": null, "peer_median": 0.14,
     "summary": "소형주 비중 27%, 전체 13F 운용사 중앙값 14%의 1.9배 (상위 4%)",
     "explanation": "소형주 비중이 다른 운용사들의 중간값보다 1.9배 높습니다.",
     "evidence": [{"source": "Form 13F 2026Q3", "url": "https://www.sec.gov/Archives/edgar/data/...", "as_of": "2026-09-30", "page": null, "quote": null}]}
  ],
  "verdict_example": {"signal_id": "demo1-key_person-1",
     "keep": {"numbers": 1, "grounds": 2, "rebuttal": 1, "limits": 1},
     "terminate": {"numbers": 2, "grounds": 3, "rebuttal": 2, "limits": 1},
     "status": "unexplained", "reason": "후임의 운용 이력 근거가 부족함"}
}
```
위 예시는 신호 3건(경보 2, 관찰 1) → 토론 개시. 유지 측 5점, 해지 측 8점이라 차이가 −3으로 `EXPLAINED_MARGIN`(1) 미만 → 미설명.

### A11-2. 모듈 간 입출력 전체 예시 (`tests/fixtures/` 의 출발점)

아래 다섯 개는 `state.py` 형식 검사(pydantic)를 통과하는 것을 확인한 예시다. 수치·이름은 가상이다. PM은 이것을 `tests/fixtures/*.sample.json` 으로 저장하고, 각 파트는 mock과 테스트에 그대로 쓴다. 이 예시에서는 13F 매핑률이 낮아 업종·규모 지표가 `확인 불가` 이고, ADV 신호 2개(임원 제외 경보, 운용자산 감소 관찰)로 토론이 열린다.

`manager_data.sample.json` (Frontend → Data)
```json
{
 "manager_id": "demo1",
 "manager_name": "Example Capital Management LLC",
 "cik": "0000000000",
 "crd": "000000",
 "quarters": [
  {
   "period": "2026Q2",
   "report_date": "2026-06-30",
   "filed_date": "2026-08-12",
   "accession": "0000000000-26-000001",
   "url": "https://www.sec.gov/Archives/edgar/data/0000000000/000000000026000001/",
   "holdings": [
    {
     "cusip": "037833100",
     "issuer": "APPLE INC",
     "title_of_class": "COM",
     "value_usd": 1000.0,
     "shares": 100.0,
     "ticker": "AAPL",
     "issuer_cik": "0000320193",
     "sic": "3571",
     "shares_outstanding": 15000000000.0,
     "shares_outstanding_partial": false,
     "is_etf": false
    },
    {
     "cusip": "000000002",
     "issuer": "EXAMPLE SMALL CO",
     "title_of_class": "COM",
     "value_usd": 1000.0,
     "shares": 50.0,
     "ticker": "EXSM",
     "issuer_cik": "0000000002",
     "sic": "7372",
     "shares_outstanding": 50000000.0,
     "shares_outstanding_partial": false,
     "is_etf": false
    }
   ]
  },
  {
   "period": "2026Q3",
   "report_date": "2026-09-30",
   "filed_date": "2026-11-13",
   "accession": "0000000000-26-000002",
   "url": "https://www.sec.gov/Archives/edgar/data/0000000000/000000000026000002/",
   "holdings": [
    {
     "cusip": "037833100",
     "issuer": "APPLE INC",
     "title_of_class": "COM",
     "value_usd": 1200.0,
     "shares": 100.0,
     "ticker": "AAPL",
     "issuer_cik": "0000320193",
     "sic": "3571",
     "shares_outstanding": 15000000000.0,
     "shares_outstanding_partial": false,
     "is_etf": false
    },
    {
     "cusip": "000000002",
     "issuer": "EXAMPLE SMALL CO",
     "title_of_class": "COM",
     "value_usd": 500.0,
     "shares": 25.0,
     "ticker": "EXSM",
     "issuer_cik": "0000000002",
     "sic": "7372",
     "shares_outstanding": 50000000.0,
     "shares_outstanding_partial": false,
     "is_etf": false
    },
    {
     "cusip": "000000003",
     "issuer": "EXAMPLE NEW CO",
     "title_of_class": "COM",
     "value_usd": 400.0,
     "shares": 10.0,
     "ticker": null,
     "issuer_cik": null,
     "sic": null,
     "shares_outstanding": null,
     "shares_outstanding_partial": false,
     "is_etf": false
    }
   ]
  }
 ],
 "holding_changes": [
  {
   "cusip": "000000003",
   "issuer": "EXAMPLE NEW CO",
   "ticker": null,
   "kind": "new",
   "shares_before": 0.0,
   "shares_after": 10.0,
   "value_before": 0.0,
   "value_after": 400.0,
   "weight_before": 0.0,
   "weight_after": 0.1905
  }
 ],
 "adv1_new": {
  "filed_date": "2026-03-30",
  "url": "https://adviserinfo.sec.gov/firm/summary/000000",
  "crd": "000000",
  "aum_usd": 7800000000.0,
  "employees": 28,
  "private_funds": 4,
  "people": [
   {
    "name": "KIM, JANE",
    "entity_type": "I",
    "title": "CHIEF INVESTMENT OFFICER",
    "since": "2019-01",
    "ownership_code": "C",
    "is_control_person": true
   }
  ]
 },
 "adv1_old": {
  "filed_date": "2025-03-28",
  "url": "https://www.sec.gov/foia-services/frequently-requested-documents/form-adv-data",
  "crd": "000000",
  "aum_usd": 12000000000.0,
  "employees": 40,
  "private_funds": 4,
  "people": [
   {
    "name": "KIM, JANE",
    "entity_type": "I",
    "title": "CHIEF INVESTMENT OFFICER",
    "since": "2019-01",
    "ownership_code": "C",
    "is_control_person": true
   },
   {
    "name": "LEE, JOHN",
    "entity_type": "I",
    "title": "CO-CHIEF INVESTMENT OFFICER",
    "since": "2015-06",
    "ownership_code": "B",
    "is_control_person": true
   }
  ]
 },
 "adv2a_new": {
  "filed_date": "2026-03-30",
  "url": "https://adviserinfo.sec.gov/firm/summary/000000",
  "items": {
   "2": "There have been no material changes since our last annual update.",
   "8": "We invest primarily in U.S. large-capitalization equities..."
  },
  "pages": {
   "2": 2,
   "8": 9
  }
 },
 "adv2a_old": null,
 "person_changes": [
  {
   "kind": "removed",
   "name": "LEE, JOHN",
   "before": {
    "name": "LEE, JOHN",
    "entity_type": "I",
    "title": "CO-CHIEF INVESTMENT OFFICER",
    "since": "2015-06",
    "ownership_code": "B",
    "is_control_person": true
   },
   "after": null,
   "evidence": [
    {
     "source": "Form ADV Part 1A Schedule A",
     "url": "https://adviserinfo.sec.gov/firm/summary/000000",
     "as_of": "2026-03-30",
     "page": null,
     "quote": null
    },
    {
     "source": "Form ADV Part 1A Schedule A (직전본)",
     "url": "https://www.sec.gov/foia-services/frequently-requested-documents/form-adv-data",
     "as_of": "2025-03-28",
     "page": null,
     "quote": null
    }
   ]
  }
 ],
 "text_changes": [],
 "item2_declares_no_change": true,
 "has_new_filing": true,
 "notes": [
  "ADV 최신본: 저장본 사용"
 ],
 "unavailable": [
  "ADV 2A 문구 비교: 이전본 없음"
 ],
 "fetched_at": "2026-11-20T10:00:00+09:00"
}
```

`analysis.sample.json` (Data → Backend)
```json
{
 "manager_id": "demo1",
 "signals": [
  {
   "id": "demo1-key_person-1",
   "manager_id": "demo1",
   "kind": "key_person",
   "level": "alert",
   "source_form": "ADV",
   "metric": "officer_removed",
   "unit": "text",
   "before": null,
   "after": null,
   "change": null,
   "active_change": null,
   "percentile": null,
   "exceeds_own_3y_max": null,
   "peer_median": null,
   "summary": "임원 1명 제외: LEE, JOHN(공동 CIO)",
   "explanation": "최신 ADV 임원 명단에 직전 본의 공동 CIO가 없습니다.",
   "evidence": [
    {
     "source": "Form ADV Part 1A Schedule A",
     "url": "https://adviserinfo.sec.gov/firm/summary/000000",
     "as_of": "2026-03-30",
     "page": null,
     "quote": null
    },
    {
     "source": "Form ADV Part 1A Schedule A (직전본)",
     "url": "https://www.sec.gov/foia-services/frequently-requested-documents/form-adv-data",
     "as_of": "2025-03-28",
     "page": null,
     "quote": null
    }
   ]
  },
  {
   "id": "demo1-strategy_drift-1",
   "manager_id": "demo1",
   "kind": "strategy_drift",
   "level": "watch",
   "source_form": "ADV",
   "metric": "aum_change",
   "unit": "usd",
   "before": 12000000000.0,
   "after": 7800000000.0,
   "change": -4200000000.0,
   "active_change": null,
   "percentile": null,
   "exceeds_own_3y_max": null,
   "peer_median": null,
   "summary": "운용자산 $12B → $7.8B (-35%), ADV 제출일 2025-03-28 → 2026-03-30",
   "explanation": "1년 사이 운용자산이 35% 줄었습니다.",
   "evidence": [
    {
     "source": "Form ADV Part 1A Schedule A",
     "url": "https://adviserinfo.sec.gov/firm/summary/000000",
     "as_of": "2026-03-30",
     "page": null,
     "quote": null
    }
   ]
  }
 ],
 "debate_required": true,
 "stated_strategy": "미국 대형주 중심의 주식 운용",
 "stated_strategy_evidence": [
  {
   "source": "Form ADV Part 2A Item 8",
   "url": "https://adviserinfo.sec.gov/firm/summary/000000",
   "as_of": "2026-03-30",
   "page": 9,
   "quote": "We invest primarily in U.S. large-capitalization equities"
  }
 ],
 "data_checks": [
  "매핑률 81%: 업종·규모 지표 확인 불가",
  "직전 변화 1개: 자기 3년 최대치 판정 불가"
 ],
 "unavailable": [
  "업종 지표: 매핑률 81%"
 ]
}
```

`debate.sample.json` (Backend → PM). 판정: 신호 1은 유지 5점·해지 8점, 신호 2는 유지 6점·해지 6점(동점) → 둘 다 미설명 → 2건이라 조건부 유지.
```json
{
 "manager_id": "demo1",
 "held": true,
 "rounds": 2,
 "keep_args": [
  {
   "signal_id": "demo1-key_person-1",
   "claim": "CIO가 남아 있어 의사결정 연속성은 유지됩니다.",
   "evidence_idx": [
    0
   ],
   "falsifier": "남은 CIO가 공동 CIO의 운용 자산을 넘겨받지 않았다면 이 논거는 약해집니다."
  },
  {
   "signal_id": "demo1-strategy_drift-1",
   "claim": "운용자산 감소는 시장 하락 때문일 수 있습니다.",
   "evidence_idx": [
    0
   ],
   "falsifier": "같은 기간 시장이 오른 것이 확인되면 이 논거는 틀립니다."
  }
 ],
 "terminate_args": [
  {
   "signal_id": "demo1-key_person-1",
   "claim": "공동 CIO 이탈과 운용자산 -35%가 같은 시기에 나타났습니다.",
   "evidence_idx": [
    0
   ],
   "falsifier": "이탈 전에 자금 유출이 끝났다면 이 연결은 약해집니다."
  },
  {
   "signal_id": "demo1-strategy_drift-1",
   "claim": "운용자산이 $12B에서 $7.8B로 줄어 고객 이탈 가능성이 있습니다.",
   "evidence_idx": [
    0
   ],
   "falsifier": "감소분 대부분이 시장 하락으로 설명되면 이 논거는 약해집니다."
  }
 ],
 "rebuttals": [
  {
   "round": 1,
   "side": "keep",
   "signal_id": "demo1-key_person-1",
   "text": "후임 지정 여부가 확인되지 않았을 뿐 이탈 자체가 전략 변경은 아닙니다.",
   "concede": false
  },
  {
   "round": 1,
   "side": "terminate",
   "signal_id": "demo1-key_person-1",
   "text": "후임이 확인되지 않은 것 자체가 위험입니다.",
   "concede": false
  }
 ],
 "verdicts": [
  {
   "signal_id": "demo1-key_person-1",
   "keep": {
    "numbers": 1,
    "grounds": 2,
    "rebuttal": 1,
    "limits": 1
   },
   "terminate": {
    "numbers": 2,
    "grounds": 3,
    "rebuttal": 2,
    "limits": 1
   },
   "status": "unexplained",
   "reason": "후임의 운용 이력 근거가 부족함"
  },
  {
   "signal_id": "demo1-strategy_drift-1",
   "keep": {
    "numbers": 1,
    "grounds": 2,
    "rebuttal": 1,
    "limits": 2
   },
   "terminate": {
    "numbers": 2,
    "grounds": 2,
    "rebuttal": 1,
    "limits": 1
   },
   "status": "unexplained",
   "reason": "시장 요인 근거가 제시되지 않음"
  }
 ],
 "unexplained_count": 2,
 "recommendation": "conditional",
 "options": [
  {
   "name": "maintain",
   "recommended": false,
   "grounds": []
  },
  {
   "name": "conditional",
   "recommended": true,
   "grounds": [
    "남은 CIO가 공동 CIO의 운용 자산을 넘겨받지 않았다면 이 논거는 약해집니다. [demo1-key_person-1]",
    "같은 기간 시장이 오른 것이 확인되면 이 논거는 틀립니다. [demo1-strategy_drift-1]"
   ]
  },
  {
   "name": "review_termination",
   "recommended": false,
   "grounds": [
    "공동 CIO 이탈과 운용자산 -35%가 같은 시기에 나타났습니다. [demo1-key_person-1]"
   ]
  }
 ],
 "questions": [
  "[핵심 인력] 공동 CIO가 맡던 운용 자산은 누가 넘겨받았습니까?",
  "[핵심 인력] 투자 의사결정은 누가 최종 승인합니까?",
  "[전략 이탈] 운용자산 감소 중 고객 자금 유출분은 얼마입니까?"
 ],
 "warnings": [],
 "models": {
  "keep": "<MODEL_KEEP>",
  "terminate": "<MODEL_TERMINATE>",
  "judge": "<MODEL_JUDGE>"
 }
}
```

`draft.sample.json` (PM → Data 검증)
```json
{
 "manager_id": "demo1",
 "period": "2026H2",
 "as_of": "2026-11-20",
 "sentences": [
  {
   "section": "recommendation",
   "text": "변화 2건 중 미설명 2건 → 조건부 유지",
   "kind": "opinion",
   "signal_ids": [
    "demo1-key_person-1",
    "demo1-strategy_drift-1"
   ],
   "evidence": []
  },
  {
   "section": "changes",
   "text": "임원 1명 제외: LEE, JOHN(공동 CIO)",
   "kind": "fact",
   "signal_ids": [
    "demo1-key_person-1"
   ],
   "evidence": [
    {
     "source": "Form ADV Part 1A Schedule A",
     "url": "https://adviserinfo.sec.gov/firm/summary/000000",
     "as_of": "2026-03-30",
     "page": null,
     "quote": null
    },
    {
     "source": "Form ADV Part 1A Schedule A (직전본)",
     "url": "https://www.sec.gov/foia-services/frequently-requested-documents/form-adv-data",
     "as_of": "2025-03-28",
     "page": null,
     "quote": null
    }
   ]
  },
  {
   "section": "changes",
   "text": "운용자산 $12B → $7.8B (-35%), ADV 제출일 2025-03-28 → 2026-03-30",
   "kind": "fact",
   "signal_ids": [
    "demo1-strategy_drift-1"
   ],
   "evidence": [
    {
     "source": "Form ADV Part 1A Schedule A",
     "url": "https://adviserinfo.sec.gov/firm/summary/000000",
     "as_of": "2026-03-30",
     "page": null,
     "quote": null
    }
   ]
  },
  {
   "section": "debate",
   "text": "심판: 유지 측 5점, 해지 측 8점 → 미설명. 후임의 운용 이력 근거가 부족함",
   "kind": "opinion",
   "signal_ids": [
    "demo1-key_person-1"
   ],
   "evidence": []
  }
 ],
 "sources": [
  {
   "source": "Form ADV Part 1A Schedule A",
   "url": "https://adviserinfo.sec.gov/firm/summary/000000",
   "as_of": "2026-03-30",
   "page": null,
   "quote": null
  }
 ]
}
```

`verify.sample.json` (Data → PM). 3번 문장에 심판 점수에 없는 `9점` 이 있다고 가정한 실패 예시.
```json
{
 "passed": false,
 "failed_step": "debate",
 "mismatches": [
  {
   "sentence_idx": 3,
   "token": "9점",
   "reason": "심판 점수에 없는 숫자"
  }
 ],
 "unsupported_idx": [],
 "uncited_signals": []
}
```

## A12. AI와 작업하는 규칙 (바이브코딩 안전수칙)

팀원 대부분이 AI 코딩 도구로 구현한다. 아래는 AI가 그럴듯하게 틀리는 지점을 막기 위한 규칙이다.

1. **한 번에 한 기능.** 테스트를 먼저 쓰고, 통과하면 커밋하고, 다음 기능으로 간다. 한 번에 여러 파일을 크게 만들지 않는다.
2. **추측 금지 목록:** 외부 주소(URL), 파일의 열 이름, API 응답 필드, 모델 ID, 라이브러리 함수 이름. 이 문서에 "확인 필요"라고 적힌 것과 문서에 없는 것은 **실제로 한 번 호출해 본 결과**를 보고 쓴다. 확인한 내용은 `docs/verified.md` 에 날짜와 함께 적는다.
3. **라이브러리는 설치된 버전 기준.** `pip show <이름>` 으로 버전을 확인하고 그 버전의 공식 문서를 따른다. 특히 `langgraph`, `streamlit`, `anthropic`, `openai` 는 버전에 따라 쓰는 법이 다르다.
4. **계약과 다른 모양이 필요해지면 멈춘다.** A6·A7을 바꾸지 말고 사용자(담당자)에게 알린다.
5. **숫자를 계산하는 코드는 손 계산 예시 테스트 없이는 합치지 않는다.** 돌아가는데 값이 조용히 틀리는 경우가 가장 위험하다.
6. **개발 중에는 `LLM_MOCK=1`.** 실제 LLM 호출은 돈이 든다. 실제 호출 결과는 저장해 두고 다시 쓴다.
7. **담당자가 설명할 수 있어야 한다.** 기능 하나가 끝나면 `docs/notes/<파트>.md` 에 "무엇을 하는가 / 어떻게 하는가 / 한계" 3줄을 남긴다. 발표 질의응답에서 본인이 답해야 한다.
8. AI가 만든 코드가 A4의 절대 규칙(숫자는 코드, 출처, 확인 불가, 비밀값)을 어기지 않는지 PR 전에 본인이 확인한다.
9. **구조는 단순하게.** `async`/`await`, 스레드, 멀티프로세싱, 데이터베이스 서버, 클래스 상속 계층을 쓰지 않는다. 모든 단계는 동기 함수이고, 단계 사이에는 `state.py` 의 dict만 오간다. 저장은 JSON 파일(Memory를 하게 되면 그때만 SQLite).
10. 전역 변수에 실행 상태를 담지 않는다(Streamlit은 화면을 다시 그릴 때마다 코드를 처음부터 다시 실행한다). 실행 결과는 `st.session_state` 에만 둔다.
11. 네트워크 호출은 `src/collect/sec_client.py`(SEC), `src/analysis/securities.py`(OpenFIGI), `src/llm.py`(LLM) 세 파일 안에서만 한다. 다른 파일이 `requests` 를 직접 부르지 않는다.

---

# B. Data 파트 상세

## B1. 만들 것과 일정

| 기간 | 업무 | 난이도 | 완료 기준 |
|---|---|---|---|
| 11/13~14 | 지표 정의 | ★ | B2의 계산식과 손 계산 예시를 `docs/metrics.md` 로 옮기고 본인이 직접 계산해 확인 |
| 11/15~18 | 종목 식별 도구 (B3-1) | ★★ | CUSIP 목록을 넣으면 티커·CIK·업종·발행주식 수가 나오고, 못 찾은 건 `None`, 예외 없음. Frontend가 11/19부터 부른다 |
| 11/19~23 | 지표 계산 + 13F 데이터셋 적재 | ★★★ | 손 계산 예시가 그대로 테스트로 통과 / 13F 데이터셋 15개 파일을 받아 분기별로 읽는 함수가 돈다 (기획서 ⑥ 1주차 "13F 데이터셋 3년 적재·종목 매핑") |
| 11/24~28 | 신호 판정·설명 | ★★★ | 신호 JSON(등급·설명·근거)이 그대로 토론 입력으로 들어감 |
| 11/29~12/5 | 기준값 보정 | ★★★ | `thresholds.json` 을 실제 분포로 생성, 분기당 토론 대상 비율 확인, Peer 대비 신호 |
| 12/6~13 | **검증 에이전트** | ★★★★ | 틀린 숫자·인용을 찾아 표시하고 다시 실행할 단계를 알려 줌 |
| 12/14~17 | 숫자 검수 | | 3곳의 화면·PDF 숫자를 SEC 원문과 직접 대조 |

마일스톤: 11/24 지표 계산이 혼자 돌아감 → 11/29 E2E v0(임시 기준값으로 연결) → 12/6 데모 완성 → 12/13 기능 동결.

## B2. 지표 정의 — 계산식은 여기 적힌 그대로 구현한다

### 준비 (한 분기의 보유 표)
1. `is_etf=True` 인 종목을 뺀다(기획서 ⑤ 전처리). 옵션·원금 행은 Frontend가 이미 뺐다.
2. 주가 `price = value_usd ÷ shares`. 전체 금액 `V = Σ value_usd`. 비중 `w = value_usd ÷ V`.
3. 시가총액 `mcap = price × shares_outstanding`. 규모 구간: `mcap < 20억 달러` 소형 / `20억 ≤ mcap < 100억` 중형 / `100억 ≤ mcap` 대형 (`config.SIZE_BOUNDS_USD`).
4. 업종: `sic` 앞 두 자리로 SIC 공식 대분류 10개 중 하나에 넣는다(`src/analysis/sectors.py` 한 곳에 둔다).

   | SIC 앞 두 자리 | 업종 | | SIC 앞 두 자리 | 업종 |
   |---|---|---|---|---|
   | 01~09 | 농림어업 | | 50~51 | 도매 |
   | 10~14 | 광업 | | 52~59 | 소매 |
   | 15~17 | 건설 | | 60~67 | 금융·보험·부동산 |
   | 20~39 | 제조 | | 70~89 | 서비스 |
   | 40~49 | 운송·통신·전기가스 | | 91~99 | 공공·기타 |

   한계: 대분류라 거칠다(반도체와 제약이 둘 다 제조, 소프트웨어는 서비스). 더 세밀한 분류가 필요하면 두 자리 코드 단위로 바꿀 수 있게 표를 한 파일에만 둔다. 바꿀 때는 PM과 상의한다.
5. **데이터 검사(기획서 ⑤ 매핑률):**
   - 매핑률 = `issuer_cik` 가 있는 종목의 금액 합 ÷ V. `config.MIN_MAPPING_RATE`(0.95) 미만이면 업종·규모 지표는 계산하지 않고 `unavailable` 에 "업종·규모 지표: 매핑률 91%" 처럼 적는다.
   - 규모는 추가로, 시가총액 구간을 정할 수 있는 종목의 금액 합 ÷ V 가 `config.MIN_SIZE_COVERAGE`(0.90) 미만이면 `확인 불가`. 구간을 정할 수 없는 종목: `shares_outstanding=None`, 또는 `shares_outstanding_partial=True` 인데 하한값으로 계산한 시가총액이 100억 달러 미만인 경우(실제 값을 모르므로).
   - 기준을 넘으면 값을 못 찾은 종목은 "미분류"로 두고 비중 계산의 분모에는 남긴다. 집중도·회전율은 종목 식별이 필요 없어 항상 계산한다.

### 주식 분할 보정 (두 분기 모두 보유한 종목마다)
주가 변화 `c = price_now ÷ price_prev`.
1. 두 분기 모두 `shares_outstanding` 이 있으면 `k = so_now ÷ so_prev`. `k ≥ 1.4` 또는 `k ≤ 1/1.4` 이고 `0.7 ≤ c × k ≤ 1.4` 이면 **분할**로 본다 → `shares_prev × k`, `price_prev ÷ k` 로 맞춘다.
2. 1에 해당하지 않고 발행주식 수를 몰라 확인할 수 없는데 `c < 0.55` 또는 `c > 1.8` 이면 **분할 여부 확인 불가**로 본다 → 그 종목은 매매가 없었던 것으로 둔다(`shares_prev := shares_now`).
3. 보정하거나 제외한 종목은 `data_checks` 에 "분할 보정: XYZ ×2" / "가격 급변으로 매매 계산 제외: XYZ" 로 적는다.

상수는 `config` 의 `SPLIT_SO_RATIO`, `SPLIT_CAP_BAND`, `PRICE_JUMP_BAND` (A8 기본값). 예: 2대1 분할이면 `k = 2`, 주가가 10달러 → 5.5달러면 `c = 0.55`, `c × k = 1.1` → 분할. 한계: 발행주식 수를 모르는 종목의 3대2 분할(`c ≈ 0.67`)은 잡지 못한다.

### 매매 기준 변화 (`active_change`) — 기획서 ⑤ "매매 변화만 신호"
```
passive 금액_i = (보정한) 직전 주식 수_i × 최신 주가_i        # 그대로 들고 있었다면
                 최신 분기에 없는 종목(전량 매도)은 최신 주가 대신 직전 주가를 쓴다
passive 비중_i = passive 금액_i ÷ Σ passive 금액
active_change(묶음) = Σ 실제 최신 비중 − Σ passive 비중       # 묶음 = 업종, 규모 구간, 상위 10종목
```
실제 체결 가격은 13F로 알 수 없으므로 분기 말 가격으로 근사한다는 한계를 `docs/metrics.md` 에 적는다.

### 지표별 정의
| 기준값 이름 | 계산 | 신호에 넣는 값 |
|---|---|---|
| `sector_shift` | 업종별 `active_change` 를 구해 절댓값이 가장 큰 업종 g를 고른다. 변화폭 = `|active_change_g|` | `metric="sector_weight:<g>"`, `before`·`after` = g의 실제 비중, `change = after − before`, `active_change` |
| `size_shift` | 소형·중형·대형별 `active_change` 중 절댓값이 가장 큰 구간. 변화폭 = 그 절댓값 | `metric="small_cap_weight"` 등, 위와 같음 |
| `concentration_change` | `top10(비중)` = 비중이 큰 10종목의 합(종목이 10개 미만이면 전부). 변화폭 = `|top10(실제 최신 비중) − top10(passive 비중)|` | `metric="top10_concentration"`, `before`·`after` = 실제 top10 |
| `turnover` | 종목별 `Δ = shares_now − (보정한) shares_prev`. 매수액 = `Σ max(Δ, 0) × price_now`, 매도액 = `Σ max(−Δ, 0) × price_prev`. `turnover = min(매수액, 매도액) ÷ ((V_prev + V_now) ÷ 2)`. 변화폭 = `turnover` 자체 | `metric="turnover"`, `after` = 이번 분기 회전율, `before` = 직전 분기 회전율, `active_change=None` |

`min(매수액, 매도액)` 을 쓰는 이유: 고객 자금이 들어오거나 나가서 생긴 매매를 빼고 "종목을 바꾼 정도"만 보기 위해서다(펀드 회전율의 표준 정의).

### 손 계산 예시 (이 숫자가 그대로 테스트가 된다)
직전 분기: A 100주 × 10달러 = 1,000 / B 50주 × 20달러 = 1,000 → V = 2,000 (A 50%, B 50%)
최신 분기: A 100주 × 12달러 = 1,200 / B 25주 × 20달러 = 500 / C 10주 × 40달러 = 400 → V = 2,100

| | 실제 최신 비중 | passive 금액 | passive 비중 | active_change |
|---|---|---|---|---|
| A | 1,200 ÷ 2,100 = 57.1% | 100 × 12 = 1,200 | 1,200 ÷ 2,200 = 54.5% | +2.6%p |
| B | 500 ÷ 2,100 = 23.8% | 50 × 20 = 1,000 | 1,000 ÷ 2,200 = 45.5% | −21.6%p |
| C | 400 ÷ 2,100 = 19% | 0 | 0% | +19%p |

- 회전율: 매수액 = C 10주 × 40 = 400, 매도액 = B 25주 × 20 = 500 → `min = 400`, 평균 금액 = (2,000 + 2,100) ÷ 2 = 2,050 → 400 ÷ 2,050 = **19.5%**
- A·B가 대형, C가 소형이면: 소형 `active_change` = +19%p, 대형 = (57.1% + 23.8%) − 100% = −19%p → `size_shift` = 19%, 절댓값이 같으므로 소형 → 중형 → 대형 순서에서 앞선 소형으로 신호를 낸다
- A는 사고팔지 않았는데 +2.6%p인 이유: B를 500 팔고 C를 400만 사서 전체 금액이 줄었기 때문이다. 비중은 상대값이라 생기는 효과이고 오류가 아니다.
- 테스트에는 반올림 전 값도 넣는다: A `0.0259740…`, B `−0.2164502…`, C `0.1904762…`, 회전율 `0.1951220…` (허용 오차 1e-6)

## B3. 지표 계산 (11/19~23) — `src/analysis/metrics.py`, `splits.py`, `sectors.py`

```python
def prepare(q: QuarterHoldings) -> pd.DataFrame: ...                      # 준비 1~4 + 커버리지
def adjust_splits(prev: pd.DataFrame, curr: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]: ...
def compute_changes(prev: QuarterHoldings, curr: QuarterHoldings) -> dict[str, dict]: ...
    # {"sector_shift": {"metric":..., "before":..., "after":..., "change":..., "active_change":..., "magnitude":...}, ...}
```
- pandas로 구현한다. 비율은 0~1로 저장하고 반올림하지 않는다(반올림은 표기할 때 `format.py` 가 한다).
- 개발용 데이터: Frontend의 수집 도구가 나오기 전에는 `tests/fixtures/manager_data.sample.json` 과 손 계산 예시를 쓴다.

## B3-1. 종목 식별 도구 (11/15~18) — `src/analysis/securities.py` (`enrich_cusips(cusips, as_of)`)

13F의 종목은 CUSIP(미국 증권 고유번호 9자리)로만 나온다. 이 도구가 CUSIP을 회사 정보(티커, 발행사 CIK, 업종 SIC, 발행주식 수, ETF·예탁증서 여부)로 바꾼다. 원래 Frontend 업무였는데 11/12에 Data로 옮겼다(기준값 계산에서 대량으로 쓰고, 기획서 역할 분담에서도 종목 매핑은 데이터 담당). Frontend의 `collect` 와 내 기준값 스크립트가 둘 다 이 함수를 쓴다.

- SEC 주소(④~⑥)는 Frontend의 `sec_get`(A7)으로 부른다. 조재연이 11/16까지 올리기로 했으니, 그 전에는 테스트에서 가짜 `sec_get` 을 쓴다. OpenFIGI(①)는 이 파일에서 `requests` 로 직접 부른다(A12-11).
- 11/16에 OpenFIGI로 ETF·보통주·예탁증서를 하나씩 실제 조회해 종목 유형 값을 `docs/verified.md` 에 적는다(③).

**이 함수는 절대 예외를 던지지 않는다.** 단계마다 실패하면 그 값만 `None` 으로 두고 다음 종목으로 넘어간다. 실패 내역은 `data_cache/raw/enrich_log.jsonl` 에 한 줄씩 남긴다(CUSIP, 실패 단계, 사유).

| 단계 | 방법 | 실패하면 |
|---|---|---|
| ① CUSIP → 티커·종목 유형 | OpenFIGI `POST https://api.openfigi.com/v3/mapping`, 본문 `[{"idType": "ID_CUSIP", "idValue": "<CUSIP>"}, ...]`. 키 없이 분당 25요청·요청당 10건, 키가 있으면(`X-OPENFIGI-APIKEY` 헤더) 분당 250요청·요청당 100건. 응답은 요청 순서대로 한 줄씩 `{"data": [...]}` 또는 `{"warning": ...}`/`{"error": ...}` | `warning`/`error` → 티커 `None`. HTTP 429(요청 과다) → 1분 쉬고 다시(3회까지). 3회 실패 → 그 묶음 전체 `None` |
| ② 여러 결과 중 고르기 | `data` 중 `exchCode == "US"` 인 것을 먼저, 없으면 첫 번째 | |
| ③ ETF·예탁증서 판별 | OpenFIGI 결과의 종목 유형 필드로 판별. **값은 추측하지 말고** ETF 하나(SPDR S&P 500 ETF, CUSIP `78462F103`)와 보통주 하나(Apple, `037833100`)를 실제로 조회해 어떤 필드·값이 다른지 확인하고 `docs/verified.md` 에 적는다. 예탁증서(ADR)도 같은 방법으로 하나 확인 | ① 실패 시 `nameOfIssuer` 에 단어 `ETF` 가 있으면 `is_etf=True`, 아니면 `False` |
| ④ 티커 → 발행사 CIK | `https://www.sec.gov/files/company_tickers.json`(필드 `cik_str`, `ticker`). 티커는 대문자로, `/` 는 `-` 로 바꿔 맞춘다(OpenFIGI `BRK/B` ↔ SEC `BRK-B`) | 못 찾으면 `issuer_cik=None` → 매핑 실패로 계산됨 |
| ⑤ CIK → 업종(SIC) | `https://data.sec.gov/submissions/CIK{10자리}.json` 의 `sic` | 빈 문자열·없음 → `None` |
| ⑥ 발행주식 수 | `https://data.sec.gov/api/xbrl/companyconcept/CIK{10자리}/dei/EntityCommonStockSharesOutstanding.json` → 404면 `.../us-gaap/CommonStockSharesOutstanding.json`. 응답의 `units["shares"]` 목록에서 아래 `pick_shares_outstanding` 으로 고른다 | 둘 다 없음 → `None`. **예탁증서는 이 단계를 건너뛰고 `None`**(예탁증서 1주와 원주 1주가 달라 시가총액이 틀어진다) |

```python
from datetime import date
from src.config import SHARES_OUT_MAX_GAP_DAYS

def pick_shares_outstanding(facts: list[dict], as_of: str):
    """XBRL companyconcept 응답의 units["shares"] 목록 → (값, partial).
    as_of 와 기준일(end) 차이가 SHARES_OUT_MAX_GAP_DAYS 이내인 것 중 가장 가까운 날짜.
    그 날짜에 서로 다른 값이 여러 개면 주식 종류별 값으로 보고 가장 큰 값을 '하한값'(partial=True)으로."""
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
```

- 여러 종류 주식(예: A주·C주)을 발행한 회사는 종류별 값만 있어 합계를 모를 수 있다. 그때는 가장 큰 값을 **하한값**으로 쓰고 `shares_outstanding_partial=True` 로 표시한다. 지표 계산(B2 준비 5)에서는 하한값으로 계산한 시가총액이 대형 경계(100억 달러) 이상일 때만 "대형"으로 쓰고, 그보다 작으면 "미분류"로 둔다(실제 값은 더 크므로 대형이라는 판단만 안전하다).
- 한 번 찾은 결과는 `data_cache/demo/security_master.json` 에 저장한다. 티커·CIK·SIC·유형은 CUSIP별, 발행주식 수는 CUSIP + 분기 말일별.
- 반환 형태: `{"<CUSIP>": {"ticker": str|None, "issuer_cik": str|None, "sic": str|None, "shares_outstanding": float|None, "shares_outstanding_partial": bool, "is_etf": bool}}`.

테스트 (`tests/analysis/test_securities.py`, 네트워크 없이 가짜 응답으로):
- [ ] 같은 CUSIP을 두 번 물으면 두 번째는 네트워크 호출이 0회
- [ ] OpenFIGI가 `{"warning": ...}` 를 주거나 SEC가 404를 줘도 예외 없이 해당 값만 `None`, 로그에 한 줄
- [ ] 티커 `BRK/B` 가 SEC 목록의 `BRK-B` 와 맞음
- [ ] `pick_shares_outstanding`: 같은 날짜 값 2개(150, 90) → `(150, True)` / 120일 밖 값만 있음 → `(None, False)`
- [ ] 예탁증서로 판별된 종목은 발행주식 수 조회를 하지 않고 `None`
- [ ] OpenFIGI 실패 + 종목명에 `ETF` → `is_etf=True`

## B4. 신호 판정과 설명 (11/24~28)

### 판정 — `src/analysis/signals.py` (`detect_signals(data) -> list[Signal]`, LLM 없음)
`data.quarters` 의 이웃한 분기 쌍마다 `compute_changes` 를 돌려 변화폭의 시계열을 만든다. 맨 마지막이 이번 분기다.

```
13F 지표마다 (sector_shift, size_shift, concentration_change, turnover):
  m    = 이번 분기 변화폭
  pct  = 전체 13F 운용사 분포에서 m의 위치 (thresholds.json 으로 계산)
  own  = 이번 분기를 뺀 직전 최대 12개 변화폭의 최댓값 (4개 미만이면 판정 불가)
  경보(alert) : pct >= 0.95
  관찰(watch) : 0.90 <= pct < 0.95 이고 m > own
  그 밖       : 신호 없음
  관찰 범위(0.90 <= pct < 0.95)인데 own 을 판정할 수 없으면: 신호 없음 + unavailable 에 기록 (경보는 own 과 무관)

ADV:
  person_changes 를 종류별로 묶어 신호 1개씩 → 경보
    개인의 added → "officer_added", removed → "officer_removed", title_changed → "title_changed"
    법인의 added/removed 와 모든 ownership_changed → "owner_changed"
  text_changes 중 item "8" 에 material=True 가 있으면 → "strategy_text_changed" 관찰
  item2_declares_no_change 가 True 인데 item "8" 에 material=True 가 있으면 → "item2_mismatch" 관찰

ADV Part 1 규모 (adv1_old 와 adv1_new 가 둘 다 있고 값이 None 이 아닐 때만):
  r = (new.aum_usd - old.aum_usd) / old.aum_usd
  r <= -AUM_DROP(0.30) 또는 r >= AUM_JUMP(1.00)              → "aum_change" 관찰 (unit="usd")
  d = old.employees - new.employees
  d >= EMPLOYEE_DROP_MIN(3) 이고 d / old.employees >= EMPLOYEE_DROP_RATE(0.20)  → "employee_drop" 관찰 (unit="count")
  e = |new.private_funds - old.private_funds|
  e >= PRIVATE_FUND_MIN_DIFF(2) 이고 e / max(old.private_funds, 1) >= PRIVATE_FUND_RATE(0.25) → "private_fund_change" 관찰 (unit="count")
  (old 값이 0이면 운용자산·직원 비율을 계산하지 않고 신호도 내지 않는다)

Peer 대비 (11/29~12/5에 추가):
  PEER_LEVEL_METRICS 의 지표 수준이 전체 분포의 위 5% 또는 아래 5% → "peer_level:<지표>" 관찰 (kind="peer_anomaly")
  peer_median = levels[<지표>]["p50"], before/change/active_change = None

토론 개시:
  debate_required = (경보 수 >= 1) or (관찰 수 >= 2)
```
- `kind`: A8 표를 따른다. 13F 변화 지표·`strategy_text_changed`·`item2_mismatch`·`aum_change`·`private_fund_change` 는 `strategy_drift`, 임원·소유주·`employee_drop` 은 `key_person`, 수준 비교는 `peer_anomaly`.
- ADV Part 1 규모 신호의 `summary` 예: `"운용자산 $12B → $7.8B (-35%), ADV 제출일 2025-03-28 → 2026-03-30"`, `"직원 40명 → 28명 (-30%), …"`, `"사모펀드 4개 → 7개, …"`. `before`·`after` 에 원래 값(달러 또는 명·개 수), `change = after − before`.
- 같은 종류의 임원 변경이 여러 명이면 신호 하나에 이름을 모두 넣는다(예: "임원 2명 제외: A(공동 CIO), B(COO)"). 직함을 꼭 적는다.
- 기획서대로 임원·소유주 변경은 모두 경보다. 준법감시인 교체처럼 운용과 거리가 먼 변경 때문에 토론이 너무 자주 열리면 숫자(3곳 중 몇 곳)와 함께 PM에게 알린다. 핵심 직함만 남길지는 팀이 정한다.
- `summary` 는 코드가 `format.py` 로 만든다. 예: `"소형주 비중 12% → 27% (+15%p), 매매 기준 +14%p, 전체 13F 운용사 분기 변화폭 상위 3%"`. 임시 기준값일 때는 "상위 N%" 대신 "(임시 기준)"을 붙인다.
- 모든 신호에 `evidence` 1개 이상. 13F 신호는 최신·직전 분기 공시 URL과 `as_of=report_date`, ADV 신호는 Frontend가 준 근거를 그대로.
- 신호 `id` 는 `<manager_id>-<kind>-<번호>`. 번호는 `(kind, metric)` 으로 정렬한 순서라서 같은 입력이면 항상 같은 id가 나온다.
- 13F가 없는 운용사(`quarters=[]`)는 ADV 신호만 내고 멈추지 않는다.

### `data_cache/thresholds.json` 읽기
```json
{"computed_at": "2026-11-22", "window": null,
 "metrics": {
   "concentration_change": {"mode": "placeholder", "p90": 0.05, "p95": 0.08, "quantiles": null, "n": null},
   "turnover":             {"mode": "placeholder", "p90": 0.20, "p95": 0.30, "quantiles": null, "n": null}},
 "levels": {
   "top10_concentration":  {"mode": "placeholder", "p05": null, "p50": null, "p95": null, "quantiles": null, "n": null}}}
```
- **위 숫자는 형식을 보여 주는 자리표시일 뿐 근거가 없다.** 11/29 E2E v0에서 연결을 확인하는 용도로만 쓰고 `docs/decisions.md` 에 "임시값(근거 없음)"이라고 적는다. B5에서 실제 분포로 바꾼다.
- `mode="distribution"` 이면 `quantiles` 에 0~100 백분위 값 101개가 들어 있다. `pct` = m이 `quantiles` 에서 놓이는 위치를 선형 보간해 100으로 나눈 값. `p90 = quantiles[90]`, `p95 = quantiles[95]`.
- `mode="placeholder"` 이면 `pct` 를 계산할 수 없으므로 `m >= p95` → 경보, `p90 <= m < p95` 이고 `m > own` → 관찰로 판정하고 `Signal.percentile = None`.

### 설명 — `src/analysis/explain.py` (데이터 분석 에이전트의 LLM 부분)
- 신호 전체를 한 번의 `call_llm(role="analyst", ...)` 호출로 보내 신호별 1~2문장 한국어 설명을 받는다(`{"explanations": [{"signal_id", "text"}]}`). 담당자가 금융 용어를 몰라도 읽히게.
- LLM에게는 `summary` 와 표기값만 준다. 응답에 A7의 숫자 검사를 적용해 **주어지지 않은 숫자**가 있으면 그 설명을 버리고 `explanation = summary` 로 둔다.
- LLM이 실패해도 `analyze` 는 멈추지 않는다(전부 `explanation = summary`).

### 운용사가 밝힌 전략 — `src/analysis/strategy.py`
1. 후보 문단: `search_evidence(manager_id, 질의)`(PM의 근거 검색)를 부른다. 결과가 비어 있으면(색인 없음) `adv2a_new.items["8"]` 의 앞 6,000자를 후보로 쓴다.
2. `call_llm(role="analyst")` 1회: 후보에서 전략을 설명하는 문장을 **원문 그대로** 3문장 이내로 고르고, 한국어 한 줄 요약을 쓴다.
3. 고른 인용이 `adv2a_new` 본문에 실제로 있는 문자열인지 코드로 확인한다(연속 공백만 하나로 정리해 비교). 없는 인용은 버린다.
4. 남은 인용이 없거나 Part 2A가 없으면 `stated_strategy=None`, `unavailable` 에 "운용사가 밝힌 전략: 확인 불가".

### 조립 — `analyze()`
`detect_signals` → `explain` → `strategy` → `AnalysisResult` → `validate` → A9 형식으로 `analysis.json` 저장. LLM 호출은 최대 2번이다.

## B5. 기준값 보정 (11/29~12/5) — `scripts/analysis_compute_thresholds.py`

로컬에서 한 번 돌려 `data_cache/thresholds.json` 을 만든다. 배포 서버에서는 이 파일만 읽는다.

### 데이터 (내려받기와 읽는 함수는 11/19~23에 먼저 만든다)
- SEC "Form 13F Data Sets"(분기별 압축 파일, 탭 구분). 내려받는 페이지 주소는 검색으로 찾아 `docs/verified.md` 에 적는다. `data_cache/raw/13f/` 에 둔다(GitHub에 올리지 않음).
- 쓰는 표와 열(SEC 안내문 기준):
  - `INFOTABLE`: `ACCESSION_NUMBER, CUSIP, VALUE, SSHPRNAMT, SSHPRNAMTTYPE, PUTCALL`
  - `SUBMISSION`: `ACCESSION_NUMBER, FILING_DATE, SUBMISSIONTYPE, CIK, PERIODOFREPORT`
  - `COVERPAGE`: `ACCESSION_NUMBER, ISAMENDMENT, AMENDMENTTYPE`
- **압축 파일은 "제출된 시기"별로 묶여 있다.** 분기를 나눌 때는 파일 이름이 아니라 `PERIODOFREPORT`(보고 기준일)를 쓴다. 14개 보고 분기를 덮으려면 파일이 15개쯤 필요하다.
- `VALUE` 는 제출일(`FILING_DATE`)이 2023-01-03 이후면 달러, 그 전이면 천 달러(×1000).
- 한 운용사·한 보고 분기에 제출이 여러 개면: 전체 대체 정정(RESTATEMENT)이 있으면 가장 늦은 것, 없으면 원본을 쓴다. 추가 정정(NEW HOLDINGS)은 분포 계산에서 반영하지 않는다(표본이 수천 곳이라 영향이 작다고 보고 단순화한 것이며 `docs/metrics.md` 에 적는다).
- 11/19~23에 만들 것: `scripts/analysis_load_13f.py` — 압축 파일 15개를 받아 두고, `load_quarter(period) -> pandas.DataFrame`(열: `CIK, PERIODOFREPORT, CUSIP, VALUE_USD, SSHPRNAMT`, 옵션·원금 제외, 정정 규칙 적용, 금액 단위 통일)가 한 분기를 돌려준다. 여기까지가 기획서 1주차 "13F 데이터셋 3년 적재"다.
- 분기 하나가 수백만 줄이다. pandas `read_csv(sep="\t", usecols=[...])` 로 필요한 열만, **이웃한 두 분기씩만** 메모리에 올려 계산하고 결과(운용사·분기별 지표 한 줄)를 CSV로 쌓는다. 그래도 메모리가 모자라면 PM에게 알리고 다른 도구를 상의한다.

### 계산
1. 운용사(CIK)·분기 쌍마다 B2의 `concentration_change`, `turnover` 를 계산한다. 이 규모에서는 발행주식 수가 없으므로 분할 보정은 2번 규칙(가격 급변 제외)만 적용한다.
2. 분포에서 빼는 운용사: 보유 종목 수가 `MIN_POSITIONS`(10) 미만이거나 `INDEX_LIKE_MIN_POSITIONS`(1,500) 이상(두 분기 중 하나라도).
3. 최근 13개 변화(14개 분기)의 모든 (운용사, 분기) 관측값을 한데 모아 `numpy.percentile(값, range(101))` 로 `quantiles` 를 만든다. `n` 에 관측 수를 적는다.
4. 수준 분포(`levels`): 가장 최근 분기의 `top10_concentration` 으로 같은 방식.
5. **업종·규모(`sector_shift`, `size_shift`, `small_cap_weight` 수준):** 모든 CUSIP에 업종·발행주식 수가 필요하다. 범위를 이렇게 줄인다: ① 가장 최근 두 분기만, ② 분포에 들어가는 운용사 중 무작위 1,000곳(`random.seed(42)`, 결과를 다시 만들 수 있게), ③ 그 운용사들의 CUSIP을 금액이 큰 순으로 내 `enrich_cusips`(B3-1)에 넣어 전체 금액의 95%를 덮는 데까지. OpenFIGI 무료 키가 필요하고 SEC 요청은 초당 5회라, 시작 전에 고유 CUSIP 수와 예상 시간(CUSIP 수 × 발행사당 SEC 요청 2번 ÷ 5회/초)을 계산해 `docs/decisions.md` 에 적는다. 한 분기 쌍만 쓰므로 `window` 에 그 사실을 적는다.
6. **12/5까지 5번이 안 되면:** 업종·규모는 `mode="placeholder"` 로 남기고 PM에게 알린다. 발표에서 "업종·규모는 임시 기준"이라고 밝힌다(A10의 줄이는 순서).

### 보정 확인 (기획서 ⑥ "분기당 토론 대상 10% 안팎")
- 가장 최근 분기에 대해, 13F 신호만으로 `debate_required` 가 되는 운용사 비율을 계산해 `docs/decisions.md` 에 적는다(ADV 경보는 전체 운용사에 대해 계산할 수 없어 빠진다는 점도 함께).
- **미리 알아 둘 계산:** 지표 4개가 서로 무관하다면 "적어도 하나가 상위 5%"일 확률은 `1 − 0.95⁴ ≈ 18.5%` 다. 실제로는 지표끼리 연관이 있어 더 낮겠지만 10%를 넘을 수 있다. 실제 비율이 10%에서 많이 벗어나면 기준을 혼자 바꾸지 말고 숫자를 들고 PM과 정한다(상위 5%·10%는 기획서에 적힌 값이다).

### Should (12/6 이후 여유가 있을 때만)
같은 전략 Peer 5곳 정밀 비교. 못 하면 하지 않는다.

## B6. 검증 에이전트 (12/6~13) — `src/analysis/verify.py`

기획서 목표: **점검 리포트 수치의 원문 일치 100%.** 검증은 전부 코드다. LLM에게 "맞는지 봐줘"라고 시키지 않는다.

`verify_report(draft, analysis, debate, data)` 가 하는 검사:

| # | 검사 | 방법 | 결과 |
|---|---|---|---|
| 1 | 근거 없는 사실 문장 | `kind="fact"` 인데 `evidence == []` | `unsupported_idx` (삭제 대상) |
| 2 | 숫자 | 문장마다 `unknown_numbers(text, analysis["signals"])`(A7, 그 운용사 신호 전체 기준)가 비어 있는가 | 걸린 표기마다 `Mismatch("신호에 없는 숫자")` |
| 3 | 개수·점수 | `number_tokens(text, include_report_units=True)` 중 `N건` 은 {신호 수, 경보 수, 관찰 수, 미설명 수, 설명됨 수} 안에, `N점` 은 그 문장 `signal_ids` 의 심판 점수(항목별·양측 합계) 안에 있는가 | 없으면 `Mismatch` |
| 4 | 인용 | `evidence.quote` 가 `data` 의 ADV 본문(`adv2a_new`, `adv2a_old` 의 모든 Item)에 실제로 있는 문자열인가(연속 공백만 정리해 비교) | 없으면 `Mismatch("원문에 없는 인용")` |
| 5 | 모든 신호 인용 | `analysis.signals` 의 모든 id가 어떤 문장의 `signal_ids` 에 있는가 | 없으면 `uncited_signals` |
| 6 | 저장본 어긋남 | `detect_signals(data)` 를 다시 돌려 `analysis.signals` 의 숫자 필드와 같은가(차이 1e-9 이내) | 다르면 `Mismatch("신호 값이 원본과 다름")` |

결과 판단:
- `passed = (mismatches 없음) and (uncited_signals 없음)`. 1번만 있으면 통과다(그 문장은 PM이 삭제하고 리포트에 내역을 표시한다).
- `failed_step`: 6번이 있으면 `"analysis"`. 아니고 `section` 이 `debate / options / questions` 인 문장의 불일치가 있으면 `"debate"`. 그 밖의 실패(`changes` 문장의 숫자, 인용되지 않은 신호)는 리포트 조립 코드의 문제라 다시 돌려도 고쳐지지 않으므로 `None` 으로 두고 PM에게 버그로 알린다.
- 그래프가 `failed_step` 부터 다시 실행한다(전체 합쳐 최대 2회). 나는 결과만 정확히 돌려주면 된다.

이 검증이 잡는 것과 못 잡는 것(발표 질의응답에서 그대로 답한다):
- 잡는다: LLM이 만든 숫자, 원문에 없는 인용, 빠진 신호, 저장본끼리 어긋난 값.
- 못 잡는다: 계산식 자체가 틀린 경우(6번은 같은 코드로 다시 계산하므로). 이건 B2의 손 계산 테스트와 B7의 수동 검수로 잡는다.

## B7. 숫자 검수 (12/14~17)

- 3곳의 화면·PDF에 나온 숫자를 하나씩 SEC 원문(13F 정보표, ADV)에서 직접 찾아 대조하고 `docs/number_audit.md` 에 표로 남긴다(숫자 / 원문 위치 / 직접 계산한 값 / 일치 여부).
- 비중·회전율 같은 계산값은 13F 정보표를 스프레드시트에 붙여 B2 식으로 직접 계산해 비교한다. 최소한 신호로 나온 지표는 전부 한다.
- 발표에서 "수치 원문 일치 N/N"으로 쓸 자료다.

## B8. 테스트와 완료 기준 — `tests/analysis/`

- [ ] B2 손 계산 예시: `active_change`(A·B·C), 회전율 19.5%, `size_shift` 가 예시 값과 같음(허용 오차 1e-6)
- [ ] 주가만 변하고 주식 수가 그대로면 모든 `active_change` 가 0, 회전율 0
- [ ] 2대1 분할(`k=2`, 주가 10 → 5.5)이 매매로 잡히지 않음. 발행주식 수가 없고 주가가 10 → 4면 그 종목이 매매 계산에서 제외되고 `data_checks` 에 남음
- [ ] 매핑률 0.9 → 업종·규모 지표 `확인 불가`, 집중도·회전율은 계산됨
- [ ] 시가총액 19.9억 → 소형, 20억 → 중형, 100억 → 대형 (경계값)
- [ ] `pct=0.96` → 경보 / `pct=0.92` 이고 자기 최대 초과 → 관찰 / `pct=0.92` 이고 자기 최대 이하 → 신호 없음 / `pct=0.92` 인데 직전 변화가 3개뿐 → 신호 없음 + `unavailable` / `pct=0.96` 이면 직전 변화가 3개뿐이어도 경보
- [ ] 경보 1개 → `debate_required=True` / 관찰 1개 → False / 관찰 2개 → True / 신호 0개 → False
- [ ] 임원 2명 제외 → `officer_removed` 경보 1개에 두 이름과 직함
- [ ] 운용자산 $12B → $7.8B → `aum_change` 관찰, $12B → $9B(-25%) → 신호 없음, $5B → $10.5B → 관찰
- [ ] 직원 40 → 28명 → `employee_drop` 관찰, 10 → 8명(2명 감소) → 신호 없음
- [ ] 사모펀드 4 → 7개 → 관찰, 4 → 5개 → 신호 없음, 0 → 2개 → 관찰
- [ ] 직전 ADV가 없으면 규모 신호를 내지 않음
- [ ] 하한값(partial) 시가총액 $50B → 대형, $5B → 미분류
- [ ] 매핑률 0.94 → 업종·규모 `확인 불가` / 매핑률 0.97인데 규모 구간을 정할 수 있는 금액 비율 0.85 → 규모만 `확인 불가`
- [ ] 같은 입력으로 두 번 돌리면 신호 id가 같음
- [ ] 13F 없는 운용사로 `analyze` 가 멈추지 않음
- [ ] 설명문에 주어지지 않은 숫자가 있으면 `summary` 로 대체됨
- [ ] 전략 인용이 원문에 없으면 버려짐
- [ ] 검증: 초안의 `27%` 를 `31%` 로 바꾸면 `passed=False`, 해당 문장 인덱스의 `Mismatch`
- [ ] 검증: 신호 하나를 인용하지 않은 초안 → `uncited_signals` 에 그 id
- [ ] 검증: 근거 없는 사실 문장 → `unsupported_idx` 에 들어가고 `passed` 는 그대로
- [ ] 검증: `analysis.json` 의 값을 바꿔 두면 `failed_step="analysis"`
- [ ] 실제 데이터 1곳: 분기마다 비중 합이 1(오차 1e-9), 주가 중앙값이 1~1,000달러

## B9. 하지 말 것

- 숫자를 LLM에게 계산시키지 않는다. 설명문에 새 숫자를 허용하지 않는다.
- B2의 계산식을 "더 간단하게" 바꾸지 않는다. 바꿔야 하면 PM과 상의하고 `docs/metrics.md` 와 손 계산 예시를 같이 고친다.
- 데이터가 없는데 비슷한 값으로 채우지 않는다. `확인 불가`.
- 공시를 직접 받아오는 코드를 `src/analysis/` 에 넣지 않는다(수집은 Frontend). 기준값 스크립트의 13F 데이터셋 읽기만 예외다.
- 유지·해지 판단을 하지 않는다. "변화가 있다, 얼마나 드문 변화다"까지만 말한다.
- `src/state.py`, `src/config.py`, 다른 파트 폴더를 수정하지 않는다.

# C. 지금 바로 할 일 (AI와 함께 이 순서로)

1. A5의 환경을 만든다(파이썬 3.11, 가상환경). PM 레포가 있으면 받고, 없으면 로컬에 A5 폴더 구조를 만들어 `src/state.py` 에 A6을 그대로 옮겨 둔다.
2. `enrich_cusips` 의 **가짜 버전**(모든 값 `None`, `is_etf=False`)과 `analyze`·`verify_report` 의 **mock 버전**(A11-2의 `AnalysisResult` 와 `passed=True` 를 돌려줌)을 먼저 올린다. Frontend와 PM이 바로 연결할 수 있게 한다.
3. (11/13~14) B2의 손 계산 예시를 종이나 스프레드시트로 **직접 한 번 계산해** 같은 값이 나오는지 확인하고 `docs/metrics.md` 에 옮긴다. 값이 다르면 PM에게 바로 알린다.
4. (11/15~18) 종목 식별 도구(B3-1)를 만든다. B3-1의 테스트를 먼저 쓰고, 11/16에 OpenFIGI로 ETF·보통주·예탁증서를 하나씩 실제 조회해 종목 유형 값을 확인한다. SEC 호출은 조재연의 `sec_get` 을 쓴다(올라오기 전엔 가짜).
5. (11/19~23) 손 계산 예시를 `tests/analysis/test_metrics.py` 로 옮기고, 통과하도록 `metrics.py`, `splits.py`, `sectors.py` 를 구현한다. 같은 주에 SEC "Form 13F Data Sets" 파일을 받아 열 이름·`PERIODOFREPORT`·금액 단위를 실제로 확인해 `docs/verified.md` 에 적고 `load_quarter` 를 만든다(B5).
6. (11/24~28) 자리표시용 `thresholds.json` 을 만들고 `signals.py`(판정 규칙 테스트 먼저) → `explain.py` → `strategy.py` 순서로 붙인다.
