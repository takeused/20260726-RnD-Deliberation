"""기획보고서 사전 점검 (규칙 기반, LLM 없음).

심의 전에 보고서에 꼭 있어야 할 항목이 있는지 키워드와 단위 붙은 수치로 점검한다.
누락·근거 약함 항목은 심사위원 패널과 예상 질의 추출기에 '우선 확인 지점'으로 넘긴다.
뻔히 빠진 항목을 LLM이 다시 찾느라 토큰을 쓰지 않게 하고, 예상 질의가 그 지점을 놓치지 않게 한다.

출처: 학습 저장소 langgraph-learning-examples의 plan_precheck.py(25번 예제)를 옮겨 출처 표기만 이 저장소
형식([출처: 파일명 L시작-L끝])으로 바꿨다. 규칙은 '있는지'만 보며 내용 타당성은 판단하지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

UNIT_NUMBER = re.compile(
    r"\d[\d,.]*\s*(?:억\s*원|억|조|만\s*원|백만\s*원|천\s*원|%|명|건|개소|개|회|배|㎢|km|ha|톤|시간|일)"
)
PAGE_MARK = re.compile(r"<!--\s*p\.(\d+)\s*-->")
# 키워드는 있지만 '정해지지 않았다'는 뜻의 표현 (예: "운영 주체는 사업 착수 후 협의")
UNDECIDED = re.compile(r"추후|착수\s*후\s*(?:협의|결정)|협의\s*(?:예정|중)|검토\s*예정|미정|정해지지\s*않|향후\s*결정")


@dataclass(frozen=True)
class CheckItem:
    key: str
    name: str
    criterion: str
    patterns: tuple[str, ...]
    needs_number: bool = False
    question: str = ""


CHECKLIST: tuple[CheckItem, ...] = (
    CheckItem("background", "추진 배경·문제 정의", "기타",
              # '추진 목적과 핵심 문제'(지역재난 2단계 요약 보고서의 절 제목)도 배경·문제 정의다
              (r"추진\s*(?:배경|목적)", r"연구\s*배경", r"문제\s*(?:점|정의)", r"핵심\s*문제", r"현황"),
              question="이 사업이 해결하려는 문제가 무엇이고 현재 어떤 상황입니까?"),
    CheckItem("gov_support", "정부지원 필요성", "정부지원 필요성",
              (r"정부\s*(?:지원|주도|투자|역할)", r"시장\s*실패", r"민간.{0,10}(?:투자|유인|참여)", r"공공\s*(?:성|영역|재)"),
              question="민간이 아니라 정부가 투자해야 하는 이유는 무엇입니까?"),
    CheckItem("urgency", "시급성의 정량 근거", "시급성",
              (r"시급", r"증가\s*(?:추세|하는|하고)", r"최근\s*\d*\s*년", r"피해\s*(?:액|규모|가|를|현황)",
               r"사망|인명\s*피해|이재민"),
              needs_number=True, question="왜 지금 해야 합니까? 피해 규모와 추세를 수치로 제시해 주십시오."),
    CheckItem("novelty", "기술 차별성·중복 검토", "기술개발의 중요성",
              (r"차별(?:성|화)", r"중복", r"유사\s*(?:사업|과제|연구)", r"선행\s*연구", r"NTIS",
               r"기존\s*(?:연구|기술|사업)"),
              question="기존 연구·사업과 무엇이 다르며, 중복은 없습니까?"),
    CheckItem("goal_kpi", "목표와 성과지표 정량화", "기타",
              (r"성과\s*지표", r"목표\s*(?:치|값)", r"KPI", r"평가\s*지표", r"정량\s*(?:목표|지표)",
               r"(?:연구|사업|최종)\s*목표", r"최종\s*성과물", r"(?:달성|향상|감소|절감|단축)\s*목표"),
              needs_number=True, question="성과를 무엇으로, 얼마만큼 달성했는지 어떻게 측정합니까?"),
    CheckItem("governance", "추진 체계와 역할", "기타",
              (r"추진\s*(?:체계|전략|일정|계획)", r"(?<!관리)주관\s*기관", r"참여\s*기관", r"역할\s*분담",
               r"협업\s*체계", r"거버넌스"),
              question="누가 무엇을 맡고, 기관 간 역할은 어떻게 나눕니까?"),
    CheckItem("budget", "예산 규모와 산출 근거", "예산 타당성",
              (r"총\s*(?:사업비|연구비|예산)", r"사업\s*(?:비|예산|규모)", r"소요\s*(?:예산|재원)", r"산출\s*근거",
               r"단가", r"비목"),
              needs_number=True, question="총사업비와 비목별 금액은 어떤 근거(단가·수량)로 산출했습니까?"),
    CheckItem("outcome", "기대효과 정량화", "기타",
              (r"기대\s*효과", r"파급\s*효과", r"활용\s*방안", r"편익"),
              needs_number=True, question="기대효과를 수치로 제시할 수 있습니까?"),
    CheckItem("operation", "결과 활용·운영 주체", "기타",
              (r"운영\s*주체", r"사업화", r"현장\s*(?:적용|활용)", r"확산", r"실증\s*(?:이후|후)",
               r"후속\s*(?:사업|연구|과제)"),
              question="연구가 끝난 뒤 결과는 누가, 어떻게 운영·활용합니까?"),
)


@dataclass
class Evidence:
    line: int
    page: int | None
    text: str
    has_number: bool
    undecided: bool
    heading: bool


@dataclass
class CheckResult:
    item: CheckItem
    status: str  # 충족 / 근거 약함 / 누락
    evidence: list[Evidence] = field(default_factory=list)


def check_lines(lines: list[str], checklist: tuple[CheckItem, ...] = CHECKLIST) -> list[CheckResult]:
    pages, current = [], None
    for line in lines:
        if m := PAGE_MARK.search(line):
            current = int(m.group(1))
        pages.append(current)
    results = []
    for item in checklist:
        regex = re.compile("|".join(item.patterns))
        evidence = [
            Evidence(i, pages[i - 1], line.strip(), bool(UNIT_NUMBER.search(line)),
                     bool(UNDECIDED.search(line)), line.lstrip().startswith("#"))
            for i, line in enumerate(lines, 1)
            if regex.search(line) and not re.search(r"[·.…]{6,}", line) and not PAGE_MARK.fullmatch(line.strip())
        ]
        if not evidence:
            status = "누락"
        elif item.needs_number and not any(e.has_number for e in evidence):
            status = "근거 약함"
        elif all(e.undecided or e.heading for e in evidence) and any(e.undecided for e in evidence):
            status = "근거 약함"
        else:
            status = "충족"
        results.append(CheckResult(item, status, evidence))
    return results


def _cite(source: str, e: Evidence) -> str:
    page = f" (p.{e.page})" if e.page else ""
    return f"[출처: {source} L{e.line}-L{e.line}]{page}"


def _best(r: CheckResult, n: int = 2) -> list[Evidence]:
    return sorted(r.evidence, key=lambda e: (not e.heading, not e.has_number, e.line))[:n]


def render_precheck(results: list[CheckResult], source: str) -> str:
    """전체 점검표 (산출물 00b_사전점검.md)."""
    mark = {"충족": "충족", "근거 약함": "근거 약함", "누락": "누락"}
    counts = {s: sum(r.status == s for r in results) for s in mark}
    out = [
        "# 기획보고서 사전 점검 (규칙 기반)", "",
        f"- 대상: `{source}`",
        f"- 결과: 충족 {counts['충족']} · 근거 약함 {counts['근거 약함']} · 누락 {counts['누락']} (항목 {len(results)}개)", "",
        "| 항목 | 심의기준 | 결과 | 해당 줄 수 | 대표 근거 |", "|---|---|---|---|---|",
    ]
    for r in results:
        ev = "; ".join(f"{_cite(source, e)} {e.text[:40]}" for e in _best(r)) or "-"
        out.append(f"| {r.item.name} | {r.item.criterion} | {r.status} | {len(r.evidence)} | {ev} |")
    out += ["", "## 한계", "",
            "- 키워드와 단위 붙은 수치로 '있는지'만 본다. 내용이 타당한지, 수치가 맞는지는 판단하지 않는다.",
            "- 표현이 다르면 놓칠 수 있고, 키워드만 있고 내용이 빈약해도 충족으로 나온다."]
    return "\n".join(out)


def precheck_brief(results: list[CheckResult], source: str) -> str:
    """에이전트 지시문에 넣을 짧은 요약: 누락·근거 약함 항목만 (충족 항목은 넣지 않아 토큰을 아낌)."""
    gaps = [r for r in results if r.status != "충족"]
    if not gaps:
        return ""
    lines = ["사전 점검(규칙 기반)에서 아래 항목이 누락되었거나 근거가 약했습니다. "
             "보고서 원문으로 사실 여부를 확인한 뒤 우선 다루세요 (규칙 점검이라 오탐일 수 있음):"]
    for r in gaps:
        where = f" 근거 후보: {_cite(source, _best(r, 1)[0])}" if r.evidence else ""
        lines.append(f"- [{r.item.criterion}] {r.item.name} — {r.status}. 예상 질의: {r.item.question}{where}")
    return "\n".join(lines)


def run_precheck(report_text: str | None, source: str | None) -> tuple[str, str]:
    """(전체 점검표, 지시문용 요약). 원문 모드가 아니면 둘 다 빈 문자열."""
    if not report_text or not source:
        return "", ""
    from rdagents.dataflows import budget_check

    lines = report_text.splitlines()
    results = check_lines(lines)
    numbers = budget_check.check(lines)  # 표·본문 숫자가 서로 맞는지 (합계·비율·단가×수량·증감률)
    full = render_precheck(results, source) + "\n\n" + budget_check.render_section(numbers, source)
    brief_parts = [precheck_brief(results, source)]
    if numbers.findings:
        brief_parts.append("숫자 검산(코드 계산)에서 서로 맞지 않는 수치가 나왔습니다. 원문을 확인하고 질의하세요:\n"
                           + "\n".join(budget_check.brief_lines(numbers, source)))
    return full, "\n\n".join(p for p in brief_parts if p)
