"""데모 저장본 만들기: python -m src.collect demo1 demo2 demo3 --live (Frontend B3 "조립")"""
import sys

from src.collect import collect_live, save_demo
from src.config import DEMO_MANAGERS

ids = [a for a in sys.argv[1:] if a != "--live"]
if "--live" not in sys.argv or not ids or any(i not in DEMO_MANAGERS for i in ids):
    sys.exit(f"사용법: python -m src.collect <{'|'.join(DEMO_MANAGERS)}> ... --live")
for mid in ids:
    data = collect_live(mid)
    print(f"{mid} {data['manager_name']}: 13F {len(data['quarters'])}분기, has_new_filing={data['has_new_filing']}, "
          f"확인 불가 {len(data['unavailable'])}건 → {save_demo(data)}")
