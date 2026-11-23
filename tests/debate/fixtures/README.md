# LLM mock 응답 (`LLM_MOCK=1`)

`src/llm.py` 가 `LLM_MOCK=1` 일 때 실제 호출 대신 돌려주는 **원문 응답 텍스트**다.
파일 이름은 `<role>_<json_keys 첫 키>.txt` (json_keys 가 없으면 `<role>_text.txt`).
내용은 `tests/fixtures/debate.sample.json`(계약 샘플)에서 옮겼다. 심판의 A측 = 유지 측, B측 = 해지 측.
반박(`*_rebuttals.txt`)은 계약 샘플에 인력 신호 것만 있어, 토론 응답 검사(모든 신호에 반박)를 통과하도록
운용자산 신호 반박 1개씩을 더했다. 반박 1·2회차에 같은 응답이 나간다.
파일이 없으면 `call_llm` 은 `LLMUnavailable` 을 낸다.

## 토론 입력
- `a11_analysis.json`: CONTRACT A11 신호 3개(인력 경보·소형주 비중 경보·Peer 대비 관찰)를 담은 `AnalysisResult`.
  밝힌 전략은 `tests/fixtures/analysis.sample.json` 것. 토론 테스트(`test_rounds.py`)의 입력이다.
