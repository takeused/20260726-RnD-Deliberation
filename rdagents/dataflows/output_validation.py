"""생성 산출물의 출처·미확인 주장 표기를 감사한다."""

from __future__ import annotations

import re
from collections.abc import Mapping

from rdagents.dataflows.project_loader import get_source_line_counts, get_source_lines


# 범위는 여러 개일 수 있고("… L319-L319, L314-L314"), 줄인 파일명 뒤에 공백 없이 붙기도 한다("…L3-L7")
_CITATION_RE = re.compile(
    # 파일명에 닫는 괄호가 들어가지 않게: 줄번호 없는 '【출처: 전문위원회 의견】' 뒤의 다른 인용까지 삼켰음 (07b JSON)
    r"[\[【]출처:\s*(?P<source>[^\]】]+?)\s*"
    r"(?P<ranges>L\d+\s*[-–—]\s*L?\d+(?:\s*,\s*L\d+\s*[-–—]\s*L?\d+)*)\s*,?\s*[\]】]"
)
_RANGE_RE = re.compile(r"L(\d+)\s*[-–—]\s*L?(\d+)")
_BROKEN_CITATION_RE = re.compile(r"[\[【]출처:[^\]】\n]*(?:L\s*[-…]|…)[^\]】]*[\]】]")
_RISKY_UNVERIFIED_RE = re.compile(
    r"(?:\d[\d,.]*\s*(?:억원|억\s*원|%|명|개|USD|M)|MOU|FEMA|KOTRA|ISO[- ]?\d+)", re.I,
)
_BUDGET_LABEL_RE = re.compile(
    r"(?:최종 승인 예산|원래 요청 예산|조정 후 제안 예산)\*{0,2}\s*:\s*(?P<amount>[0-9][0-9,]*(?:\.\d+)?)\s*억원"
)
# 내용 대조용: 단위가 붙은 수치 (연도·번호처럼 단위 없는 숫자는 오탐이 많아 제외)
# (?<![제\d,.]): 법조문 "제2조제3호"의 '2조'를 금액(조 원)으로 읽지 않게 (NDMI 실행에서 오탐)
# '2개월'은 개수가 아니라 기간이다 (groq5 실행에서 '최대 2개월', '3개월 차'가 원문에 없는 수치 '2개'로 표시됐음)
_UNIT_NUMBER_RE = re.compile(r"(?<![제\d,.])(\d[\d,]*(?:\.\d+)?)\s*(억\s*원|억|조|만\s*원|%|명|건|개(?!월))")
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
    target = target.replace("...", "…")
    # 가운데를 줄인 이름("(NDMI-기본-2025-20)…md")은 앞부분과 끝부분을 따로 맞춘다
    head, _, tail = _ELLIPSIS_RE.sub("", target).partition("…")
    # 앞 괄호를 빼먹기도 한다("NDMI-기본-2025-20… L5-L8")
    head = head.lstrip("(")
    # '…' 없이 앞부분만 쓴 경우("(NDMI-기본-2025-20) L1-L46")도 있다. 너무 짧은 앞부분은 우연히 맞을 수 있어 8자 이상만
    if len(head) < (4 if "…" in target else 8):
        return None, False
    matches = [name for norm, name in by_norm.items()
               if norm.lstrip("(").startswith(head) and norm.endswith(tail)]
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


# 원문에 없는 수치를 본문에 표시할 때 건너뛰는 파일: 코드가 만든 파일과 구조화 데이터
_NOT_LLM_TEXT = _CODE_GENERATED | {"12_실행관측성.md", "07b_예상질의.json"}
UNSUPPORTED_NOTE = "⚠️[원문에 없는 수치: {}]"
_NUMBER_UNIT_RE = re.compile(r"^(\d+(?:\.\d+)?)(.*)$")
_MARK_RE = re.compile(r"\s*⚠️\[원문에 없는 수치: [^\]]*\]")


def _split_number(token: str) -> tuple[float, int, str]:
    """'251.6%' -> (251.6, 소수 1자리, '%')."""
    m = _NUMBER_UNIT_RE.match(token)
    digits = m.group(1)
    return float(digits), len(digits.split(".")[1]) if "." in digits else 0, m.group(2)


