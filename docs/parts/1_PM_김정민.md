# 망루 개발 기획서 — PM (김정민)

> **사람용 안내:** 이 파일을 AI 코딩 도구(Claude Code 등)에 통째로 넣고 "C장 순서대로 시작해줘"라고 하면 된다. A장은 4개 파트가 똑같이 갖고 있는 공통 계약이고, B장이 내 파트 상세다.
>
> **AI에게:** 너는 「망루」 프로젝트의 **PM 파트(레포·계약 관리, LangGraph 연결, 리포트, 통합 테스트)** 개발을 돕는다. 이 문서 전체를 읽고 A장의 계약을 기준으로 삼아라. 네가 고칠 수 있는 곳은 `src/state.py`, `src/config.py`, `src/validate.py`, `src/graph.py`, `src/report/`, `src/rag/`, `scripts/rag_*`, `tests/integration/`, `tests/fixtures/`, `assets/`, `requirements*.txt`, `.env.example`, `CLAUDE.md`, `docs/` 다. `src/collect/`, `src/analysis/`, `src/debate/`, `src/llm.py`, `src/app.py` 는 다른 파트 소유이므로 고치지 말고, 필요한 변경은 사용자에게 알려라. `state.py` 나 `config.py` 를 바꾸면 4개 파트 문서의 A장도 같이 고쳐야 한다는 점을 사용자에게 알려라. 작업은 C장 순서로 진행하라.

## 0. 내 파트 한눈에

- **맡은 것:** 레포와 공통 계약 관리, ① 계획, LangGraph로 전체 연결, ⑤ 점검 리포트와 PDF, 근거 검색(RAG), 통합 테스트, 발표 준비
- **내가 만드는 함수:** `make_plan`, `stream_run`, `draft_report`, `apply_verify`, `render_pdf`, `search_evidence`, `validate`, 숫자 표기 함수(`fmt_*`, `number_tokens`, `allowed_tokens`)
- **중요한 점:** 내가 11/15까지 `state.py` 와 샘플 JSON을 올려야 나머지 세 파트가 서로를 기다리지 않고 개발할 수 있다. 이후에는 각 파트의 mock을 실제 함수로 하나씩 바꿔 끼우는 일이 중심이다

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

# B. PM 파트 상세

## B1. 만들 것과 일정

| 기간 | 업무 | 난이도 | 완료 기준 |
|---|---|---|---|
| 11/13 | LLM API 키·비용 상한 | ★ | Anthropic·OpenAI 키 발급, 회사별 월 사용 한도 설정, 팀원에게 키 전달 방식 결정(B2-11). 백엔드 모델 선택이 이걸 기다린다 |
| 11/13~14 | OpenFIGI 키·SEC 연락 이메일 | ★ | OpenFIGI 무료 키 발급, SEC User-Agent에 쓸 팀 공용 이메일 결정, 김지유·조재연에게 전달 (11/15부터 쓴다) |
| 11/13~15 | 협업 세팅 | ★★ | 레포에 4명 초대, `state.py`·`config.py`·`validate.py`·샘플 JSON·`CLAUDE.md` 가 올라가 있음 |
| 11/16~21 | LangGraph 뼈대 | ★★★ | mock 함수로 계획 → 수집 → 분석 → 토론 → 리포트 → 검증이 순서대로 실행됨 |
| 11/18 | 상호평가 투표 | | 팀원 전원 투표 완료 (11/19 10:00 전) |
| 11/22~24 | 리포트 PDF | ★★ | 샘플 JSON으로 신호·토론·선택지·질문·출처가 든 1장 PDF가 나옴 (한글 정상) |
| 11/25~29 | 노드 연결 | ★★★ | 각 파트의 실제 함수로 바꿔 끼워 운용사 1곳이 끝까지 실행됨 (E2E v0) |
| 12/1~5 | 발표 목차 + 근거 검색(RAG) | ★★★ | 슬라이드 목차 초안 / `search_evidence` 가 ADV 2A에서 관련 문단을 돌려줌 |
| 12/5 | 기본값 점검 회의 | | A8의 기본값으로 데모 3곳·분포를 돌려 본 결과를 보고, 근거가 생긴 값만 바꿔 `docs/decisions.md` 에 기록 |
| 12/7~13 | 통합 테스트 | ★★★ | 3곳 반복 실행, 버그를 파트별로 배정, 시연 1회 시간·비용 기록 |
| 12/14~19 | 발표 PDF | | 제출용 발표 자료 완성 |
| 12/16~19 | README (전체) | | 실행 방법, 데이터 출처, 생성형 AI 사용 내역 |
| 12/17~20 | 시연 영상 | | 입력 → 진행 → 결과 → PDF 흐름 2~3분. 발표 당일 백업으로도 사용 |
| 12/21 | 최종 점검 후 밤에 제출 | | 다른 기기에서 모든 링크가 열림 |
| 12/22~25 | 대본·예상 Q&A | | 시간 맞춘 대본 + 파트별 답변을 합친 Q&A 문서 |
| 12/26, 12/28 | 리허설 1차·2차 | | 발표자·시연 담당·Q&A 답변자 확정 |

