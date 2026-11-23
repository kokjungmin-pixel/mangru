# data 노트 (김지유)

기능 하나가 끝날 때마다 3줄씩 남긴다 (발표 Q&A에서 본인이 설명할 수 있게).

## 기능 이름 (날짜)
- 무엇을 하는가:
- 어떻게 하는가:
- 한계:

## 종목 식별 도구 enrich_cusips (2026-11-17)
- 무엇을 하는가: 13F의 CUSIP 목록을 받아 종목마다 티커, 발행사 CIK, 업종 SIC, 발행주식 수, ETF 여부를 붙인다. 업종·규모 지표와 매핑률 계산의 재료가 된다.
- 어떻게 하는가: OpenFIGI로 CUSIP → 티커·종목 유형(securityType "ETP"면 ETF, "ADR"이면 예탁증서), SEC 티커 목록으로 CIK, submissions로 SIC, XBRL로 분기 말에 가장 가까운 발행주식 수를 찾는다. 결과는 `security_master.json` 에 저장해 다시 묻지 않고, 실패는 `enrich_log.jsonl` 에 남기며 그 값만 None으로 둔다.
- 한계: 예탁증서는 발행주식 수를 None으로 둔다(1주 단위가 달라 시가총액이 틀어짐). 종목명 기준 ETF 대체 판별(`is_etf_by_name`)은 이 함수가 종목명을 받지 않아 수집 쪽에서 불러야 한다. SEC가 일시적으로 안 될 때 발행주식 수가 None으로 저장될 수 있어, 그때는 `security_master.json` 을 지우고 다시 돌린다.

## enrich_cusips 빈칸 보완 (2026-11-23)
- 무엇을 하는가: 데모 저장본에서 비어 있던 해외 발행사 티커와, 주식 종류가 여러 개인 회사의 발행주식 수를 채운다.
- 어떻게 하는가: 영문자로 시작하는 번호는 OpenFIGI 에 ID_CINS 로 한 번 더 묻는다. 발행주식 수는 dei → us-gaap 발행주식 수 → us-gaap 분기 가중평균 주식 수 순서로 보고, as_of ±120일 값이 있는 첫 항목을 쓴다. `scripts/analysis_build_security_master.py` 로 데모 운용사의 security_master.json 을 처음부터 다시 만든다.
- 한계: 가중평균 주식 수는 분기 말 시점 값이 아니라 분기 평균이라 시가총액이 조금 다를 수 있다. Visa·Brookfield 처럼 세 항목 모두 없는 회사는 여전히 None 이다.
