"""생성 산출물의 출처·미확인 주장 표기를 감사한다."""

from __future__ import annotations

import re
from collections.abc import Mapping

from rdagents.dataflows.project_loader import get_source_line_counts, get_source_lines


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
# 내용 대조용: 단위가 붙은 수치 (연도·번호처럼 단위 없는 숫자는 오탐이 많아 제외)
_UNIT_NUMBER_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(억\s*원|억|조|만\s*원|%|명|건|개)")
_WORD_RE = re.compile(r"[가-힣A-Za-z0-9]{2,}")
# 산출물 문장마다 나오는 말은 겹침 판단에서 뺀다 (안 빼면 거의 모든 문장이 '겹침 있음'이 됨)
_COMMON_BIGRAMS = {"출처", "사업", "보고", "고서", "있다", "한다", "하여", "에서", "으로", "니다", "습니", "확인", "필요"}


def _bigrams(text: str) -> set[str]:
    out: set[str] = set()
    for word in _WORD_RE.findall(text):
        out.update(word[i:i + 2] for i in range(len(word) - 1))
    return out - _COMMON_BIGRAMS


def _numbers(text: str) -> set[str]:
    """단위가 붙은 수치를 정규화해 모은다. '226억 원'·'226억원'·'226억'은 같은 값."""
    out = set()
    for m in _UNIT_NUMBER_RE.finditer(text):
        unit = re.sub(r"\s+", "", m.group(2))
        out.add(m.group(1).replace(",", "") + ("억" if unit == "억원" else unit))
    return out


def check_citation_content(claim_line: str, cited_text: str) -> list[str]:
    """출처가 달린 문장과 인용된 원문 줄을 대조해 의심 사유를 돌려준다 (자동 판정이 아니라 확인 권고).

    줄 범위가 유효해도 LLM이 엉뚱한 줄을 인용하는 경우가 있다 (학습 저장소의 모의 심의 Groq 실행에서
    인용문이 해당 줄에 없는 지적이 실제로 나옴). 이 검사는 그런 경우를 사람이 확인할 목록에 올린다.
    """
    claim = _CITATION_RE.sub("", claim_line)
    reasons = []
    missing = sorted(_numbers(claim) - _numbers(cited_text))
    if missing:
        reasons.append(f"인용 줄에 없는 수치 {', '.join(missing)}")
    if _bigrams(claim) and not (_bigrams(claim) & _bigrams(cited_text)):
        reasons.append("문장과 인용 줄이 공유하는 단어가 없음")
    return reasons


def build_validation_report(documents: Mapping[str, str]) -> str:
    """출처 형식·줄 범위와 미확인 사실형 문장을 별도 감사 보고서로 만든다."""
    source_lines = get_source_line_counts()
    source_texts = get_source_lines()
    facts_budget = None
    try:
        from rdagents.dataflows.project_loader import get_project_facts
        facts_budget = get_project_facts().get("requested_budget_eok")
    except RuntimeError:
        pass
    valid, citation_issues, unverified, content_flags = 0, [], [], []
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
                    if source in source_texts:
                        cited = "\n".join(source_texts[source][start - 1:end])
                        for reason in check_citation_content(line, cited):
                            content_flags.append(
                                f"- `{filename}` L{line_no} → `{source}` L{start}-L{end}: {reason} — {line[:120]}"
                            )
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
    # 내용 대조는 경험적 검사라 상태(통과/검토 필요)를 바꾸지 않고 확인 권고 목록으로만 둔다
    status = "통과" if not citation_issues and not unverified else "검토 필요"
    return "\n".join([
        "# 생성물 근거 검증 보고서", "", f"- **검증 상태**: {status}",
        f"- **형식·범위가 유효한 출처 인용 수**: {valid}",
        f"- **출처 검증 이슈 수**: {len(citation_issues)}",
        f"- **미확인 사실형 문장 수**: {len(unverified)}",
        f"- **출처 내용 대조 확인 권고 수**: {len(content_flags)}", "", "## 출처 검증 이슈", "",
        *(citation_issues or ["- 없음"]), "", "## 미확인 사실형 문장 (심의 제출 전 삭제·근거 보강 필요)", "",
        *(unverified or ["- 없음"]), "",
        "## 출처 내용 대조 확인 권고 (범위는 맞지만 인용 줄과 내용이 다를 수 있음)", "",
        *(content_flags or ["- 없음"]), "", "## 판정 기준", "",
        "- 입력 원문에 존재하는 파일명과 줄 범위만 자동 검증합니다.",
        "- 내용 대조는 문장의 수치(단위 포함)가 인용 줄에 있는지, 공유 단어가 있는지만 봅니다. "
        "경험적 검사이므로 검증 상태에는 반영하지 않고 원문 대조 대상만 표시합니다.",
        "- 의미적 진실성은 자동 확정하지 않으므로 심의 제출 전 원문 대조가 필요합니다.",
        "- `[확인 필요: ...]`는 미확인 사실을 정당화하지 않습니다. 구체 수치·기관·협약은 근거를 첨부하거나 삭제해야 합니다.",
    ])