# 원문은 '14,160백만원'인데 산출물은 '141.6억 원'으로 바꿔 쓴다 (기관고유 샘플 보고서에서 검증 총사업비가 26줄 표시됐음)
_SMALL_MONEY_RE = re.compile(r"(?<![\d,.])(\d[\d,]*(?:\.\d+)?)\s*(천\s*만\s*원|백\s*만\s*원|만\s*원|천\s*원)")


def _money_tokens(won: float) -> set[str]:
    """원 단위 금액을 산출물이 쓰는 억·조 단위 수치로. 1억 미만을 0.07억으로, 9,600억을 0.96조로 바꿔 두면
    반올림 허용 범위 때문에 지어낸 '0.1억'·'1조'까지 통과하므로(NDMI groq5) 그 단위로 1 이상인 값만 만든다."""
    return {f"{won / scale:.6f}".rstrip("0").rstrip(".") + unit
            for scale, unit in ((1e8, "억"), (1e12, "조")) if won >= scale}


def _converted_money(text: str) -> set[str]:
    """본문의 천원·만원·백만원 금액과 억·조 금액을 서로 바꾼 값 (2.11조 <-> 21,100억)."""
    from rdagents.dataflows.budget_check import UNIT_WON

    out: set[str] = set()
    for m in _SMALL_MONEY_RE.finditer(text):
        out |= _money_tokens(float(m.group(1).replace(",", "")) * UNIT_WON[re.sub(r"\s", "", m.group(2))])
    for token in _numbers(text):
        value, _, unit = _split_number(token)
        if unit in ("억", "조"):
            out |= _money_tokens(value * UNIT_WON[unit])
    return out


def _table_numbers(lines: list[str]) -> set[str]:
    """단위가 칸이 아니라 열 제목('피해액 비율', '금액(억 원)')이나 표 위 '(단위: 백만원, %)'에만 있는 표 숫자.

    NDMI 표 1.1의 비율 칸은 '0.3'처럼 숫자만 있어, 예상 질의가 원문 값 '0.3%'를 그대로 옮겨도 원문에 없는 수치로 표시됐다.
    """
    from rdagents.dataflows import budget_check

    out: set[str] = set()
    for table in budget_check.find_tables(lines):
        for c in range(1, len(table.header)):
            unit = "%" if budget_check.RATIO_HEADER.search(table.header[c]) else (table.col_unit(c) or "")
            if not unit:
                continue
            for _, cells in table.rows:
                cell = re.sub(r"\*\*|<br>|%", "", cells[c]).strip()
                if not re.fullmatch(r"\d[\d,]*(?:\.\d+)?", cell):
                    continue
                if unit in budget_check.UNIT_WON:  # 금액 열은 억·조로 바꿔 둔다 ('총사업비(백만원)' 열의 4,500)
                    out |= _money_tokens(float(cell.replace(",", "")) * budget_check.UNIT_WON[unit])
                out |= _numbers(cell + unit)
    return out


def source_number_index(source_texts: Mapping[str, list[str]], extra_text: str = "") -> dict[str, list[float]]:
    """입력 원문(사업보고서·외부근거)에 나오는 단위 붙은 수치를 단위별로 모은다.

    extra_text: 코드가 원문에서 계산한 값(사전 점검의 숫자 검산 결과). 산출물이 '계산 값 3.2%'를 옮겨 적으면 원문엔
    없지만 지어낸 수치도 아니다 (groq5 실행: 숫자 불일치 질의마다 표시가 붙었음).
    """
    index: dict[str, list[float]] = {}
    tokens = _numbers(extra_text) | _converted_money(extra_text)
    for lines in source_texts.values():
        text = "\n".join(lines)
        tokens |= _numbers(text) | _converted_money(text) | _table_numbers(lines)
    for token in tokens:
        value, _, unit = _split_number(token)
        index.setdefault(unit, []).append(value)
    return index


def unsupported_numbers(line: str, index: Mapping[str, list[float]]) -> list[str]:
    """줄의 단위 붙은 수치 중 입력 원문 어디에도 없는 것. 원문 값을 반올림한 수치(251.6% -> 251%)와 0은 통과."""
    if UNSUPPORTED_NOTE.split("{")[0] in line:
        return []  # 이미 표시한 줄 (다시 실행해도 두 번 붙이지 않음)
    claim = _claim_text(_CITATION_RE.sub("", normalize_citation_text(line)))
    out = []
    for token in sorted(_numbers(claim)):
        value, decimals, unit = _split_number(token)
        if value == 0:
            continue
        tolerance = 0.5 * 10 ** -decimals + 1e-9
        if not any(abs(value - v) <= tolerance for v in index.get(unit, [])):
            out.append(token)
    return out