Should(12/6 이후 Must가 모두 끝났을 때만): 점검 이력 Memory(SQLite에 운용사별 점검 결과·질문 저장). 못 하면 하지 않고 발표에서 확장 계획으로 말한다.

## B2. 협업 세팅 (11/13~15) — 이게 끝나야 다른 파트가 시작한다

1. GitHub 레포 `mangru` 를 만들고 4명을 초대한다. `main` 은 직접 푸시 금지(PR만).
2. A5의 폴더 구조를 만든다. 빈 폴더에는 `__init__.py` 또는 `.gitkeep`.
3. `.gitignore`: `.env`, `data_cache/raw/`, `logs/`, `__pycache__/`, `.venv/`. **`data_cache/demo/` 와 `data_cache/thresholds.json` 은 올린다.**
4. `src/state.py` 를 A6 그대로, `src/config.py` 를 A8 그대로 작성한다. `config.py` 에 `DEMO_MANAGERS` 를 둔다(조재연이 11/14까지 3곳을 정해 준다. 그 전에는 가짜 값):
   ```python
   DEMO_MANAGERS = {
       "demo1": {"name": "...", "aliases": ["..."], "cik": "...", "crd": "...", "has_13f": True, "last_check_date": None},
   }
   ```
5. `src/validate.py`:
   ```python
   from pydantic import TypeAdapter
   def validate(obj, type_) -> None:
       TypeAdapter(type_).validate_python(obj)   # 모양이 다르면 예외. 사용법은 설치한 pydantic 버전 문서로 확인
   ```
6. **계약 샘플 5개**를 `tests/fixtures/` 에 만든다: A11-2의 JSON을 그대로 `manager_data / analysis / debate / draft / verify .sample.json` 으로 저장한다. `tests/integration/test_fixtures.py` 에서 다섯 파일이 `validate` 를 통과하는지 검사한다.
7. `requirements.txt`(배포용)와 `requirements-dev.txt`(`-r requirements.txt` + `pytest`, `chromadb`)를 A5 표대로 만들고, 설치한 실제 버전으로 고정한다(`pip freeze` 에서 해당 줄만).
8. `.env.example`: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENFIGI_API_KEY`, `SEC_CONTACT_EMAIL`, `MODEL_KEEP`, `MODEL_TERMINATE`, `MODEL_JUDGE`, `MODEL_ANALYST`, `LLM_MOCK` (이름만, 값은 비움).
9. `CLAUDE.md`(B8)를 만들고, A장을 `docs/CONTRACT.md` 로, 4개 파트 문서를 `docs/parts/` 에 둔다. `docs/decisions.md`(팀이 정한 것), `docs/verified.md`(실제 호출로 확인한 주소·열 이름)를 빈 파일로 만든다.
10. `assets/fonts/` 에 재배포가 허용된 한글 폰트(예: 나눔고딕, SIL OFL)를 넣고 라이선스 파일을 함께 둔다.
11. **API 키·계정 (11/13~14, 내가 직접):**
    - LLM: Anthropic·OpenAI 계정에서 API 키를 만들고, 각 회사 콘솔에서 월 사용 한도를 건다(금액은 팀과 정해 `docs/decisions.md` 에 기록).
    - OpenFIGI: 무료 키 발급(키가 없으면 분당 25요청이라 종목 식별이 너무 느리다).
    - SEC: User-Agent에 넣을 팀 공용 연락 이메일을 정한다(개인 메일 대신 팀 메일 권장).
    - 전달: 키는 GitHub·단톡방에 올리지 않는다. 개인 메시지로 보내고 각자 `.env` 에 넣는다. 배포용 키는 Streamlit secrets에 내가 넣는다.

## B3. LangGraph 뼈대 (11/16~21) — `src/graph.py`

### 노드와 흐름
```
plan ─(운용사 못 찾음)→ failed
  └→ collect ─(새 공시 없음)→ early_exit
        └→ analyze → debate → draft → verify ─ 통과 ──────────────────→ done
              ↑         ↑                  │
              └─────────┴── 실패 + 재수행 가능: failed_step 부터 다시 ──┘
                                           └ 재수행 불가: 문장 삭제 + 알림 → done
