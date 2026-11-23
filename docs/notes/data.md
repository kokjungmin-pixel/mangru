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

## 지표 계산 compute_changes (2026-11-24)
- 무엇을 하는가: 이웃한 두 분기 보유 내역으로 업종 변화(sector_shift), 규모 변화(size_shift), 상위 10종목 집중도 변화, 회전율을 계산한다. `compute_series` 는 14개 분기를 넣으면 분기 쌍 13개의 결과를 돌려준다.
- 어떻게 하는가: docs/metrics.md 의 식 그대로. ETF를 빼고, 분할을 보정한 뒤, 주가 변화만으로 생긴 비중(passive)과 실제 비중의 차이(active_change)로 매매에 따른 변화를 본다. 매핑률·시가총액 확인 비율이 기준 아래면 그 지표는 None 이고 이유를 unavailable 에 적는다.
- 한계: 체결 가격을 몰라 분기 말 가격으로 근사한다. 반환값에 data_checks·unavailable·coverage 를 함께 담았다(문서의 함수 모양에는 지표만 적혀 있어 신호 판정에서 쓰려고 덧붙임).

## 13F 데이터셋 적재 load_quarter (2026-11-24)
- 무엇을 하는가: SEC Form 13F Data Sets 압축 파일을 data_cache/raw/13f/ 에 받아 두고, 한 보고 분기의 전체 운용사 보유 내역(CIK, 보고 기준일, CUSIP, 금액, 주식 수)을 돌려준다. 기준값 계산(B5)의 재료다.
- 어떻게 하는가: 분기는 PERIODOFREPORT 로 나누고, RESTATEMENT 정정이 있으면 가장 늦은 것, 없으면 원본을 쓴다. 옵션·원금 행은 빼고 2023-01-03 이전 제출분은 금액 ×1000. 한 번 읽은 분기는 quarters/<분기>.pkl 로 저장해 다시 읽지 않는다.
- 한계: 추가 정정(NEW HOLDINGS)은 반영하지 않는다. 2026Q3 보고분(2026년 9~11월 제출)은 SEC가 다음 파일을 올리기 전까지 받을 수 없다.
