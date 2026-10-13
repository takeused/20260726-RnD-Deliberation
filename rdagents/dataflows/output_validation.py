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
# (?<![제\d,.]): 법조문 "제2조제3호"의 '2조'를 금액(조 원)으로 읽지 않게 (NDMI 실행에서 오탐)
_UNIT_NUMBER_RE = re.compile(r"(?<![제\d,.])(\d[\d,]*(?:\.\d+)?)\s*(억\s*원|억|조|만\s*원|%|명|건|개)")
_WORD_RE = re.compile(r"[가-힣A-Za-z0-9]{2,}")
# 산출물 문장마다 나오는 말은 겹침 판단에서 뺀다 (안 빼면 거의 모든 문장이 '겹침 있음'이 됨)
_COMMON_BIGRAMS = {"출처", "사업", "보고", "고서", "있다", "한다", "하여", "에서", "으로", "니다", "습니", "확인", "필요"}
# gpt-oss는 하이픈 대신 비슷한 문자(U+2010~2015, U+2212, 전각 '－')를 쓴다 ("L3‑L4"). 비교 전에 '-'로 맞춘다
_DASHES = str.maketrans({c: "-" for c in "‐‑‒–—―−－"})
_ELLIPSIS_RE = re.compile(r"\s*(?:…|\.{3})\s*$")
# 코드가 만든 산출물은 LLM 인용이 아니므로 내용 대조에서 뺀다 (사전 점검 표의 대표 근거 칸이 오탐을 냈음)
_CODE_GENERATED = {"00_입력문서_출처.md", "00b_사전점검.md", "14_검증보고서.md"}


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


def normalize_citation_text(text: str) -> str:
    return text.translate(_DASHES)


def resolve_source(source: str, known: Mapping[str, int]) -> tuple[str | None, bool]:
    """인용에 적힌 파일명을 실제 입력 파일명으로. (파일명, 줄여 쓴 이름이었는지).

    LLM은 긴 파일명을 "(NDMI-기본-2025-20)…"처럼 줄여 쓴다. 앞부분이 입력 파일 하나와만 맞으면 그 파일로 본다.
    여러 파일과 맞거나 아무것도 안 맞으면 None (잘린 출처로 남김).
    """
    target = normalize_citation_text(source).strip()
    by_norm = {normalize_citation_text(name): name for name in known}
    if target in by_norm:
        return by_norm[target], False
    prefix = _ELLIPSIS_RE.sub("", target)
    # '…' 없이 앞부분만 쓴 경우("(NDMI-기본-2025-20) L1-L46")도 있다. 너무 짧은 앞부분은 우연히 맞을 수 있어 8자 이상만
    if len(prefix) < (4 if prefix != target else 8):
        return None, False
    matches = [name for norm, name in by_norm.items() if norm.startswith(prefix)]
    return (matches[0], True) if len(matches) == 1 else (None, False)


_NUMBER_CELL_RE = re.compile(r"^\s*\**[\d.,]+\s*(?:%|점|억\s*원|억)?\**\s*$")


def _claim_text(line: str) -> str:
    """대조할 주장 문장. 표 줄이면 숫자만 있는 칸(가중치·점수 열)은 뺀다 (정량평가표의 '15%' 가중치가 오탐)."""
    if not line.lstrip().startswith("|"):
        return line
    return "|".join(cell for cell in line.split("|") if not _NUMBER_CELL_RE.match(cell))


