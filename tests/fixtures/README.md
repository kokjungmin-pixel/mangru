# 계약 샘플 (fixture)

가짜지만 모양은 진짜와 똑같은 JSON. `docs/CONTRACT.md` A11 그대로다. **PM만 수정한다.**

| 파일 | 모양 (`src/state.py`) | 누가 만들고 누가 받나 |
|---|---|---|
| `manager_data.sample.json` | `ManagerData` | Frontend → Data |
| `analysis.sample.json` | `AnalysisResult` | Data → Backend·PM |
| `debate.sample.json` | `DebateResult` | Backend → PM |
| `draft.sample.json` | `ReportDraft` | PM → Data(검증) |
| `verify.sample.json` | `VerifyResult` (실패 예시) | Data → PM |
| `a11_signals.sample.json` | 신호 3개 (숫자 표기 테스트용) | |
