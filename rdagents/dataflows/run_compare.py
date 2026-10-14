"""두 심의 실행 결과 폴더를 같은 지표로 비교한다 (LLM 호출 없음).

설정·프롬프트·검증 규칙을 바꾼 뒤 다시 실행했을 때 무엇이 나아졌는지 숫자로 본다.
공정하게 비교하려면 두 폴더를 먼저 같은 코드로 다시 렌더링(--rerender)해 검증 기준을 맞춘다.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

OUTPUT_CAP = 3072          # Groq 기본 출력 상한 (출력 토큰이 이 값이면 잘린 응답)
LLM_FILES = ("01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11")


def _read(run: Path, name: str) -> str:
    path = run / name
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _label_int(text: str, label: str) -> int | None:
    m = re.search(rf"\*\*{re.escape(label)}\*\*:\s*([\d,]+)", text)
    return int(m.group(1).replace(",", "")) if m else None


def _llm_docs(run: Path) -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(run.glob("*.md")) if p.name[:2] in LLM_FILES}


def collect(run_dir: str) -> dict[str, object]:
    """실행 결과 폴더 하나의 비교 지표."""
    run = Path(run_dir)
    observation = _read(run, "12_실행관측성.md")
    validation = _read(run, "14_검증보고서.md")
    docs = _llm_docs(run)

    calls = [row for row in re.findall(r"^\| ([^|]+) \| ([^|]+) \| [\d.]+ \| (\d+) \| (\d+) \| (\d+) \|$",
                                       observation, re.M) if row[1].strip() != "도구/로직"]
    llm_calls = [(node.strip(), int(inp), int(out)) for node, _, inp, out, _ in calls]
    total = _label_int(observation, "보고된 총 토큰")

    questions, improvements, criteria = [], [], Counter()
    raw = _read(run, "07b_예상질의.json")
    if raw.strip().startswith("{"):
        data = json.loads(raw)
        questions, improvements = data.get("questions", []), data.get("improvements", [])
        criteria = Counter(q.get("criterion", "?") for q in questions)

    # 숫자 검산 결과가 공방·예상 질의로 이어졌는지: 사전 점검의 숫자 검산 절에 나온 표 번호가 언급되는가
    precheck = _read(run, "00b_사전점검.md")
    numbers_section = precheck.split("## 숫자 검산", 1)[1] if "## 숫자 검산" in precheck else ""
    mismatch = re.search(r"불일치\s*(\d+)건", numbers_section)
    table_ids = set(re.findall(r"표\s*\d+(?:\.\d+)*", numbers_section.split("- 숫자가 서로")[0]))
    reflected = sum(1 for name in ("02_심사공방_전문.md", "07_예상질의응답.md")
                    for line in _read(run, name).splitlines()
                    if any(t in line for t in table_ids)) if table_ids else 0

    decision = re.search(r"\*\*최종 심의 결정\*\*:\s*(\S+)", _read(run, "06_최종결정.md"))
    return {
        "결정": decision.group(1) if decision else "?",
        "총 토큰": total,
        "LLM 호출 수": len(llm_calls),
        "출력 상한에 닿은 호출 (잘림)": sum(out >= OUTPUT_CAP for _, _, out in llm_calls),
        "잘림 표시가 붙은 산출물 줄": sum(doc.count("출력 토큰 한도에 걸려") for doc in docs.values()),
        "가장 큰 입력 토큰": max((inp for _, inp, _ in llm_calls), default=0),
        "유효 출처 인용": _label_int(validation, "형식·범위가 유효한 출처 인용 수"),
        "출처 검증 이슈": _label_int(validation, "출처 검증 이슈 수"),
        "미확인 사실형 문장": _label_int(validation, "미확인 사실형 문장 수"),
        "출처 내용 대조 확인 권고": _label_int(validation, "출처 내용 대조 확인 권고 수"),
        "원문에 없는 수치 표시 줄": sum(doc.count("⚠️[원문에 없는 수치") for doc in docs.values()),
        "└ 그중 예상 질의·보완 권고": sum(_read(run, n).count("⚠️[원문에 없는 수치")
                                     for n in ("07_예상질의응답.md", "08_보완권고.md")),
        "예상 질의 수": len(questions),
        "보완 권고 수": len(improvements),
        "예상 질의 심의기준": ", ".join(f"{k} {v}" for k, v in criteria.most_common()) or "-",
        "숫자 검산 불일치 (사전 점검)": int(mismatch.group(1)) if mismatch else None,
        "숫자 검산 표가 공방·질의에 언급된 줄": reflected,
    }


def _fmt(value: object) -> str:
    if value is None:
        return "-"
    return f"{value:,}" if isinstance(value, int) else str(value)


def _change(a: object, b: object) -> str:
    if isinstance(a, int) and isinstance(b, int):
        return f"{b - a:+,}" if a != b else "같음"
    return "같음" if a == b else "바뀜"


def render(run_a: str, run_b: str) -> str:
    a, b = collect(run_a), collect(run_b)
    lines = ["# 실행 결과 비교", "",
             f"- A: `{run_a}`", f"- B: `{run_b}`", "",
             "| 지표 | A | B | 변화 (B−A) |", "|---|---|---|---|"]
    lines += [f"| {key} | {_fmt(a[key])} | {_fmt(b[key])} | {_change(a[key], b[key])} |" for key in a]
    lines += ["", "- 검증 지표(인용·이슈·확인 권고·원문에 없는 수치)는 각 폴더의 14_검증보고서를 만든 코드 기준입니다. "
              "같은 기준으로 비교하려면 두 폴더를 먼저 `--rerender`로 다시 만드세요.",
              f"- '출력 상한에 닿은 호출'은 출력 토큰이 {OUTPUT_CAP:,} 이상인 LLM 호출 수입니다 (Groq 기본 상한에서 잘린 응답).",
              "- 체크포인트로 이어서 실행한 결과는 앞 실행의 호출도 함께 집계됩니다."]
    return "\n".join(lines)
