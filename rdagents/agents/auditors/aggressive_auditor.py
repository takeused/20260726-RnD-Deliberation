"""🚀 적극 투자 검토관 (Aggressive Auditor) — 국가 미래를 위해 과감한 투자 옹호."""

from langchain_core.prompts import ChatPromptTemplate

from rdagents.agents.utils.agent_utils import get_language_instruction, make_ai_message


def create_aggressive_auditor(llm):
    def aggressive_auditor_node(state):
        system_message = (
            "당신은 기획처 재정 검토팀 소속 **'적극 투자 검토관(Aggressive Auditor)'**입니다.\n"
            "예산 조정관이 제출한 '1차 예산 조정안'을 검토하여, 국가 미래 기술 확보와 산업 선점을 위해 "
            "과감하게 투자해야 한다는 입장을 대변합니다.\n\n"
            "다음을 명심하세요:\n"
            "1. 예산이 감액되었거나 보류되었다면, 이를 비판하고 예산 원안 통과 또는 증액을 강력히 주장하세요.\n"
            "2. 단기적인 재정 부담보다는 중장기적 파급효과와 기술 패권 경쟁에서의 승리 가능성을 강조하세요.\n"
            "3. 타 검토관(재정 건전성 검토관 등)의 이전 발언이 있다면 이를 반박하세요.\n"
            "4. 리스크를 수용하고 도전적인 목표를 지향해야 한다고 주장하세요."
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_message),
            ("human", "다음은 예산 조정관의 1차 예산 조정안입니다:\n\n{budget_plan}\n\n"
                      "타 검토관들의 이전 발언 내역:\n{audit_history}\n\n"
                      "위 내용을 바탕으로 적극적인 투자 확대를 지지하는 논리를 전개해 주세요."),
        ])

        budget_plan = state.get("budget_coordination_plan", "예산안 없음")
        audit_history = state["audit_debate_state"]["history"] or "이전 발언이 없습니다."

        prompt_val = prompt.invoke({"budget_plan": budget_plan, "audit_history": audit_history})
        response = llm.invoke(prompt_val)
        new_content = response.content

        new_history = state["audit_debate_state"]["history"] + f"\n[적극 투자 검토관]: {new_content}\n"
        new_agg_history = state["audit_debate_state"]["aggressive_history"] + f"\n[적극 투자 검토관]: {new_content}\n"

        return {
            "messages": [make_ai_message(new_content, "AggressiveAuditor", getattr(response, "usage_metadata", None))],
            "audit_debate_state": {
                **state["audit_debate_state"],
                "aggressive_history": new_agg_history,
                "history": new_history,
                "latest_speaker": "Aggressive Auditor",
                "current_aggressive_response": new_content,
                "count": state["audit_debate_state"]["count"] + 1,
            }
        }

    return aggressive_auditor_node
