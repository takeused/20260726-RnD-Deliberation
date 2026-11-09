"""사업 유형 판별 (규칙 기반, LLM 없음): 산업형 · 공공임무형 · 혼합형.

심의기준은 사업 성격에 따라 평가해야 한다. 재난안전 R&D에 민간투자·수출·산업파급을 일률적으로 요구하면
공익 사업이 '시장이 작다'는 이유로 감점된다. 이전에는 노드마다 LLM이 성격을 따로 판별하라는 지시만 있어
분석가와 재정 검토관이 서로 다른 잣대를 쓸 수 있었다. 여기서 한 번 판별해 근거와 함께 기록하고,
모든 노드의 심의기준·정량 평가 가중치·사전 점검 항목·예상 질의 보장이 이 결과를 따른다.

키워드가 나온 줄 수를 세는 단순 규칙이므로 판별이 틀리면 --project-type으로 지정한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping

INDUSTRY, PUBLIC, MIXED = "산업형", "공공임무형", "혼합형"
PROJECT_TYPES = (INDUSTRY, PUBLIC, MIXED)

PUBLIC_RE = re.compile(
    r"재난|재해|방재|안전\s*(?:관리|사고|격차|취약)|국민\s*안전|인명\s*피해|피해\s*(?:저감|규모|액)|사망|이재민|"
    r"소방|구조\s*활동|대피|위기\s*관리|취약\s*계층|사회\s*(?:문제|회복력)|공공\s*(?:서비스|임무|안전)"
)
INDUSTRY_RE = re.compile(
    r"시장\s*(?:규모|점유|창출|진출|선점)|매출|수출|상용화|기술\s*(?:이전|사업화)|사업화|민간\s*투자|"
    r"산업\s*(?:경쟁력|생태계|파급)|글로벌\s*(?:시장|경쟁)|부가가치|공급망|기술\s*주권"
)
PHASES = {"예방": r"예방", "대비": r"대비(?!하)", "대응": r"대응", "복구": r"복구"}
_DOMINANCE = 2.0  # 한쪽이 다른 쪽의 2배 이상이면 그 유형, 아니면 혼합형


@dataclass
class ProjectTypeResult:
    project_type: str
    decided_by: str                      # 자동 판별 / 사용자 지정 / 원문 없음
    public_lines: int = 0
    industry_lines: int = 0
    evidence: list[str] = field(default_factory=list)   # [출처: 파일 Lx-Lx] 줄 앞부분
    phases: dict[str, int] = field(default_factory=dict)


def _cite(name: str, line_no: int, text: str) -> str:
    return f"[출처: {name} L{line_no}-L{line_no}] {text.strip()[:50]}"


def classify(source_lines: Mapping[str, list[str]], override: str | None = None) -> ProjectTypeResult:
    """입력 원문 줄로 사업 유형을 판별한다. override가 유형 이름이면 그대로 쓰고 근거만 센다."""
    public, industry, phases = [], [], {name: 0 for name in PHASES}
    for name, lines in source_lines.items():
        for i, line in enumerate(lines, 1):
            if PUBLIC_RE.search(line):
                public.append(_cite(name, i, line))
            if INDUSTRY_RE.search(line):
                industry.append(_cite(name, i, line))
            for phase, pattern in PHASES.items():
                phases[phase] += bool(re.search(pattern, line))
    if override in PROJECT_TYPES:
        project_type, decided_by = override, "사용자 지정"
    elif not source_lines:
        project_type, decided_by = MIXED, "판별할 원문 없음"
    elif len(public) >= _DOMINANCE * max(len(industry), 1):
        project_type, decided_by = PUBLIC, "자동 판별"
    elif len(industry) >= _DOMINANCE * max(len(public), 1):
        project_type, decided_by = INDUSTRY, "자동 판별"
    else:
        project_type, decided_by = MIXED, "자동 판별"
    evidence = (public[:2] + industry[:1]) if project_type != INDUSTRY else (industry[:2] + public[:1])
    return ProjectTypeResult(project_type, decided_by, len(public), len(industry), evidence, phases)


def render_section(result: ProjectTypeResult) -> str:
    """사전 점검 문서(00b)에 붙일 판별 결과."""
    phases = ", ".join(f"{k} {v}줄" for k, v in result.phases.items())
    return "\n".join([
        "## 사업 유형 판별 (규칙 기반)", "",
        f"- 판별: **{result.project_type}** ({result.decided_by})",
        f"- 근거: 공공임무 키워드가 나온 줄 {result.public_lines}개, 산업·시장 키워드가 나온 줄 {result.industry_lines}개 "
        f"(한쪽이 {_DOMINANCE:g}배 이상이면 그 유형, 아니면 혼합형)",
        f"- 재난관리 단계가 언급된 줄: {phases}",
        *[f"- 예: {e}" for e in result.evidence],
        "- 판별이 틀리면 `--project-type 산업형|공공임무형|혼합형`으로 지정하세요.",
    ])


def brief(result: ProjectTypeResult) -> str:
    """에이전트 지시문에 넣을 한 줄."""
    return (f"사업 유형: {result.project_type} ({result.decided_by}; 공공임무 근거 {result.public_lines}줄, "
            f"산업·시장 근거 {result.industry_lines}줄). 이 유형의 심의기준으로 평가하세요.")
