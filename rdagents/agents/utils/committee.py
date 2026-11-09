# 심의위원 구성 — 사업 유형별 분야 기술전문가 3명과 심사위원 패널 위원의 단일 정의
"""실제 재난안전 R&D 심의는 기술가치·중복성·경제성 같은 기능별 검토와 별도로 해당 분야 기술전문가가
기술 내용을 검토한다. 기능별 분석가 6명만으로는 '이 재난 현상을 이 방법으로 정말 다룰 수 있나',
'현장 장비·체계와 맞나'를 깊이 묻는 사람이 없었다.

패널 위원은 쟁점의 심의기준에 따라 코드가 배정한다 (누가 묻는지 질의마다 남김). 공공임무형에는 현장
실무위원(소방·지자체 재난부서 같은 수요자 관점)을 둔다. '현장에서 정말 쓸 수 있나'는 재난안전 R&D
심의에서 자주 나오는 질문인데 이전 구성에는 그 관점의 위원이 없었다.
"""

from rdagents.dataflows.project_type import INDUSTRY, MIXED, PUBLIC

# 분야 기술전문가 3명: (이름, 검토 관점)
_PUBLIC_EXPERTS = (
    ("재난 위험·현상 전문가", "대상 재난의 발생 메커니즘·피해 양상, 위험 평가·예측 방법의 과학적 타당성과 한계"),
    ("재난안전 ICT·데이터 전문가", "센서·데이터·AI·시스템 구성, 데이터 확보 가능성과 품질, 기존 재난관리 시스템과의 연계"),
    ("방재·현장 대응 실무 전문가", "현장 운용성, 기존 장비·대응 체계와의 호환, 실증 환경과 현장 검증 방법"),
)
_INDUSTRY_EXPERTS = (
    ("핵심 원천기술 전문가", "핵심 기술의 과학적 타당성, 국내외 기술 수준 대비 목표의 도전성과 실현 가능성"),
    ("응용·시스템 통합 전문가", "구성 기술 간 통합, 성능 목표의 측정 가능성, 개발 일정의 기술적 위험"),
    ("실증·사업화 기술 전문가", "실증 계획, 양산·표준·인증 요건, 수요기업이 쓸 수 있는 수준인지"),
)
DOMAIN_EXPERTS = {PUBLIC: _PUBLIC_EXPERTS, MIXED: _PUBLIC_EXPERTS, INDUSTRY: _INDUSTRY_EXPERTS}

# 심사위원 패널: 쟁점의 심의기준 -> 질의하는 위원
_PUBLIC_PANEL = {
    "정부지원 필요성": "재난안전 정책위원",
    "기술개발의 중요성": "기술위원",
    "시급성": "재난안전 정책위원",
    "현장 적용·확산": "현장 실무위원",
    "예산 타당성": "재정위원",
    "기타": "기술위원",
}
_INDUSTRY_PANEL = {
    "정부지원 필요성": "산업·시장위원",
    "기술개발의 중요성": "기술위원",
    "시급성": "산업·시장위원",
    "현장 적용·확산": "사업화위원",
    "예산 타당성": "재정위원",
    "기타": "기술위원",
}
PANEL_MEMBERS = {PUBLIC: _PUBLIC_PANEL, MIXED: _PUBLIC_PANEL, INDUSTRY: _INDUSTRY_PANEL}
REGULATORY_MEMBER = "법·제도위원"  # 규제·윤리 분석가의 쟁점은 기준과 관계없이 이 위원이 묻는다


def domain_experts(project_type: str | None) -> tuple[tuple[str, str], ...]:
    return DOMAIN_EXPERTS.get(project_type or MIXED, _PUBLIC_EXPERTS)


def panel_member(project_type: str | None, criterion: str, source: str = "") -> str:
    """쟁점을 질의할 위원. source는 쟁점을 낸 분석가 보고서 키 (규제·윤리면 법·제도위원)."""
    if source == "regulatory_report":
        return REGULATORY_MEMBER
    panel = PANEL_MEMBERS.get(project_type or MIXED, _PUBLIC_PANEL)
    return panel.get(criterion, panel["기타"])


def panel_roster(project_type: str | None) -> str:
    """프롬프트·산출물에 넣을 위원 명단."""
    panel = PANEL_MEMBERS.get(project_type or MIXED, _PUBLIC_PANEL)
    members = list(dict.fromkeys([*panel.values(), REGULATORY_MEMBER]))
    return ", ".join(members)
