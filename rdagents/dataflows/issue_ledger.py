"""쟁점 원장 (코드 로직, LLM 없음): 쟁점 등록·출처 검증·공방 순서·방어 판정·판정 정합성.

이전 공방은 라운드마다 패널이 질의 3~5개를 자유 서술하고 발표자가 자유 서술로 답했다. 쟁점별로 방어에 성공했는지
기록이 없어서 위원장·최종 승인·예상 질의가 긴 토론 기록을 잘라 읽고 각자 해석했고, 발표자는 원문에 없는 피해액·
투자액·비목표까지 지어내 방어했다 (NDMI groq7). 학습 저장소 23번 예제의 방식을 옮겼다:
  - 분석 보고서의 지적은 쟁점으로 등록하고, LLM이 단 출처는 코드가 원문과 대조한다
  - 공방은 쟁점 하나씩 (예산·사전 점검 누락·3대 기준 '상' 쟁점은 반드시 상정)
  - 발표자 답변의 출처가 틀리거나 원문에 없는 수치로 방어하면 코드가 방어 실패로 본다
  - 판정은 LLM이 하되, 원장과 맞지 않는 승인은 거부한다
"""

from __future__ import annotations

import re

from rdagents.agents.utils.committee import panel_member

CORE_CRITERIA = ("정부지원 필요성", "기술개발의 중요성", "시급성")
_SEVERITY_RANK = {"상": 0, "중": 1, "하": 2}
_REPORT_NAMES = {  # 등록기가 적은 보고서 이름 -> 상태 키 (패널 위원 배정용: 규제·윤리면 법·제도위원)
    "분야 기술전문가": "domain_expert_report", "기술 가치": "tech_value_report", "트렌드": "tech_trend_report",
    "중복": "tech_trend_report", "경제": "economic_report", "재무": "economic_report", "정책": "policy_report",
    "수행": "feasibility_report", "규제": "regulatory_report", "윤리": "regulatory_report",
}
UNASKED, DEBATING, DEFENDED, FAILED = "공방 미상정", "공방 중", "방어 성공", "방어 실패"


def _compact(text: str) -> str:
    """대조용: 공백·하이픈 변형·문장부호를 지운다 (gpt-oss는 U+202F 공백·U+2011 하이픈을 씀)."""
    from rdagents.dataflows.output_validation import normalize_citation_text

    return re.sub(r"[\s    *`\"'“”‘’.,·:;()\[\]-]", "", normalize_citation_text(text or ""))


def verify_citation(cite: str, quote: str, require_quote: bool = False) -> tuple[bool, str]:
    """(검증됨, 사유). 출처의 파일·줄 범위가 원문에 있고, 인용 구절이 그 줄에 실제로 있는지 본다."""
    from rdagents.dataflows.output_validation import _CITATION_RE, _RANGE_RE, normalize_citation_text, resolve_source
    from rdagents.dataflows.project_loader import get_source_lines

    lines_by_source = get_source_lines()
    match = _CITATION_RE.search(normalize_citation_text(cite or ""))
    if not match:
        return False, "출처 형식 없음"
    source, _ = resolve_source(match.group("source").strip(), {k: len(v) for k, v in lines_by_source.items()})
    if source is None:
        return False, "출처 파일을 찾을 수 없음"
    lines = lines_by_source[source]
    spans = [(int(a), int(b)) for a, b in _RANGE_RE.findall(match.group("ranges"))]
    if not spans or any(not 1 <= a <= b <= len(lines) for a, b in spans):
        return False, f"없는 줄 범위 (원문 {len(lines)}줄)"
    if not quote:
        return (False, "인용 구절 없음") if require_quote else (True, "줄 범위만 확인")
    cited = _compact("".join("".join(lines[a - 1:b]) for a, b in spans))
    if _compact(quote) not in cited:
        return False, "인용 구절이 그 줄에 없음"
    return True, "원문 대조 일치"


_CITE_RE = re.compile(r"\[출처:[^\]\n]*\]")
_BULLET_RE = re.compile(r"^\s*(?:[-*•|]|\d+[.)])\s*")
_REF_RE = re.compile(r"\bR(\d+)\b")