def mark_unsupported_numbers(documents: Mapping[str, str]) -> tuple[dict[str, str], list[tuple[str, int, list[str]]]]:
    """LLM이 쓴 산출물에서 입력 원문에 없는 수치가 든 줄 끝에 표시를 붙인다. (표시한 문서들, [(파일, 줄, 수치)]).

    NDMI 실행에서 "대응시간 30% 감소", "추가 재산 피해 1,200억 원" 같은 원문에 없는 수치가 출처까지 달린 채
    분석 보고서와 공방에 들어갔다. 검증보고서에만 나열하면 산출물을 읽는 사람은 사실로 받아들이므로 본문에 표시한다.
    """
    precheck = documents.get("00b_사전점검.md", "")
    computed = precheck.split("## 숫자 검산", 1)[1] if "## 숫자 검산" in precheck else ""
    index = source_number_index(get_source_lines(), computed)
    marked, found = dict(documents), []
    if not index:
        return marked, found  # 원문 모드가 아니면(샘플 JSON) 대조할 원문이 없음
    for filename, content in documents.items():
        if filename in _NOT_LLM_TEXT:
            continue
        # 지난 표시는 지우고 지금 규칙으로 다시 붙인다 (규칙을 고친 뒤 --rerender하면 오탐 표시가 사라지게)
        lines = [_MARK_RE.sub("", line) for line in content.splitlines()]
        for i, line in enumerate(lines):
            missing = unsupported_numbers(line, index)
            if not missing:
                continue
            found.append((filename, i + 1, missing))
            note = UNSUPPORTED_NOTE.format(", ".join(missing))
            stripped = line.rstrip()
            # 표 줄은 마지막 칸 안에 넣어야 표가 깨지지 않는다
            lines[i] = f"{stripped[:-1].rstrip()} {note} |" if stripped.endswith("|") else f"{stripped} {note}"
        marked[filename] = "\n".join(lines) + ("\n" if content.endswith("\n") else "")
    return marked, found


UNSUPPORTED_SUMMARY_TITLE = "## 검증 안 된 수치 요약 (수치별)"