```

| 노드 | 부르는 함수 | 상태에 쓰는 것 |
|---|---|---|
| `plan` | `make_plan(request)` | `plan` (없으면 `status="failed"`, 알림 "운용사를 찾지 못함") |
| `collect` | `collect(plan, demo_mode)`. 실제 모드이고 `adv2a_new` 가 있으면 `rag.build_index` 도 부른다(실패해도 계속) | `data`, `unavailable` |
| `analyze` | `analyze(data, plan)` | `analysis`, `unavailable` |
| `debate` | `run_debate(analysis, data, demo_mode)` | `debate`, `notices`(토론 경고) |
| `draft` | `draft_report(state)` | `draft` |
| `verify` | `verify_report(draft, analysis, debate, data)` → `apply_verify(...)` | `verify`, `draft`, `removed_sentences`, `retries`, `notices` |

### 검증 뒤 분기 규칙
| 검증 결과 | 조건 | 다음 |
|---|---|---|
| 통과 | | 근거 없는 문장만 삭제 → 끝 (`status="done"`) |
| 실패 | `failed_step` 있음 + 실제 모드 + `retries < 2` | `retries += 1` → `analysis` 면 analyze 노드부터, `debate` 면 debate 노드부터 다시 |
| 실패 | 그 밖 (데모 모드, 재시도 2회 초과, `failed_step=None`) | 불일치 문장도 삭제 + 사유 알림 → 끝 |

- 데모 모드에서 재수행하지 않는 이유: 저장본을 다시 읽어도 같은 결과라 의미가 없다.
- 재수행은 같은 토론을 다시 만드는 것이라 "운용사당 토론 1회" 규칙과 부딪히지 않는다(남는 결과는 마지막 하나).
- 삭제한 문장은 `removed_sentences` 에 모아 PDF와 화면에 내역을 보여 준다(기획서 ③ "근거 없는 문장 삭제(내역 표시)").
- 노드 안에서 예외가 나면 `safe_node` 가 잡아 `status="failed"` 와 알림을 남기고 끝낸다. 예외는 버그라는 뜻이다. 데이터가 없는 상황은 각 파트가 예외 대신 `확인 불가` 로 처리한다.
- `unavailable` 은 재수행 때 같은 항목이 다시 쌓일 수 있으니 화면·PDF에서 보여 줄 때 중복을 뺀다.

### `src/graph.py` 전체 뼈대 — 그대로 쓴다
LangGraph 1.2에서 mock 함수로 실행해 정상 흐름, 검증 실패 재수행 2회, 데모 모드, 조기 종료, 운용사 없음, 노드 예외, 색인 실패를 모두 확인한 코드다. 노드 함수는 **바뀐 값만 담은 dict** 를 돌려준다. 모두 동기 함수다(async 쓰지 않음).

```python
from typing import Iterator
from langgraph.graph import StateGraph, START, END

from src.state import AgentState
from src.config import MAX_VERIFY_RETRIES
from src.plan import make_plan                      # 아래 'make_plan' 참고 (PM)
from src.collect import collect                     # Frontend
from src.analysis import analyze                    # Data
from src.analysis.verify import verify_report       # Data
from src.debate import run_debate                   # Backend
from src.llm import reset_call_count                # Backend
from src.report.draft import draft_report, apply_verify   # PM
from src.rag import build_index                     # PM


def initial_state(request: str, demo_mode: bool) -> AgentState:
    return {"request": request, "demo_mode": demo_mode, "plan": None, "data": None,
            "analysis": None, "debate": None, "draft": None, "verify": None,
            "retries": 0, "next_step": None, "removed_sentences": [], "notices": [],
            "unavailable": [], "status": "running"}


def safe_node(name, fn):
    """노드 안에서 예외가 나면 그래프를 죽이지 않고 status=failed 로 멈춘다."""
    def wrapped(state: AgentState) -> dict:
        try:
            return fn(state)
        except Exception as e:
            return {"status": "failed",
                    "notices": state["notices"] + [f"{name} 단계 오류: {type(e).__name__}: {e}"]}
    return wrapped


