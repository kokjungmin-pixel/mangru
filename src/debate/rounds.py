"""토론 1~3단계: 독립 작성 → 반박 1회차 → 반박 2회차 (Backend · 임동욱).
규칙은 docs/parts/3_Backend 문서 B3 "양측에게 주는 자료"·"입장"·"응답 검사", B5 "1라운드 합의".

- 호출 수: 독립 작성 2 + 반박 2회 × 양측 = 정상 6번. 응답 검사에 걸리면 그 호출만 1회 재요청한다
  (검사 여러 개가 걸려도 문제를 모두 적어 한 번에 재요청 → 검사 하나당 재요청 1회를 넘지 않는다).
- 재요청 뒤에도 남은 문제는 코드가 정리한다: 빠진 신호는 논거·반박 없음, 새 숫자가 있는 항목은 삭제.
  둘 다 warnings 에 남긴다.
- LLMUnavailable 은 여기서 잡지 않는다. run_debate 가 B5 "토론 실패" 로 처리한다.
"""
from src import config
from src.llm import call_llm
from src.report.format import (
    fmt_count, fmt_multiple, fmt_pp, fmt_ratio, fmt_signed_ratio, fmt_top_pct, fmt_usd, unknown_numbers,
)
from src.state import AnalysisResult, Argument, Rebuttal, Signal

PROMPT_DIR = config.ROOT / "prompts" / "debate"
SIDES = ("keep", "terminate")
SIDE_LABEL = {"keep": "유지 측", "terminate": "해지 측"}
OPPONENT = {"keep": "terminate", "terminate": "keep"}
REBUTTAL_ROUNDS = 2

KIND_LABEL = {"strategy_drift": "전략 이탈", "key_person": "핵심 인력", "peer_anomaly": "Peer 대비"}
LEVEL_LABEL = {"alert": "경보", "watch": "관찰"}
NO_STRATEGY = "운용사가 밝힌 전략을 확인할 수 없음"
DATA_LIMITS = ("13F는 분기 말 기준이고 분기 종료 후 45일 안에 공시되어 늦게 보인다. "
               "운용사 전체 계좌를 합산한 값이며 미국 상장 주식 등 13F 대상 종목만 담는다.")


def _prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


def _fill(template: str, **values: str) -> str:
    for k, v in values.items():
        template = template.replace("{{" + k + "}}", v)
    return template


# ---------- 양측에게 주는 자료 (같은 내용) ----------
def number_labels(sig: Signal) -> list[str]:
    """신호의 숫자 필드를 src/report/format.py 로 표기한 문자열. LLM에게는 이것만 준다."""
    b, a, unit = sig["before"], sig["after"], sig["unit"]
    out = []
    if unit == "ratio":
        out += [f"직전 {fmt_ratio(b)}"] if b is not None else []
        out += [f"최신 {fmt_ratio(a)}"] if a is not None else []
        out += [f"변화 {fmt_pp(sig['change'])}"] if sig["change"] is not None else []
        out += [f"매매 기준 변화 {fmt_pp(sig['active_change'])}"] if sig["active_change"] is not None else []
        if sig["peer_median"] is not None:
            out.append(f"전체 운용사 중앙값 {fmt_ratio(sig['peer_median'])}")
            if a is not None and fmt_multiple(a, sig["peer_median"]):
                out.append(f"중앙값 대비 {fmt_multiple(a, sig['peer_median'])}")
    elif unit in ("usd", "count"):
        show = fmt_usd if unit == "usd" else (lambda v: fmt_count(v, "명"))
        out += [f"직전 {show(b)}"] if b is not None else []
        out += [f"최신 {show(a)}"] if a is not None else []
        if b and a is not None:
            out.append(f"증감률 {fmt_signed_ratio((a - b) / b)}")
    if sig["percentile"] is not None:
        out.append(f"전체 13F 운용사 분포 {fmt_top_pct(sig['percentile'])}")
    return out


def _evidence_line(i: int, ev: dict) -> str:
    parts = [ev["source"], ev["as_of"]]
    if ev.get("page") is not None:
        parts.append(f"p.{ev['page']}")
    line = f"  [{i}] " + ", ".join(parts) + f" ({ev['url']})"
    if ev.get("quote"):
        line += f' "{ev["quote"]}"'
    return line


