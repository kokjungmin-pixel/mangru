{{material}}

[당신의 논거]
{{own}}

[상대 측의 {{opponent_label}}]
{{opponent}}

[할 일 — 반박 {{round}}회차]
신호마다 상대의 글에 반박하십시오. 상대의 가장 강한 논거를 골라 직접 답하십시오.
상대 글이 없는 신호는 당신의 논거를 보강하십시오.
- signal_id: 위 신호 목록의 id를 그대로
- text: 반박 (두세 문장)
- concede: 이 신호에서 상대 주장에 동의하게 되었으면 true, 아니면 false

아래 키를 가진 JSON만 출력하십시오. 설명 문장은 붙이지 않습니다.
{"rebuttals": [{"signal_id": "...", "text": "...", "concede": false}]}
