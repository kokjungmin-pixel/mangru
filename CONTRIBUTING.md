# 같이 개발하는 방법

처음 Git을 써 봐도 이 순서대로만 하면 된다. 모르는 게 있으면 PM에게 물어보기.

## 용어 먼저

| 용어 | 뜻 |
|---|---|
| 레포(repository) | 팀 코드 저장소. 이 GitHub 페이지 |
| 클론(clone) | 레포를 내 컴퓨터로 복사 (처음 한 번) |
| 브랜치(branch) | 내 작업용 가지. 여기서 마음껏 고쳐도 `main` 은 안 망가짐 |
| 커밋(commit) | "여기까지 저장" 한 단위 |
| 푸시(push) | 내 커밋을 GitHub에 올리기 |
| PR(Pull Request) | "내 브랜치를 main에 합쳐 주세요" 요청. 리뷰 후 PM이 합침 |
| `main` | 언제나 돌아가는 상태의 본 줄기. **직접 푸시 금지** (막혀 있음) |

## 매번 하는 순서

```bash
# 1) 최신 main 받기
git checkout main
git pull

# 2) 작업 브랜치 만들기 — 이름: feat/<파트>-<기능>
git checkout -b feat/data-metrics

# 3) 코드 고치고 테스트
pytest

# 4) 저장하고 올리기
git add src/analysis/metrics.py tests/analysis/test_metrics.py
git commit -m "Data: 집중도·회전율 계산 + 손 계산 테스트"
git push -u origin feat/data-metrics

# 5) GitHub에서 'Compare & pull request' 버튼 → 템플릿 체크리스트 채우고 PR 만들기
```

- 파트 이름: `frontend` / `backend` / `data` / `pm`. 예) `feat/frontend-sec-client`, `feat/backend-judge`
- 버그 고칠 땐 `fix/<파트>-<내용>`
- PR은 **작게**(기능 하나). 크면 리뷰도 못 하고 충돌 남
- PR을 올리면 GitHub가 자동으로 `pytest` 를 돌린다(Actions). ❌가 뜨면 고쳐서 다시 푸시

## 규칙 5개

1. **내 폴더만 고친다.** 담당 폴더는 README 표. 다른 파트 문제는 이슈(버그 템플릿)로 알린다.
2. `src/state.py`, `src/config.py`, `tests/fixtures/` 는 **PM만** 고친다. 바꿔야 하면 먼저 말하기.
3. **비밀값 금지.** API 키·이메일은 `.env` 에만. 실수로 올렸으면 바로 PM에게 (키를 새로 발급해야 함).
4. 숫자는 코드로 계산하고 표기는 `src/report/format.py`. 없는 데이터는 `확인 불가`.
5. 기능 하나 끝나면 `docs/notes/<파트>.md` 에 3줄(무엇을/어떻게/한계).

## AI 코딩 도구로 작업할 때

- 시작할 때 "`CLAUDE.md` 와 `docs/parts/<내 파일>.md` 를 읽고 C장 순서대로 시작해줘"
- AI가 주소·열 이름·모델 이름을 "아마 이럴 것"이라고 쓰면 믿지 말고 직접 확인 → `docs/verified.md`
- 개발 중엔 `.env` 의 `LLM_MOCK=1` (실제 AI 호출은 돈이 든다)

## 막혔을 때

- 충돌(conflict)이 나면 혼자 해결하려 하지 말고 PM 호출
- `main` 이 깨졌으면(테스트 ❌) 단톡방에 바로 알리기
