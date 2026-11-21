"""화면에 그릴 값 만들기 (Frontend · 조재연). 계산은 하지 않고 상태 값을 옮기기만 한다 (B5 "지킬 것").
Streamlit 없이 테스트할 수 있게 app.py 와 나눴다."""
from src.graph import stream_run
from src.report.format import fmt_count, fmt_usd
from src.report.pdf import render_pdf


def progress_line(step: str, s: dict) -> str | None:
    """stream_run 의 한 단계 → 진행 상황 한 줄 (B5 표). 'done' 은 줄을 만들지 않는다."""
    if s["status"] == "failed" and s["notices"]:
        return f"중단: {s['notices'][-1]}"
    if step == "plan":
        p = s["plan"]
        return f"계획: {p['manager_name']}, {'13F 포함' if p['has_13f'] else '13F 제외(ADV만)'}"
    if step == "collect":
        if s["status"] == "early_exit":
            return "새 공시 없음 → 종료"
        d = s["data"]
        return f"수집 완료: 13F {fmt_count(len(d['quarters']), '개')} 분기, ADV 신·구본 (확인 불가 {fmt_count(len(d['unavailable']), '건')})"
    if step == "analyze":
        sig = s["analysis"]["signals"]
        alerts = sum(1 for x in sig if x["level"] == "alert")
        return f"신호 {fmt_count(len(sig), '건')} 감지 (경보 {alerts}, 관찰 {len(sig) - alerts})"
    if step == "debate":
        d = s["debate"]
        return f"토론 완료: 미설명 {fmt_count(d['unexplained_count'], '건')}" if d["held"] else "토론 기준 미달 → 토론 없음"
    if step == "draft":
        return "리포트 초안 작성"
    if step == "verify":
        v = s["verify"]
        return "검증 통과" if v and v["passed"] else "검증 실패 → 근거 없는·틀린 문장 삭제"
    return None


def verdict(s: dict) -> tuple[str, str]:
    """결과 상태 → (표시 종류 success/info/warning/error, 문장)."""
    if s["status"] == "failed":
        return "error", "점검 중단: " + (" / ".join(s["notices"]) or "원인 확인 필요")
    if s["status"] == "early_exit":
        return "info", "직전 점검 이후 새 공시가 없어 점검을 끝냈습니다."
    v = s.get("verify")
    if v and not v["passed"]:
        return "warning", f"검증 실패: 문장 {fmt_count(len(s['removed_sentences']), '개')}를 리포트에서 뺐습니다."
    return "success", "검증 통과"


def pdf_file(s: dict) -> tuple[bytes | None, str, str | None]:
    """→ (PDF, 파일 이름, 못 만든 이유). 리포트 초안이 없으면(중단·조기 종료) PDF 를 만들지 않는다."""
    mid = (s.get("plan") or {}).get("manager_id", "unknown")
    as_of = (s.get("draft") or {}).get("as_of", "")
    kind = verdict(s)[0]
    name = f"mangru_{mid}_{as_of}{'_검증실패' if kind == 'warning' else ''}.pdf"
    if s["status"] != "done" or not s.get("draft"):
        return None, name, "리포트가 만들어지지 않아 PDF 가 없습니다."
    try:
        return render_pdf(s), name, None
    except Exception as e:  # noqa: BLE001 — PDF 실패가 화면 전체를 멈추지 않게
        return None, name, f"PDF 생성 실패: {type(e).__name__}: {e}"


def manager_facts(s: dict) -> list[str]:
    """운용사 정보(최신 ADV Part 1). 값은 상태 그대로, 표기는 format.py."""
    p = (s.get("data") or {}).get("adv1_new")
    if not p:
        return ["운용사 정보: 확인 불가"]
    show = lambda v, f: "확인 불가" if v is None else f(v)
    return [f"운용자산 {show(p['aum_usd'], fmt_usd)}", f"직원 {show(p['employees'], lambda n: fmt_count(n, '명'))}",
            f"사모펀드 {show(p['private_funds'], lambda n: fmt_count(n, '개'))}",
            f"기준: ADV 제출일 {p['filed_date']} ({p['url']})"]


def run_check(manager_name: str, demo_mode: bool = True) -> dict:
    """그래프를 한 번 돌려 화면에 보관할 결과를 만든다."""
    lines, state = [], None
    for ev in stream_run(f"{manager_name} 반기 점검 준비해줘", demo_mode=demo_mode):
        state = ev["state"]
        line = progress_line(ev["step"], state) if ev["step"] != "done" else None
        if line and line not in lines:
            lines.append(line)
    pdf, name, pdf_error = pdf_file(state)
    return {"manager_name": manager_name, "state": state, "lines": lines, "pdf": pdf, "pdf_name": name,
            "pdf_error": pdf_error}