def cited_claims(text: str, start: int = 1, width: int = 100) -> list[dict]:
    """분석 보고서에서 출처가 달린 지적(줄)을 뽑아 짧은 번호(R1, R2…)를 붙인다.

    출처 하나가 파일 이름 때문에 100자를 넘어서, 보고서를 글자 수로 줄이면 출처 달린 지적이 거의 남지 않았다
    (NDMI groq8: 등록 쟁점 7개 모두 출처 없음 -> 공방 미상정). 등록기에는 번호만 보여 주고 코드가 출처로 되돌린다.
    """
    claims = []
    for line in (text or "").splitlines():
        cites = _CITE_RE.findall(line)
        claim = _BULLET_RE.sub("", _CITE_RE.sub("", line)).strip(" *|")
        if cites and claim:
            claims.append({"ref": f"R{start + len(claims)}", "claim": claim[:width], "cite": cites[0]})
    return claims


def resolve_refs(registered: list[dict], claims: list[dict]) -> list[dict]:
    """등록기가 cite에 적은 번호(R3)를 원래 출처로 바꾼다. 출처를 직접 적었거나 없는 번호면 그대로 둔다."""
    by_ref = {c["ref"]: c["cite"] for c in claims}
    resolved = []
    for raw in registered:
        cite = raw.get("cite") or ""
        match = _REF_RE.search(cite)
        if match and "출처:" not in cite and f"R{match.group(1)}" in by_ref:
            raw = {**raw, "cite": by_ref[f"R{match.group(1)}"]}
        resolved.append(raw)
    return resolved


def cited_lines(cite: str, around: int = 1, max_lines: int = 8) -> str:
    """출처가 가리키는 원문 줄(앞뒤 around줄 포함)을 'L번호: 내용'으로. 공방 노드가 긴 보고서 대신 읽는 근거."""
    from rdagents.dataflows.output_validation import _CITATION_RE, _RANGE_RE, normalize_citation_text, resolve_source
    from rdagents.dataflows.project_loader import get_source_lines

    lines_by_source = get_source_lines()
    match = _CITATION_RE.search(normalize_citation_text(cite or ""))
    if not match:
        return ""
    source, _ = resolve_source(match.group("source").strip(), {k: len(v) for k, v in lines_by_source.items()})
    if source is None:
        return ""
    lines, out = lines_by_source[source], []
    for a, b in _RANGE_RE.findall(match.group("ranges")):
        start, end = max(1, int(a) - around), min(len(lines), int(b) + around)
        out += [f"{source} L{n}: {lines[n - 1].strip()}" for n in range(start, end + 1) if lines[n - 1].strip()]
    return "\n".join(dict.fromkeys(out[:max_lines]))


def build_ledger(registered: list[dict], code_issues: list[dict], project_type: str | None) -> list[dict]:
    """코드가 찾은 쟁점(사전 점검·숫자 검산)을 앞에, LLM이 등록한 쟁점을 뒤에 둔 원장. 출처는 여기서 검증한다."""
    ledger = []
    for raw in code_issues:
        ledger.append({**raw, "source_report": ""})
    for raw in registered:
        ok, note = verify_citation(raw.get("cite", ""), raw.get("quote", ""))
        source_key = next((key for name, key in _REPORT_NAMES.items() if name in raw.get("source_report", "")), "")
        ledger.append({**raw, "origin": raw.get("source_report") or "분석 보고서", "source_report": source_key,
                       "verified": ok, "verify_note": note})
    for i, item in enumerate(ledger, 1):
        item.update(id=i, status=UNASKED, member=panel_member(project_type, item["criterion"], item["source_report"]),
                    question="", defense="", defense_cite="", defense_note="")
    return ledger


def is_must(item: dict) -> bool:
    """반드시 공방에 올릴 쟁점: 예산, 사전 점검 누락, 3대 기준의 '상' 쟁점 (출처가 검증된 것만).

    숫자 검산 불일치는 빼고 심각도 순서로만 다룬다: NDMI는 같은 표 1.1의 변형 3건이 모두 필수가 되어 상한을 넘겼다
    (예상 질의 추출기가 숫자 검산 질의를 따로 반드시 넣는다).
    """
    return item["verified"] and (
        (item["criterion"] == "예산 타당성" and item.get("origin") != "숫자 검산")
        or item.get("origin") == "사전 점검 (누락)"
        or (item["severity"] == "상" and item["criterion"] in CORE_CRITERIA)
    )


def debate_limit(ledger: list[dict], max_issues: int) -> int:
    """상정할 쟁점 수 상한: 기본 max_issues, 반드시 올릴 쟁점이 더 많으면 2개까지 늘림."""
    return max(max_issues, min(sum(map(is_must, ledger)), max_issues + 2))