def n_plan(s):
    plan = make_plan(s["request"])
    if plan is None:
        return {"status": "failed", "notices": s["notices"] + ["요청에서 운용사를 찾지 못함"]}
    return {"plan": plan}


def n_collect(s):
    data = collect(s["plan"], s["demo_mode"])
    notices = list(s["notices"])
    if not s["demo_mode"] and data["adv2a_new"]:
        try:
            build_index(data["manager_id"], data["adv2a_new"])
        except Exception as e:      # 색인이 없어도 분석은 Item 8 본문으로 진행된다
            notices.append(f"근거 검색 색인 실패: {e}")
    upd = {"data": data, "unavailable": s["unavailable"] + data["unavailable"], "notices": notices}
    if not data["has_new_filing"]:
        upd |= {"status": "early_exit", "notices": notices + ["직전 점검 이후 새 공시 없음"]}
    return upd


def n_analyze(s):
    a = analyze(s["data"], s["plan"])
    return {"analysis": a, "unavailable": s["unavailable"] + a["unavailable"]}


def n_debate(s):
    d = run_debate(s["analysis"], s["data"], s["demo_mode"])
    return {"debate": d, "notices": s["notices"] + d["warnings"]}


def n_draft(s):
    return {"draft": draft_report(s)}


def n_verify(s):
    v = verify_report(s["draft"], s["analysis"], s["debate"], s["data"])
    if v["passed"]:
        draft, removed = apply_verify(s["draft"], v, drop_mismatched=False)
        return {"verify": v, "draft": draft, "removed_sentences": removed,
                "next_step": "finish", "status": "done"}
    can_rerun = (v["failed_step"] is not None and not s["demo_mode"]
                 and s["retries"] < MAX_VERIFY_RETRIES)
    if can_rerun:
        target = "analyze" if v["failed_step"] == "analysis" else "debate"
        return {"verify": v, "retries": s["retries"] + 1, "next_step": target,
                "notices": s["notices"] + [f"검증 실패 → {target}부터 재수행 {s['retries'] + 1}/{MAX_VERIFY_RETRIES}"]}
    draft, removed = apply_verify(s["draft"], v, drop_mismatched=True)
    if v["failed_step"] is None:
        why = "리포트 조립 오류(담당 확인 필요)"
    elif s["demo_mode"]:
        why = "데모 모드라 재수행 없음"
    else:
        why = f"검증 재시도 {MAX_VERIFY_RETRIES}회 초과"
    return {"verify": v, "draft": draft, "removed_sentences": removed, "next_step": "finish",
            "status": "done", "notices": s["notices"] + [f"{why}: 문장 {len(removed)}개 삭제"]}


def build_graph():
    g = StateGraph(AgentState)
    for name, fn in [("plan", n_plan), ("collect", n_collect), ("analyze", n_analyze),
                     ("debate", n_debate), ("draft", n_draft), ("verify", n_verify)]:
        g.add_node(name, safe_node(name, fn))
    g.add_edge(START, "plan")

    def chain(src, nxt):   # status 가 running 이 아니면(실패·조기 종료) 바로 끝낸다
        g.add_conditional_edges(src, lambda s: "next" if s["status"] == "running" else "stop",
                                {"next": nxt, "stop": END})
    chain("plan", "collect"); chain("collect", "analyze"); chain("analyze", "debate")
    chain("debate", "draft"); chain("draft", "verify")
    g.add_conditional_edges(
        "verify",
        lambda s: s["next_step"] if s["status"] == "running" else "stop",
        {"analyze": "analyze", "debate": "debate", "stop": END})
    return g.compile()


APP = build_graph()


def stream_run(request: str, demo_mode: bool = True) -> Iterator[dict]:
    reset_call_count()
    state = initial_state(request, demo_mode)
    for chunk in APP.stream(state, stream_mode="updates", config={"recursion_limit": 30}):
        for node, update in chunk.items():          # {"collect": {...바뀐 값...}}
            state = {**state, **(update or {})}
            yield {"step": node, "state": state}
    yield {"step": "done", "state": state}
