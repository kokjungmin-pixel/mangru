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
