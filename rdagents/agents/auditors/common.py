"""재정 검토팀 3명(적극·건전성·균형)의 공통 입력과 수치 규칙.

이전에는 예산 조정안과 서로의 발언만 읽어서, 근거가 없을 때도 입장을 세우려고 피해 저감률·경제 효과·
증감액(예: 'n억 추가', 'n% 감액')을 지어냈다 (NDMI groq8: 이 토론의 원문에 없는 수치 표시 줄 5 -> 12,
요청 예산을 원문에서 찾지 못한 실행인데도). 다른 노드처럼 코드가 확인한 사실(요청 예산·쟁점 원장)을 주고,
근거 없는 수치 대신 조건으로 주장하게 한다.
"""

from rdagents.agents.utils.agent_utils import clip_text
from rdagents.dataflows.issue_ledger import ledger_summary

AUDIT_RULES = (
    "\n\n수치 규칙 (코드가 원문과 대조해 원문에 없는 수치에 표시를 붙입니다):\n"
    "- 피해 저감률·시장 규모·경제 효과·성과 목표 같은 수치는 아래 '확인된 사실'과 예산 조정안에 있는 것만 쓰세요. "
    "없으면 수치 없이 '[확인 필요: 무엇]'으로만 쓰세요. 예시로 드는 수치도 쓰지 마세요.\n"
    "- 확인된 요청 예산이 없으면 증액·감액 금액이나 비율을 제시하지 말고, 조건(단계적 지원, 성과관문, "
    "보완 자료 제출)으로만 주장하세요.\n"
    "- 쟁점 원장에서 방어 실패한 쟁점은 입장과 관계없이 해결 조건을 함께 말하세요."
)


def audit_facts(state) -> str:
    """코드가 확인한 사실: 원문의 요청 예산과 쟁점 원장 요약."""
    budget = (state.get("project_facts") or {}).get("requested_budget_eok")
    lines = [f"- 원문에서 확인된 요청 예산: {budget}억 원" if budget
             else "- 원문에서 확인된 요청 예산: 없음 (금액·비율을 제시하지 말 것)"]
    ledger = state.get("issue_ledger") or []
    lines.append(clip_text(ledger_summary(ledger), state) if ledger else "- 쟁점 원장 없음")
    return "\n".join(lines)
