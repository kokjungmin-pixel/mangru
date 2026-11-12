# 망루 (Mangru) — 위탁운용사 점검 AI 에이전트

KIC(한국투자공사) 위탁운용사 반기 점검을 돕는 AI 에이전트. SEC 공시(13F, Form ADV)에서 변화를 찾고,
그 변화를 두고 **유지 측·해지 측 AI 토론**을 거쳐 `유지 / 조건부 유지 / 해지 검토` 각각의 근거를 1장 리포트로 낸다.
최종 결정은 사람이 한다.

> 국부펀드 KIC AI 에이전트 공모전 · 팀 망루지기

```
입력 → ①계획 → ②수집 → ③변화 감지 → ④토론 → ⑤점검 리포트 → ⑥검증 ─통과→ PDF
                                   ↑            ↑                    │
                                   └── 실패하면 해당 단계부터 다시 (최대 2회)
```

## 팀과 담당 폴더

| 파트 | 담당 | 폴더 | 개발 기획서 |
|---|---|---|---|
| PM | 김정민 | `src/graph.py` `src/report/` `src/rag/` `src/state.py` `src/config.py` | [docs/parts/1_PM_김정민.md](docs/parts/1_PM_김정민.md) |
| Frontend | 조재연 | `src/collect/` `src/app.py` `src/ui/` | [docs/parts/2_Frontend_조재연.md](docs/parts/2_Frontend_조재연.md) |
| Backend | 임동욱 | `src/debate/` `src/llm.py` `prompts/debate/` | [docs/parts/3_Backend_임동욱.md](docs/parts/3_Backend_임동욱.md) |
| Data | 김지유 | `src/analysis/` `prompts/analysis/` | [docs/parts/4_Data_김지유.md](docs/parts/4_Data_김지유.md) |

공통 계약(데이터 모양, 함수 이름, 절대 규칙)은 [docs/CONTRACT.md](docs/CONTRACT.md), 일정은 노션 '개발 계획' 캘린더.

## 처음 한 번 (설치)

```bash
git clone https://github.com/kokjungmin-pixel/mangru.git
cd mangru
python3.11 -m venv .venv          # 윈도우: py -3.11 -m venv .venv
source .venv/bin/activate         # 윈도우: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env              # 윈도우: copy .env.example .env  → 값은 PM이 개인 메시지로 줌
pytest                            # 전부 통과하면 준비 끝
```

## 실행

```bash
streamlit run src/app.py   # 화면 (기본은 데모 모드: 저장본으로 돌아서 키 없이도 됨)
pytest                     # 테스트
```

## 지금 상태

모든 단계가 **가짜(mock)** 로 연결돼 있어서 처음부터 끝까지 이미 돈다. 각자 자기 파일의 `TODO(이름)` 부분을
진짜 구현으로 바꾸면 된다. 가짜는 `tests/fixtures/` 의 계약 샘플을 돌려준다.

| 함수 | 파일 | 지금 | 담당 |
|---|---|---|---|
| `make_plan` | `src/plan.py` | ✅ 동작 | PM |
| `collect` | `src/collect/__init__.py` | 가짜 | 조재연 |
| `sec_get` | `src/collect/sec_client.py` | 빈칸 (11/16) | 조재연 |
| `enrich_cusips` | `src/analysis/securities.py` | 가짜 | 김지유 |
| `analyze` | `src/analysis/__init__.py` | 가짜 | 김지유 |
| `run_debate` | `src/debate/__init__.py` | 가짜 | 임동욱 |
| `call_llm` | `src/llm.py` | 빈칸 | 임동욱 |
| `draft_report` / `apply_verify` | `src/report/draft.py` | 가짜 / ✅ | PM |
| `verify_report` | `src/analysis/verify.py` | 가짜 (항상 통과) | 김지유 |
| `render_pdf` | `src/report/pdf.py` | 빈칸 | PM |
| `stream_run` | `src/graph.py` | ✅ 동작 (LangGraph) | PM |
| 숫자 표기 `fmt_*` | `src/report/format.py` | ✅ 동작 | PM |

## 협업 규칙

[CONTRIBUTING.md](CONTRIBUTING.md) — 브랜치 만들기부터 PR까지 순서대로. AI 코딩 도구를 쓸 땐 [CLAUDE.md](CLAUDE.md) 를 꼭 읽히기.

## 데이터 출처

- SEC EDGAR (Form 13F, Form ADV), IAPD — 미국 증권거래위원회 공개 데이터
- OpenFIGI — 종목 코드 변환
- 폰트: 나눔고딕 (SIL OFL 1.1)
