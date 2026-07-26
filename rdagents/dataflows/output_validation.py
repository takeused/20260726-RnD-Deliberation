"""생성 산출물의 출처·미확인 주장 표기를 감사한다."""

from __future__ import annotations

import re
from collections.abc import Mapping

from rdagents.dataflows.project_loader import get_source_line_counts


_CITATION_RE = re.compile(
    r"[\[【]출처:\s*(?P<source>.+?)\s+L(?P<start>\d+)\s*[-–—]\s*L?(?P<end>\d+)[\]】]"
)
_BROKEN_CITATION_RE = re.compile(r"[\[【]출처:[^\]】\n]*(?:L\s*[-…]|…)[^\]】]*[\]】]")
_RISKY_UNVERIFIED_RE = re.compile(
    r"(?:\d[\d,.]*\s*(?:억원|억\s*원|%|명|개|USD|M)|MOU|FEMA|KOTRA|ISO[- ]?\d+)", re.I,
)
_BUDGET_LABEL_RE = re.compile(
    r"(?:최종 승인 예산|원래 요청 예산|조정 후 제안 예산)\*{0,2}\s*:\s*(?P<amount>[0-9][0-9,]*(?:\.\d+)?)\s*억원"
)


def build_validation_report(documents: Mapping[str, str]) -> str:
    """출처 형식·줄 범위와 미확인 사실형 문장을 별도 감사 보고서로 만든다."""
    source_lines = get_source_line_counts()
    facts_budget = None
    try:
        from rdagents.dataflows.project_loader import get_project_facts
        facts_budget = get_project_facts().get("requested_budget_eok")
    except RuntimeError:
        pass
    valid, citation_issues, unverified = 0, [], []
    for filename, content in documents.items():
        for line_no, line in enumerate(content.splitlines(), 1):
            for match in _CITATION_RE.finditer(line):
                source = match.group("source").strip()
                start, end = int(match.group("start")), int(match.group("end"))
                maximum = source_lines.get(source)
                if maximum is None:
                    citation_issues.append(f"- `{filename}` L{line_no}: 인용 원문을 찾을 수 없음 — `{source}`")
                elif start < 1 or end < start or end > maximum:
                    citation_issues.append(f"- `{filename}` L{line_no}: L{start}-L{end}가 `{source}`(최대 L{maximum})를 벗어남")
                else:
                    valid += 1
            if _BROKEN_CITATION_RE.search(line):
                citation_issues.append(f"- `{filename}` L{line_no}: 줄번호가 생략되거나 잘린 출처 표기")
            if "[확인 필요:" in line and _RISKY_UNVERIFIED_RE.search(line):
                unverified.append(f"- `{filename}` L{line_no}: 미확인 표식과 함께 구체 수치·기관·협약을 진술함 — {line[:180]}")
            if facts_budget is not None:
                for budget_match in _BUDGET_LABEL_RE.finditer(line):
                    value = float(budget_match.group("amount").replace(",", ""))
                    if filename == "04_예산조정안.md" and "조정 후" in line:
                        continue
                    if abs(value - facts_budget) > 0.01 and "감액" not in line and "증액" not in line:
                        citation_issues.append(
                            f"- `{filename}` L{line_no}: 검증 총사업비 {facts_budget}억원과 다른 핵심 예산 표기 {value}억원"
                        )
    status = "통과" if not citation_issues and not unverified else "검토 필요"
    return "\n".join([
        "# 생성물 근거 검증 보고서", "", f"- **검증 상태**: {status}",
        f"- **형식·범위가 유효한 출처 인용 수**: {valid}",
        f"- **출처 검증 이슈 수**: {len(citation_issues)}",
        f"- **미확인 사실형 문장 수**: {len(unverified)}", "", "## 출처 검증 이슈", "",
        *(citation_issues or ["- 없음"]), "", "## 미확인 사실형 문장 (심의 제출 전 삭제·근거 보강 필요)", "",
        *(unverified or ["- 없음"]), "", "## 판정 기준", "",
        "- 입력 원문에 존재하는 파일명과 줄 범위만 자동 검증합니다.",
        "- 의미적 진실성은 자동 확정하지 않으므로 심의 제출 전 원문 대조가 필요합니다.",
        "- `[확인 필요: ...]`는 미확인 사실을 정당화하지 않습니다. 구체 수치·기관·협약은 근거를 첨부하거나 삭제해야 합니다.",
    ])
