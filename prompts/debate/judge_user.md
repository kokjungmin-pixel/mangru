{{body}}

[할 일 — 채점]
위 신호 하나하나에 대해 A측과 B측을 점수표로 채점하고 한 줄 이유를 쓰십시오.
- signal_id: 위 신호의 id를 그대로
- A, B: {"numbers": 0~3, "grounds": 0~3, "rebuttal": 0~2, "limits": 0~2} (정수)
- reason: 두 측의 점수 차이를 만든 이유 한 줄

아래 키를 가진 JSON만 출력하십시오. 설명 문장은 붙이지 않습니다.
{"scores": [{"signal_id": "...", "A": {"numbers": 0, "grounds": 0, "rebuttal": 0, "limits": 0}, "B": {"numbers": 0, "grounds": 0, "rebuttal": 0, "limits": 0}, "reason": "..."}]}