```

- `stream_run` 이 내보내는 `step` 순서(정상): `plan → collect → analyze → debate → draft → verify → done`. 재수행이 있으면 `verify` 뒤에 `debate`(또는 `analyze`)부터 다시 나온다.
- 경로 길이: 노드 6개 + 재수행 2회(최대 4노드씩) = 최대 14단계라 `recursion_limit=30` 안에 들어간다.
- LangGraph 버전이 바뀌어 위 코드가 안 돌면, `pip show langgraph` 로 버전을 확인하고 그 버전 문서에서 `StateGraph`, `add_conditional_edges`, `stream(stream_mode="updates")` 사용법만 맞춘다.
- **대비책:** 11/21까지 LangGraph가 안 돌면 같은 `stream_run` 모양을 유지한 채 평범한 파이썬 반복문으로 먼저 만들어 다른 파트를 막지 않는다. 12/6 데모 완성 전에 LangGraph로 바꾼다(기획서 명시 기술).
- 11/21까지는 모든 노드가 mock을 부른다. 각 파트가 자기 mock을 올리면 그걸 쓰고, 없으면 내가 `tests/fixtures/` 샘플을 돌려주는 mock을 임시로 만든다.

### `make_plan` (① 계획) — `src/plan.py`, LLM 없음
- 요청 문장에 `DEMO_MANAGERS` 의 `name` 또는 `aliases` 가 들어 있으면(대소문자 무시) 그 운용사로 `Plan` 을 만든다. `has_13f` 는 `config` 값, `checks` 는 세 가지 모두, `period` 는 오늘 날짜로 정한다(1~6월 `YYYYH1`, 7~12월 `YYYYH2`). 주식형이면(`has_13f=True`) 13F 경로를 포함한다는 기획서 규칙은 이 값으로 지켜진다.
- 못 찾으면 `None`. 화면이 운용사를 고르게 한다.
- "새 공시가 없으면 조기 종료"는 수집 단계의 `has_new_filing` 으로 처리한다(A2).

## B4. 리포트 (11/22~24) — `src/report/`

### 숫자 표기 — `format.py` (11/16까지. 다른 파트가 기다린다)
A7의 코드를 **그대로** 옮기고, A7 표의 예를 전부 테스트로 넣는다. 추가 테스트:
- `fmt_ratio(0.125)` → `12.5%`, `fmt_pp(-0.21645)` → `-21.6%p`, `fmt_top_pct(0.96)` → `상위 4%`, `fmt_usd(999)` → `$999`
- `allowed_tokens(A11의 두 번째 신호)` 에 `12%`, `27%`, `+15%p`, `15%p`, `+14%p`, `14%p`, `3%`, `5%`, `10%` 가 들어 있다
- `unknown_numbers("운용자산이 $12B에서 $7.8B로", A11-2의 신호들)` → `[]`

### 초안 — `draft.py` (`draft_report`, `apply_verify`)
코드로 조립한다(LLM 없이). 문장마다 `ReportSentence` 를 만들고 `signal_ids` 와 `evidence` 를 채운다.

| 구역 (`section`) | 문장 | `kind` | 재료 |
|---|---|---|---|
| `recommendation` | "변화 N건 중 미설명 M건 → <권고>" 한 줄 | `opinion` | `analysis.signals`, `debate` |
| `changes` | 신호마다 `summary` 한 문장 | `fact` (근거 = 신호의 `evidence`) | `analysis.signals` |
| `changes` | 신호마다 `explanation` 한 문장 | `opinion` | 〃 |
| `debate` | 변화마다 유지 측 논거 1문장, 해지 측 논거 1문장 | `opinion` | `debate.keep_args`, `terminate_args` |
| `debate` | 변화마다 "심판: 유지 측 X점, 해지 측 Y점 → 설명됨/미설명. <이유>" | `opinion` | `debate.verdicts` |
| `options` | 선택지 3개의 근거 문장(권고 표시) | `opinion` | `debate.options` |
| `questions` | 미팅 질문 3개 | `opinion` | `debate.questions` |

- 토론을 하지 않았으면(`held=False`) `debate` 구역은 "토론 개시 기준 미달" 한 문장, `questions` 는 비운다. 신호가 0건이면 `changes` 는 "특이 변화 없음" 한 문장(`opinion`).
- 숫자는 신호 필드 값을 `fmt_*` 로 바꿔 넣는다. 문자열로 직접 쓰지 않는다.
- `sources` 는 모든 문장의 근거를 모아 `(source, url, as_of)` 가 같은 것을 하나로 합친 것.
- `apply_verify(draft, verify, drop_mismatched)`: `unsupported_idx` 의 문장은 항상 빼고, `drop_mismatched=True` 면 `mismatches` 의 `sentence_idx` 문장도 뺀다. 뺀 문장의 본문 목록을 함께 돌려줘 `removed_sentences` 에 넣는다(반환 형태는 구현하면서 정하되 테스트로 고정).

### PDF — `pdf.py` (`render_pdf`)
- `fpdf2` 로 A4 1장. `assets/fonts/` 의 한글 폰트를 등록해 쓴다. 폰트 등록 방법은 설치한 `fpdf2` 버전 문서를 따른다.
- 구성(예선 기획서 4쪽 예시 화면 순서): 제목(운용사, 점검 반기, 기준일) → 권고 → 감지된 변화 → 토론 요약 → 선택지별 근거 → 미팅 질문 3개 → 출처(문서명·기준일·URL).
- 맨 아래에 꼭 넣을 것: "최종 결정은 담당자가 합니다. 본 리포트의 권고는 공시 변화에 한정됩니다." / 확인 불가 항목 / 삭제된 문장 내역 / 알림(`notices`) / 생성 시각.
- 1장을 넘치면: 먼저 `explanation` 문장을 빼고, 그래도 넘치면 토론 요약을 변화별 심판 문장만 남긴다. 무엇을 뺐는지는 PDF 하단에 "지면상 생략: …"으로 적는다.
- 만든 PDF를 직접 열어 한글이 깨지지 않는지 확인한다(자동 테스트로는 "PDF 바이트가 비어 있지 않고 1쪽인가"만 본다).

## B5. 노드 연결과 E2E (11/25~29)

- 파트별 실제 함수가 올라오는 대로 mock을 바꿔 끼운다. 순서: 수집 → 분석 → 토론 → 검증.
- **11/29 E2E v0 통과 기준:** 운용사 1곳, 데모 모드, 입력 → 리포트 초안까지 예외 없이 실행. 13F 비교표·간단한 심판·임시 기준값이어도 된다. 못 돌면 그날 A10의 줄이는 순서대로 범위를 줄인다.
- **12/6 데모 완성 기준:** 3곳 모두 실제 데이터로 화면에서 입력 → PDF 다운로드.
- `tests/integration/` (모두 mock으로, LLM·네트워크 없이):
  - [ ] 전체 흐름이 `status="done"` 으로 끝나고 `stream_run` 이 `plan → collect → analyze → debate → draft → verify → done` 순서로 내보냄
  - [ ] 실제 모드 + 검증 실패(`failed_step="debate"`) → `debate` 부터 다시 실행되고 `retries` 가 1
  - [ ] 실제 모드 + 계속 실패 → 재수행 2회 뒤 멈추고, 불일치 문장이 삭제되고 `notices` 에 알림
  - [ ] 데모 모드 + 검증 실패 → 재수행 0회, 문장 삭제 + 알림
  - [ ] `failed_step=None` 인 실패 → 재수행 0회, 문장 삭제 + 알림
  - [ ] `has_new_filing=False` → `early_exit`
  - [ ] 운용사를 못 찾는 요청 → `status="failed"`
  - [ ] `debate_required=False` → 토론 없이 리포트가 나옴
  - [ ] 13F 없는 운용사 샘플도 끝까지 실행됨
  - [ ] 노드 하나가 예외를 던져도 그래프가 죽지 않고 `notices` 에 남음

## B6. 근거 검색 RAG (12/1~5) — `src/rag/`

기획서 ④에 적은 기술이다("ADV 브로셔 임베딩, Chroma에 문서명·페이지 저장"). 로컬(실제 모드)에서만 돌고, 배포본은 `analysis.json` 에 저장된 결과를 쓴다(A9).

```python
def build_index(manager_id: str, adv2a: AdvPart2A) -> int: ...          # 넣은 문단 수
def search_evidence(manager_id: str, query: str, k: int = 3) -> list[Evidence]: ...
```
- 문단 나누기: Item별 본문을 빈 줄 기준으로 나누고 100자 미만 문단은 버린다.
- 저장: Chroma를 `data_cache/raw/chroma/` 에 파일로 저장(GitHub에 올리지 않음), 운용사마다 컬렉션 하나. 문단마다 `item`, `page`(Item 시작 페이지), `url`, `filed_date` 를 함께 넣는다.
- 임베딩은 Chroma 기본 설정을 쓴다(처음 한 번 모델을 내려받는다). 브로셔가 영어라서 **질의도 영어로** 한다. 질의문은 `config.RAG_QUERIES` 에 둔다:
  ```python
  RAG_QUERIES = {"strategy": "investment strategy and methods of analysis"}
  ```
- 반환: `Evidence(source="Form ADV Part 2A Item <N>", url, as_of=filed_date, page, quote=문단 앞 200자 원문 그대로)`.
- `chromadb` 는 함수 안에서 불러온다. 설치돼 있지 않거나 색인이 없으면 예외 대신 `[]` 를 돌려준다. 이 경우 Data의 `strategy.py` 가 Item 8 본문을 직접 쓰는 방식으로 돌아간다(미리 정해 둔 대체 경로).
- Chroma 함수 이름은 설치한 버전 문서를 보고 쓴다(A12-3).
- 테스트: 문단 3개짜리 가짜 브로셔로 색인을 만들고 질의하면 관련 문단이 1위로 나오고, `quote` 가 원문의 부분 문자열이다. `chromadb` 가 없는 척했을 때 `[]` 가 나온다.
- 12/5까지 안 되면 여기서 멈추고 대체 경로로 간다. 발표에서 "RAG는 로컬 시험 단계"라고 밝힌다.

## B7. 통합 테스트와 측정 (12/7~13)

- 3곳을 데모 모드/실제 모드로 각각 반복 실행하고, 버그는 GitHub Issues에 파트 라벨(`frontend / backend / data / pm`)을 붙여 배정한다.
- `logs/llm_calls.jsonl` 로 **시연 1회에 걸리는 시간과 비용**을 운용사별로 정리한다. 실제 모드 1회의 LLM 호출은 분석 2 + 토론 8 = 10번이어야 한다(검증 재수행이 있으면 그만큼 늘어난다). 다르면 원인을 찾는다.
- 발표용 수치(예선 기획서 ⑦에서 약속한 것):
  - 3곳에 대해 사람이 손으로 공시를 모아 비교할 때 걸리는 시간 대비 에이전트 소요 시간(사람 쪽은 팀원이 실제로 해 보고 잰다)
  - 보도된 실제 사례(CIO 교체 등)를 신호로 잡아냈는지
  - 리포트 수치의 원문 일치 건수(김지유의 `docs/number_audit.md`)
- **12/13 기능 동결.** 이후에는 버그 수정과 발표 자료만.

### PM이 챙길 확인 사항
| 확인할 것 | 언제 | 누구와 |
|---|---|---|
| ADV 자동 수집이 실제로 되는가. Schedule A가 코드로 읽히는가(못 읽으면 확인 불가로 두고 발표에서 밝힘, 11/12 결정) | 11/16 | 조재연 |
| `sec_client.py` 가 올라왔는가(김지유의 종목 식별 도구가 쓴다) | 11/16 | 조재연, 김지유 |
| 12/1에 ADV Part 1 비교가 끝났는가. 안 끝났으면 ADV 2A 문구 비교를 내가 넘겨받는다 | 12/1 | 조재연 |
| 기본값 점검: 설명됨 점수 차, 선택지 개수 규칙, 규모 경계, 인덱스형 기준, 관찰 신호(Peer·문구·운용자산·직원·사모펀드) 기준, 임원 변경 범위 | 12/5 | 임동욱, 김지유 |
| 분기당 토론 대상 비율(목표 10% 안팎)과 업종·규모 기준값이 실제 분포로 되었는가 | 12/5 | 김지유 |
| 본선 공지의 AI 코드 사용 규정, 생성형 AI 용도 표기 | 12/3 발표 직후 | 전원 |
| 배포 서버에서 3곳이 메모리 문제 없이 도는가 | 12/7~9 | 조재연 |
| LLM 비용과 시연 1회 시간, 3회 반복 시 권고가 같은지 | 12/7~13 | 임동욱 |

## B8. `CLAUDE.md` (레포 최상위에 둘 내용)

```markdown
# 망루 — 공통 규칙
KIC 위탁운용사 반기 점검을 돕는 AI 에이전트. SEC 공시(13F, Form ADV)에서 변화를 찾고,
변화를 근거로 유지 측·해지 측 토론을 거쳐 `유지 / 조건부 유지 / 해지 검토` 근거를 낸다. 결정은 사람이 한다.