def check_citation_content(claim_line: str, cited_text: str) -> list[str]:
    """출처가 달린 문장과 인용된 원문 줄을 대조해 의심 사유를 돌려준다 (자동 판정이 아니라 확인 권고).

    줄 범위가 유효해도 LLM이 엉뚱한 줄을 인용하는 경우가 있다 (학습 저장소의 모의 심의 Groq 실행에서
    인용문이 해당 줄에 없는 지적이 실제로 나옴). 이 검사는 그런 경우를 사람이 확인할 목록에 올린다.
    """
    claim = _CITATION_RE.sub("", normalize_citation_text(claim_line))
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
    valid, abbreviated, citation_issues, unverified, content_flags = 0, 0, [], [], []
    for filename, content in documents.items():
        for line_no, raw_line in enumerate(content.splitlines(), 1):
            line = normalize_citation_text(raw_line)
            resolved_spans, cited_parts = [], []
            for match in _CITATION_RE.finditer(line):
                written = match.group("source").strip()
                source, short = resolve_source(written, source_lines)
                start, end = int(match.group("start")), int(match.group("end"))
                if source is None:
                    if not _ELLIPSIS_RE.search(written):  # 줄인 이름은 아래 '잘린 출처'로 한 번만 보고
                        citation_issues.append(f"- `{filename}` L{line_no}: 인용 원문을 찾을 수 없음 — `{written}`")
                    continue
                resolved_spans.append(match.span())
                maximum = source_lines[source]
                if start < 1 or end < start or end > maximum:
                    citation_issues.append(f"- `{filename}` L{line_no}: L{start}-L{end}가 `{source}`(최대 L{maximum})를 벗어남")
                    continue
                valid += 1
                abbreviated += short
                if source in source_texts:
                    cited_parts.append((source, start, end, "\n".join(source_texts[source][start - 1:end])))
            # 한 줄에 출처가 여럿이면(표의 근거 칸 등) 문장의 수치가 어느 줄에 있는지 알 수 없으므로 모두 합쳐 대조
            if cited_parts and filename not in _CODE_GENERATED:
                cited = "\n".join(text for *_, text in cited_parts)
                where = ", ".join(f"L{s}-L{e}" for _, s, e, _ in cited_parts)
                for reason in check_citation_content(_claim_text(line), cited):
                    content_flags.append(
                        f"- `{filename}` L{line_no} → `{cited_parts[0][0]}` {where}: {reason} — {raw_line[:120]}"
                    )
            rest = line
            for a, b in reversed(resolved_spans):
                rest = rest[:a] + rest[b:]
            if _BROKEN_CITATION_RE.search(rest):
                citation_issues.append(f"- `{filename}` L{line_no}: 줄번호가 생략되거나 잘린 출처 표기")
            if "[확인 필요:" in line and _RISKY_UNVERIFIED_RE.search(line):
                unverified.append(f"- `{filename}` L{line_no}: 미확인 표식과 함께 구체 수치·기관·협약을 진술함 — {raw_line[:180]}")
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
        f"- **형식·범위가 유효한 출처 인용 수**: {valid} (그중 줄여 쓴 파일명을 입력 파일로 해석한 것 {abbreviated})",
        f"- **출처 검증 이슈 수**: {len(citation_issues)}",
        f"- **미확인 사실형 문장 수**: {len(unverified)}",
        f"- **출처 내용 대조 확인 권고 수**: {len(content_flags)}", "", "## 출처 검증 이슈", "",
        *(citation_issues or ["- 없음"]), "", "## 미확인 사실형 문장 (심의 제출 전 삭제·근거 보강 필요)", "",
        *(unverified or ["- 없음"]), "",
        "## 출처 내용 대조 확인 권고 (범위는 맞지만 인용 줄과 내용이 다를 수 있음)", "",
        *(content_flags or ["- 없음"]), "", "## 판정 기준", "",
        "- 입력 원문에 존재하는 파일명과 줄 범위만 자동 검증합니다. 비슷한 하이픈 문자는 '-'로 맞추고, "
        "'…'로 줄인 파일명은 앞부분이 입력 파일 하나와만 맞을 때 그 파일로 봅니다.",
        "- 내용 대조는 문장의 수치(단위 포함)가 인용 줄에 있는지, 공유 단어가 있는지만 봅니다. "
        "한 줄에 출처가 여럿이면 인용 줄을 모두 합쳐 대조하고, 코드가 만든 파일(사전 점검 등)은 대조하지 않습니다. "
        "경험적 검사이므로 검증 상태에는 반영하지 않고 원문 대조 대상만 표시합니다.",
        "- 의미적 진실성은 자동 확정하지 않으므로 심의 제출 전 원문 대조가 필요합니다.",
        "- `[확인 필요: ...]`는 미확인 사실을 정당화하지 않습니다. 구체 수치·기관·협약은 근거를 첨부하거나 삭제해야 합니다.",
    ])