def next_issue(ledger: list[dict], max_issues: int) -> dict | None:
    """다음에 상정할 쟁점 (반드시 올릴 쟁점 -> 출처 검증된 쟁점 -> 심각도 순). 상한에 닿았으면 None."""
    asked = sum(item["status"] != UNASKED for item in ledger)
    remaining = [item for item in ledger if item["status"] == UNASKED]
    if asked >= debate_limit(ledger, max_issues) or not remaining:
        return None
    return min(remaining, key=lambda i: (not is_must(i), not i["verified"], _SEVERITY_RANK.get(i["severity"], 3), i["id"]))


def failed_core_high(ledger: list[dict]) -> list[dict]:
    """방어에 실패한 3대 기준의 '상' 쟁점 (남아 있으면 '승인'은 원장과 맞지 않음)."""
    return [i for i in ledger if i["status"] == FAILED and i["severity"] == "상" and i["criterion"] in CORE_CRITERIA]


def ledger_counts(ledger: list[dict]) -> dict[str, int]:
    return {s: sum(i["status"] == s for i in ledger) for s in (DEFENDED, FAILED, UNASKED)}


def render_ledger(ledger: list[dict]) -> str:
    """산출물 02b_쟁점원장.md: 쟁점별 출처 검증·질의 위원·방어 결과."""
    counts = ledger_counts(ledger)
    # 개수에 '개'·'건'을 붙이지 않는다: 코드가 쓴 숫자에 '원문에 없는 수치' 표시가 붙었음
    out = ["# 쟁점 원장", "",
           f"- 쟁점 수 {len(ledger)}: 방어 성공 {counts[DEFENDED]} · 방어 실패 {counts[FAILED]} · "
           f"공방 미상정 {counts[UNASKED]}",
           f"- 방어 실패한 3대 기준 '상' 쟁점 수: {len(failed_core_high(ledger))} (남아 있으면 '승인' 불가)", "",
           "| # | 심의기준 | 심각도 | 출처 | 쟁점 | 질의 위원 | 결과 | 방어 판정 근거 |", "|---|---|---|---|---|---|---|---|"]
    for i in ledger:
        cite = f"{i['cite']} ({i['verify_note']})" if i["cite"] else i["verify_note"]
        note = i["defense_note"] or "-"
        out.append(f"| {i['id']} | {i['criterion']} | {i['severity']} | {i['origin']}: {cite} | {i['issue']} | "
                   f"{i['member'] if i['status'] != UNASKED else '-'} | {i['status']} | {note} |")
    out += ["", "- 출처: 코드가 원문과 대조 (사전 점검·숫자 검산은 코드가 찾은 문제). 출처가 틀린 쟁점은 반드시 상정하지 않음.",
            "- 방어 판정: 발표자 답변의 출처·인용 구절이 원문과 맞고 원문에 없는 수치가 없을 때만 '방어 성공'."]
    return "\n".join(out)


def ledger_summary(ledger: list[dict], width: int = 50) -> str:
    """위원장·최종 승인·예상 질의 지시문용 짧은 원장 (긴 토론 기록 대신)."""
    counts = ledger_counts(ledger)
    rows = [f"쟁점 원장: 방어 성공 {counts[DEFENDED]} · 방어 실패 {counts[FAILED]} · 공방 미상정 {counts[UNASKED]}"]
    order = sorted(ledger, key=lambda i: ({FAILED: 0, UNASKED: 1, DEFENDED: 2}.get(i["status"], 3),
                                          _SEVERITY_RANK.get(i["severity"], 3)))
    for i in order:
        rows.append(f"- #{i['id']} [{i['status']}] {i['criterion']}·{i['severity']}: {i['issue'][:width]}")
    return "\n".join(rows)


def check_decision_against_ledger(verdict: str, ledger: list[dict]) -> None:
    """판정 정합성: 3대 기준의 '상' 쟁점이 방어 실패로 남아 있는데 '승인'이면 거부한다 (조건부승인 이하만 허용).

    결정은 LLM이 하지만 원장과 맞지 않는 결론은 막는다. 오류 메시지가 재시도 피드백으로 전달되므로
    어떤 쟁점 때문인지 적는다.
    """
    failed = failed_core_high(ledger)
    if verdict == "승인" and failed:
        ids = ", ".join(f"#{i['id']} {i['criterion']}" for i in failed)
        raise ValueError(f"쟁점 원장에 방어 실패한 3대 기준 '상' 쟁점({ids})이 남아 있어 '승인'할 수 없습니다. "
                         "조건부승인(해당 쟁점 보완을 이행 조건으로)·감액조정·보류 중에서 결정하세요.")