## 먼저 읽기
`docs/CONTRACT.md`(공통 계약) → `docs/parts/<내 파트>.md`

## 절대 규칙
1. 숫자는 코드로 계산한다. LLM은 계산하지 않고, 주어진 표기를 그대로 옮긴다.
2. 사실 문장마다 출처(문서명·URL·기준일). 해석은 의견으로 구분.
3. 없거나 막힌 데이터는 `확인 불가`. 지어내지 않는다.
4. 키·개인정보를 코드·커밋·로그에 넣지 않는다.
5. SEC 요청은 초당 10회 이하, User-Agent 필수.
6. 내 파트 폴더만 수정한다. `src/state.py`, `src/config.py` 는 PM만.

## 작업 방식
- 한 번에 한 기능. 테스트 먼저, 통과 후 커밋.
- 외부 주소·열 이름·응답 필드·모델 ID·라이브러리 함수는 추측하지 않는다. 실제로 확인하고 `docs/verified.md` 에 적는다.
- 파일 입출력은 `encoding="utf-8"`. 숫자 표기는 `src/report/format.py` 만.
- 개발 중에는 `LLM_MOCK=1`.

## 폴더 소유
collect/(sec_client 포함), app.py, ui/ = Frontend · analysis/(securities 포함) = Data · debate/, llm.py = Backend · graph.py, report/, rag/, state.py, config.py, validate.py = PM