def strategy_lines(analysis: AnalysisResult) -> tuple[list[str], list[str]]:
    """밝힌 전략 부분과 warnings. 토론 양측과 심판이 같이 쓴다."""
    lines = ["[운용사가 밝힌 전략 — 판단 기준]"]
    if not analysis["stated_strategy"]:
        return lines + [NO_STRATEGY], [NO_STRATEGY]
    lines.append(analysis["stated_strategy"])
    lines += [_evidence_line(i, ev) for i, ev in enumerate(analysis["stated_strategy_evidence"])]
    return lines, []


def signal_lines(s: Signal) -> list[str]:
    """신호 하나: 제목(## id) · 요약 · 설명 · 숫자 표기 · 번호 매긴 근거."""
    lines = [f"## {s['id']} ({KIND_LABEL[s['kind']]} · {LEVEL_LABEL[s['level']]} · {s['source_form']})",
             f"요약: {s['summary']}",
             f"설명: {s['explanation']}"]
    nums = number_labels(s)
    if nums:
        lines.append("숫자 표기: " + ", ".join(nums))
    lines.append("근거:")
    return lines + [_evidence_line(i, ev) for i, ev in enumerate(s["evidence"])]


def material(analysis: AnalysisResult) -> tuple[str, list[str]]:
    """양측에게 똑같이 주는 자료 문장과 warnings."""
    lines, warnings = strategy_lines(analysis)
    lines += ["", "[신호 목록]"]
    for s in analysis["signals"]:
        lines += signal_lines(s)

    lines += ["", "[데이터 한계]", DATA_LIMITS,
              "", "[숫자 규칙] 숫자는 위에 주어진 표기를 그대로 옮겨 쓰고 새로 계산하거나 어림하지 마십시오."]
    return "\n".join(lines), warnings


# ---------- 응답 모양 ----------
def _is_idx_list(x) -> bool:
    return isinstance(x, list) and all(type(i) is int for i in x)


def _well_formed_argument(item) -> bool:
    return (isinstance(item, dict) and isinstance(item.get("signal_id"), str)
            and isinstance(item.get("claim"), str) and item["claim"].strip() != ""
            and _is_idx_list(item.get("evidence_idx"))
            and isinstance(item.get("falsifier"), str) and item["falsifier"].strip() != "")


def _well_formed_rebuttal(item) -> bool:
    return (isinstance(item, dict) and isinstance(item.get("signal_id"), str)
            and isinstance(item.get("text"), str) and item["text"].strip() != ""
            and type(item.get("concede")) is bool)


def _by_signal(items, well_formed, signal_ids: list[str]) -> dict[str, dict]:
    """모양이 맞고 아는 신호인 항목만, 신호당 처음 것 하나."""
    out = {}
    for item in items if isinstance(items, list) else []:
        if well_formed(item) and item["signal_id"] in signal_ids and item["signal_id"] not in out:
            out[item["signal_id"]] = item
    return out


# ---------- 응답 검사 (B3 표) ----------
def _problems(found: dict[str, dict], signal_ids: list[str], texts, signals: list[Signal]) -> list[str]:
    """재요청할 문제: 빠진 신호, 신호에 없는 숫자. 근거 번호는 재요청 없이 코드가 고친다."""
    problems = [f"논거·반박이 없거나 형식이 틀린 신호: {sid}" for sid in signal_ids if sid not in found]
    for sid, item in found.items():
        bad = unknown_numbers(texts(item), signals)
        if bad:
            problems.append(f"{sid}: 신호에 없는 숫자 {', '.join(bad)} — 주어진 표기만 쓰십시오")
    return problems


def _retry_user(user: str, problems: list[str]) -> str:
    return (f"{user}\n\n[이전 응답 검사 결과]\n" + "\n".join(f"- {p}" for p in problems)
            + "\n위 문제를 고쳐 모든 신호에 대해 같은 형식의 JSON 전체를 다시 출력하십시오.")


def _ask(role: str, system: str, user: str, key: str, well_formed, texts,
         analysis: AnalysisResult) -> dict[str, dict]:
    """1회 호출 + 문제가 있으면 1회 재요청. 신호 id → 항목 (아직 정리 전)."""
    signals = analysis["signals"]
    ids = [s["id"] for s in signals]
    found = _by_signal(call_llm(role, system, user, json_keys=[key])[key], well_formed, ids)
    problems = _problems(found, ids, texts, signals)
    if problems:
        found = _by_signal(call_llm(role, system, _retry_user(user, problems), json_keys=[key])[key],
                           well_formed, ids)
    return found


def _arg_text(item: dict) -> str:
    return f"{item['claim']}\n{item['falsifier']}"