def _excerpt(line: str, token: str, width: int = 70) -> str:
    """수치가 나온 줄을 표 칸에 넣을 수 있게 다듬고 수치 주변만 잘라낸다."""
    text = _CITATION_RE.sub("", normalize_citation_text(_MARK_RE.sub("", line)))
    text = re.sub(r"\s+", " ", re.sub(r"[|*#>`]|<br>", " ", text)).strip()
    start = next((m.start() for m in _UNIT_NUMBER_RE.finditer(text) if _numbers(m.group(0)) == {token}), 0)
    left = max(0, min(start - width // 3, len(text) - width))
    return ("…" if left else "") + text[left:left + width] + ("…" if left + width < len(text) else "")


def unsupported_number_summary(documents: Mapping[str, str],
                               number_marks: list[tuple[str, int, list[str]]]) -> list[str]:
    """원문에 없는 수치를 수치별로 묶은 표. 같은 수치가 여러 문서에 퍼지므로 줄 목록보다 확인할 것이 적다.

    groq5 실행에서 표시 26줄이 분석·공방·질의에 흩어져 있어, 심의자가 '1,200억 원'이 어디서 처음 나와
    몇 군데로 번졌는지 알려면 문서를 다 열어야 했다.
    """
    groups: dict[str, list[tuple[str, int]]] = {}
    for filename, line_no, numbers in number_marks:
        for token in numbers:
            groups.setdefault(token, []).append((filename, line_no))
    if not groups:
        return ["- 없음"]
    rows = ["| 수치 | 나온 줄 수 | 문서 | 처음 나온 문장 |", "|---|---:|---|---|"]
    order = sorted(groups, key=lambda t: -len(groups[t]))  # 많이 번진 수치부터 (같으면 처음 나온 순서)
    for token in order:
        places = groups[token]
        filename, line_no = places[0]
        lines = documents.get(filename, "").splitlines()
        example = _excerpt(lines[line_no - 1], token) if line_no <= len(lines) else ""
        files = ", ".join(dict.fromkeys(f"`{f}`" for f, _ in places))
        value, decimals, unit = _split_number(token)
        shown = f"{value:,.{decimals}f}{unit}"  # 비교용으로 뺀 쉼표를 되살린다 (1200억 -> 1,200억)
        rows.append(f"| {shown} | {len(places)} | {files} | {example} (`{filename}` L{line_no}) |")
    return rows


def build_validation_report(documents: Mapping[str, str],
                            number_marks: list[tuple[str, int, list[str]]] | None = None) -> str:
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
            # 본문에 붙인 '원문에 없는 수치' 표시는 검사에서 뺀다 (표시 속 숫자가 미확인 문장 검사에 다시 걸렸음)
            line = normalize_citation_text(_MARK_RE.sub("", raw_line))
            resolved_spans, cited_parts = [], []
            for match in _CITATION_RE.finditer(line):
                written = match.group("source").strip()
                source, short = resolve_source(written, source_lines)
                if source is None:
                    if "…" not in written and "..." not in written:  # 줄인 이름은 아래 '잘린 출처'로 한 번만 보고
                        citation_issues.append(f"- `{filename}` L{line_no}: 인용 원문을 찾을 수 없음 — `{written}`")
                    continue
                resolved_spans.append(match.span())
                maximum = source_lines[source]
                for start_text, end_text in _RANGE_RE.findall(match.group("ranges")):
                    start, end = int(start_text), int(end_text)
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
        f"- **출처 내용 대조 확인 권고 수**: {len(content_flags)}",
        f"- **원문에 없는 수치를 본문에 표시한 줄 수**: {len(number_marks or [])}", "",
        UNSUPPORTED_SUMMARY_TITLE, "",
        "원문 어디에도 없는 단위 붙은 수치입니다. 지어낸 값일 수 있으니 심의 제출 전 근거를 찾거나 삭제하세요.", "",
        *unsupported_number_summary(documents, number_marks or []), "", "## 출처 검증 이슈", "",
        *(citation_issues or ["- 없음"]), "", "## 미확인 사실형 문장 (심의 제출 전 삭제·근거 보강 필요)", "",
        *(unverified or ["- 없음"]), "",
        "## 출처 내용 대조 확인 권고 (범위는 맞지만 인용 줄과 내용이 다를 수 있음)", "",
        *(content_flags or ["- 없음"]), "",
        "## 원문에 없는 수치 (산출물 본문의 해당 줄 끝에 ⚠️ 표시)", "",
        *([f"- `{f}` L{n}: {', '.join(nums)}" for f, n, nums in number_marks or []] or ["- 없음"]), "",
        "## 판정 기준", "",
        "- 입력 원문에 존재하는 파일명과 줄 범위만 자동 검증합니다. 비슷한 하이픈 문자는 '-'로 맞추고, "
        "'…'로 줄인 파일명은 앞부분이 입력 파일 하나와만 맞을 때 그 파일로 봅니다.",
        "- 내용 대조는 문장의 수치(단위 포함)가 인용 줄에 있는지, 공유 단어가 있는지만 봅니다. "
        "한 줄에 출처가 여럿이면 인용 줄을 모두 합쳐 대조하고, 코드가 만든 파일(사전 점검 등)은 대조하지 않습니다. "
        "경험적 검사이므로 검증 상태에는 반영하지 않고 원문 대조 대상만 표시합니다.",
        "- 원문에 없는 수치: LLM이 쓴 산출물의 단위 붙은 수치(%, 억 원, 명 등)가 입력 원문 어디에도 없으면 본문에 표시합니다. "
        "원문 값을 반올림한 수치와 0은 통과시키고, 표의 숫자만 있는 칸(가중치·점수)은 보지 않습니다. "
        "질의의 예시 목표치(\"예: 10% 절감\")도 표시되므로, 원문 근거가 아니라는 뜻으로 읽으세요.",
        "- 의미적 진실성은 자동 확정하지 않으므로 심의 제출 전 원문 대조가 필요합니다.",
        "- `[확인 필요: ...]`는 미확인 사실을 정당화하지 않습니다. 구체 수치·기관·협약은 근거를 첨부하거나 삭제해야 합니다.",
    ])
