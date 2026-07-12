# 심의 이력 메모리 — 실행 요약을 누적 기록하고 동일 사업 재심의 시 이전 이력을 로드
"""보완 전후 비교가 목적: 같은 project_id로 재심의하면 이전 지적사항이 컨텍스트로 주입된다."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

_ENTRY_MARKER = "## "


def append_memory(
    memory_log_path: str,
    project_id: str,
    review_year: str,
    final_decision_json: str,
    key_concerns: str = "",
) -> None:
    """이번 심의 요약 1건을 메모리 로그(md)에 append."""
    path = Path(memory_log_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        d = json.loads(final_decision_json)
        verdict = d.get("verdict", "불명")
        budget = d.get("approved_budget_billion")
        summary = d.get("executive_summary", "")
        conditions = d.get("conditions") or ""
    except Exception:
        verdict, budget, summary, conditions = "불명", None, final_decision_json[:500], ""

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"{_ENTRY_MARKER}{project_id} | {timestamp} | {review_year}년도 심의",
        f"- 결정: {verdict} / 승인 예산: {budget if budget is not None else '해당 없음'}억원",
        f"- 요약: {summary}",
    ]
    if conditions:
        lines.append(f"- 이행 조건: {conditions}")
    if key_concerns:
        lines.append(f"- 핵심 우려사항: {key_concerns}")
    lines.append("")

    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def load_past_context(
    memory_log_path: str,
    project_id: str,
    max_entries: int = 5,
    max_chars: int = 12000,
) -> str:
    """동일 project_id의 이전 심의 요약들을 반환. 없으면 빈 문자열."""
    path = Path(memory_log_path)
    if not path.exists():
        return ""

    text = path.read_text(encoding="utf-8")
    entries = []
    # 줄 시작의 "## "만 항목 구분자로 취급 (본문 내 "## " 포함 문자열 오파싱 방지)
    for block in re.split(r"(?m)^## ", text):
        if block.strip().startswith(f"{project_id} |"):
            entries.append(_ENTRY_MARKER + block.strip())

    if not entries or max_entries <= 0 or max_chars <= 0:
        return ""
    selected = entries[-max_entries:]
    result = "\n\n".join(selected)
    if len(result) > max_chars:
        result = "[이전 이력 앞부분 생략]\n" + result[-max_chars:]
    return result
