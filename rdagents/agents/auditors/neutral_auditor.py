"""⚖️ 균형 재정 조율관 (Neutral Auditor) — 양측 의견 절충 및 합리적 타협점 모색."""

from langchain_core.prompts import ChatPromptTemplate

from rdagents.agents.utils.agent_utils import get_language_instruction, make_ai_message


def create_neutral_auditor(llm):
    def neutral_auditor_node(state):
        system_message = (
            "당신은 기획처 재정 검토팀 소속 **'균형 재정 조율관(Neutral Auditor)'**입니다.\n"
            "당신의 역할은 '적극 투자 검토관'과 '재정 건전성 검토관' 간의 극단적인 의견 대립을 중재하고, "
            "국가 R&D 예산의 효율성과 혁신성을 동시에 달성할 수 있는 합리적인 타협점을 도출하는 것입니다.\n\n"
            "다음을 명심하세요:\n"
            "1. 예산 조정관의 1차 예산안과 양측 검토관의 주장을 객관적으로 분석하세요.\n"
            "2. 리스크 관리를 위한 단계적 투자(Phase-gate 방식), 민간 매칭 비율 조정, 부처 간 예산 이관 등 창의적 대안을 제시하세요.\n"
            "3. 어느 한쪽으로 치우치지 않는 냉철하고 균형 잡힌 어조를 유지하세요.\n"
            "4. 최종 심의위원장이 판단하기 쉽게 실현 가능한 최적의 예산 조율안을 권고하세요."
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_message),
            ("human", "다음은 예산 조정관의 1차 예산 조정안입니다:\n\n{budget_plan}\n\n"
                      "적극 투자 및 재정 건전성 검토관들의 이전 발언 내역:\n{audit_history}\n\n"
                      "위 내용을 바탕으로 양측의 주장을 절충한 최적의 조율안을 제시해 주세요."),
        ])

        budget_plan = state.get("budget_coordination_plan", "예산안 없음")
        audit_history = state["audit_debate_state"]["history"] or "이전 발언이 없습니다."

        prompt_val = prompt.invoke({"budget_plan": budget_plan, "audit_history": audit_history})
        response = llm.invoke(prompt_val)
        new_content = response.content

        new_history = state["audit_debate_state"]["history"] + f"\n[균형 재정 조율관]: {new_content}\n"
        new_neutral_history = state["audit_debate_state"]["neutral_history"] + f"\n[균형 재정 조율관]: {new_content}\n"

        return {
            "messages": [make_ai_message(new_content, "NeutralAuditor", getattr(response, "usage_metadata", None))],
            "audit_debate_state": {
                **state["audit_debate_state"],
                "neutral_history": new_neutral_history,
                "history": new_history,
                "latest_speaker": "Neutral Auditor",
                "current_neutral_response": new_content,
                "count": state["audit_debate_state"]["count"] + 1,  # 3명이 모두 발언하면 1라운드 종료
            }
        }

    return neutral_auditor_node