## 실행
pip install -r requirements-dev.txt / streamlit run src/app.py / pytest
기본은 데모 모드(저장본 사용).
```

## B9. 발표 준비

- **발표 목차(12/1~5):** 예선 기획서 흐름을 그대로 쓴다: 문제 정의 → 서비스 제안·차별성 → Agent 역할·Workflow → 기술·도구 → 데이터 → MVP 시연 → 기대효과·확장. 본선 심사 기준이 12/3 공지에 나오면 항목마다 슬라이드를 대응시킨다.
- 본선에서는 예시 화면 대신 **실제 화면 캡처와 측정 수치**(B7)를 넣는다.
- **한계를 숨기지 않는다.** 발표 자료에 적을 것: 13F는 운용사 전체 합산·45일 지연, 분기 말 가격으로 매매를 근사, 임시 기준값을 쓴 지표, 저장본을 쓴 데이터, 구현하지 못한 Should.
- **시연 영상(12/17~20):** 데모 URL에서 입력 → 진행 상황 → 결과 → PDF 다운로드를 한 번에 녹화. 발표 당일 라이브 시연이 안 되면 이 영상을 튼다.
- **README(12/16~19):** 실행 방법, 폴더 구조, 데이터 출처와 이용 조건, 생성형 AI 사용 내역, 한계. 각 파트가 `docs/notes/<파트>.md` 를 바탕으로 자기 부분을 쓰고 내가 합친다.
- **예상 Q&A(12/22~25):** 각 파트가 자기 부분 질문 3개씩 답을 써 오면 합친다. 꼭 들어갈 질문: "13F는 운용사 전체인데 KIC 계좌 변화는?", "기존 실사 플랫폼과 무엇이 다른가?", "토론이 LLM끼리 말 돌리기 아닌가?", "검증은 무엇을 잡고 무엇을 못 잡는가?", "대체자산 운용사는?", "틀린 신호의 책임은?".

## B10. 하지 말 것

- 다른 파트의 코드를 대신 고치지 않는다. 버그는 이슈로 넘긴다(급하면 담당자와 같이 본다).
- `state.py`·`config.py` 를 조용히 바꾸지 않는다. 바꾸면 샘플 JSON, `docs/CONTRACT.md`, 4개 파트 문서의 A장, `docs/decisions.md` 를 같이 고치고 팀에 알린다.
- 리포트 문장에 숫자를 직접 써넣지 않는다. 항상 신호 값 + `fmt_*`.
- 기능 동결(12/13) 이후에 새 기능을 받지 않는다.

# C. 지금 바로 할 일 (AI와 함께 이 순서로)

1. GitHub 레포를 만들고 A5 폴더 구조, `.gitignore`, `requirements*.txt`, `.env.example`, `CLAUDE.md`(B8), 폰트를 올린다.
2. `src/state.py`(A6 그대로), `src/config.py`(A8 그대로), `src/validate.py` 를 작성한다.
3. `tests/fixtures/` 에 계약 샘플 5개를 만들고 `validate` 테스트를 통과시킨다. **여기까지가 11/15 "데이터 형식 확정"이다.** 끝나면 팀에 알린다.
4. `src/report/format.py` 와 테스트(A7의 예 전부 + B4의 추가 테스트)를 만든다. 다른 파트가 바로 쓴다.
5. `src/graph.py`: 모든 노드가 mock을 부르는 흐름을 만들고 `stream_run` 으로 단계가 순서대로 나오는지 확인한다. B5의 통합 테스트를 먼저 쓴다.
6. `draft_report` → `apply_verify` → `render_pdf` 를 샘플 JSON으로 구현한다. PDF를 열어 한글을 확인한다.
