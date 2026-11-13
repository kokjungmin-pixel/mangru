# LLM mock 응답 (`LLM_MOCK=1`)

`src/llm.py` 가 `LLM_MOCK=1` 일 때 실제 호출 대신 돌려주는 **원문 응답 텍스트**다.
파일 이름은 `<role>_<json_keys 첫 키>.txt` (json_keys 가 없으면 `<role>_text.txt`).
내용은 `tests/fixtures/debate.sample.json`(계약 샘플)에서 옮겼다. 심판의 A측 = 유지 측, B측 = 해지 측.
파일이 없으면 `call_llm` 은 `LLMUnavailable` 을 낸다.