def _clean_arguments(side: str, found: dict[str, dict], analysis: AnalysisResult,
                     warnings: list[str]) -> list[Argument]:
    label, out = SIDE_LABEL[side], []
    for s in analysis["signals"]:
        sid = s["id"]
        item = found.get(sid)
        if item is None:
            warnings.append(f"{label} 논거 없음: {sid}")
            continue
        idx = [i for i in item["evidence_idx"] if 0 <= i < len(s["evidence"])]
        if not idx:
            warnings.append(f"{label} 논거 삭제(근거 번호 없음): {sid}")
            continue
        bad = unknown_numbers(_arg_text(item), analysis["signals"])
        if bad:
            warnings.append(f"{label} 논거 삭제(신호에 없는 숫자 {', '.join(bad)}): {sid}")
            continue
        out.append({"signal_id": sid, "claim": item["claim"], "evidence_idx": idx,
                    "falsifier": item["falsifier"]})
    return out


def _clean_rebuttals(side: str, rnd: int, found: dict[str, dict], analysis: AnalysisResult,
                     warnings: list[str]) -> list[Rebuttal]:
    label, out = SIDE_LABEL[side], []
    for s in analysis["signals"]:
        sid = s["id"]
        item = found.get(sid)
        if item is None:
            warnings.append(f"{label} 반박 없음({rnd}회차): {sid}")
            continue
        bad = unknown_numbers(item["text"], analysis["signals"])
        if bad:
            warnings.append(f"{label} 반박 삭제({rnd}회차, 신호에 없는 숫자 {', '.join(bad)}): {sid}")
            continue
        out.append({"round": rnd, "side": side, "signal_id": sid, "text": item["text"],
                    "concede": item["concede"]})
    return out


# ---------- 반박 입력 ----------
def _show_args(args: list[Argument]) -> str:
    if not args:
        return "(없음)"
    return "\n".join(f"- {a['signal_id']}: {a['claim']} / 반증 조건: {a['falsifier']}" for a in args)


def _show_rebuttals(rebs: list[Rebuttal]) -> str:
    if not rebs:
        return "(없음)"
    return "\n".join(f"- {r['signal_id']}: {r['text']}" for r in rebs)


# ---------- 공개 함수 ----------
def run_rounds(analysis: AnalysisResult) -> dict:
    """독립 작성 → 반박 2회. 돌려주는 값: keep_args, terminate_args, rebuttals, warnings."""
    text, warnings = material(analysis)
    system = {side: _prompt(f"{side}_system.md") for side in SIDES}

    # 1) 독립 작성: 양측 모두 같은 자료만 보고, 서로의 글은 보지 않는다
    opening = _fill(_prompt("opening_user.md"), material=text)
    args = {}
    for side in SIDES:
        found = _ask(side, system[side], opening, "arguments", _well_formed_argument, _arg_text, analysis)
        args[side] = _clean_arguments(side, found, analysis, warnings)

    # 2)·3) 반박: 1회차는 상대의 논거, 2회차는 상대의 1회차 반박에 답한다
    template = _prompt("rebuttal_user.md")
    rebuttals: list[Rebuttal] = []
    last: dict[str, list[Rebuttal]] = {}
    for rnd in range(1, REBUTTAL_ROUNDS + 1):
        this_round = {}
        for side in SIDES:
            opp = OPPONENT[side]
            if rnd == 1:
                opp_label, opp_text = "논거", _show_args(args[opp])
            else:
                opp_label, opp_text = f"{rnd - 1}회차 반박", _show_rebuttals(last[opp])
            user = _fill(template, material=text, own=_show_args(args[side]),
                         opponent_label=opp_label, opponent=opp_text, round=str(rnd))
            found = _ask(side, system[side], user, "rebuttals", _well_formed_rebuttal,
                         lambda item: item["text"], analysis)
            this_round[side] = _clean_rebuttals(side, rnd, found, analysis, warnings)
            rebuttals += this_round[side]
        last = this_round

    # B5: 반박 1회차에서 어느 한쪽이라도 상대에 동의하면 "토론 불충분" (토론은 그대로 끝까지)
    conceded = {r["signal_id"] for r in rebuttals if r["round"] == 1 and r["concede"]}
    warnings += [f"토론 불충분: {s['id']}" for s in analysis["signals"] if s["id"] in conceded]

    return {"keep_args": args["keep"], "terminate_args": args["terminate"],
            "rebuttals": rebuttals, "warnings": warnings}
