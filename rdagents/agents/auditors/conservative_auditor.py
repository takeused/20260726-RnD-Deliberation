"""🛡️ 재정 건전성 검토관 (Conservative Auditor) — 예산 낭비 요소 차단 및 재정 부담 최소화 주장."""

from langchain_core.prompts import ChatPromptTemplate

from rdagents.agents.utils.agent_utils import clip_text, get_language_instruction, make_ai_message


def create_conservative_auditor(llm):
    def conservative_auditor_node(state):
        system_message = (
            "당신은 기획처 재정 검토팀 소속 **'재정 건전성 검토관(Conservative Auditor)'**입니다.\n"
            "예산 조정관이 제출한 '1차 예산 조정안'을 검토하여, 세금 낭비 요소를 철저히 배제하고 "
            "국가 재정 부담을 최소화해야 한다는 입장을 대변합니다.\n\n"
            "다음을 명심하세요:\n"
            "1. 예산 원안 통과 또는 증액이 제안되었다면, 이를 비판하고 대폭적인 감액, 단계적 지원 또는 전면 보류를 주장하세요.\n"
            "2. 기술적 불확실성, 기존 사업과의 중복성, 성과지표와 피해저감 근거 부족을 철저히 지적하세요. "
            "민간 영역 구축(Crowding-out)은 시장성이 있는 사업에만 적용하고 공공재형 재난안전 사업에 기계적으로 적용하지 마세요.\n"
            "3. 타 검토관(특히 적극 투자 검토관)의 이전 발언이 있다면 논리적으로 반박하세요.\n"
            "4. 반드시 성공할 수 있는 필수 항목에만 최소한의 예산을 투입해야 한다고 주장하세요."
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_message),
            ("human", "다음은 예산 조정관의 1차 예산 조정안입니다:\n\n{budget_plan}\n\n"
                      "타 검토관들의 이전 발언 내역:\n{audit_history}\n\n"
                      "위 내용을 바탕으로 재정 건전성 확보 및 예산 감액 논리를 전개해 주세요."),
        ])

        budget_plan = state.get("budget_coordination_plan", "예산안 없음")
        audit_history = clip_text(state["audit_debate_state"]["history"], state) or "이전 발언이 없습니다."

        prompt_val = prompt.invoke({"budget_plan": budget_plan, "audit_history": audit_history})
        response = llm.invoke(prompt_val)
        new_content = response.content

        new_history = state["audit_debate_state"]["history"] + f"\n[재정 건전성 검토관]: {new_content}\n"
        new_con_history = state["audit_debate_state"]["conservative_history"] + f"\n[재정 건전성 검토관]: {new_content}\n"

        return {
            "messages": [make_ai_message(new_content, "ConservativeAuditor", getattr(response, "usage_metadata", None))],
            "audit_debate_state": {
                **state["audit_debate_state"],
                "conservative_history": new_con_history,
                "history": new_history,
                "latest_speaker": "Conservative Auditor",
                "current_conservative_response": new_content,
                "count": state["audit_debate_state"]["count"] + 1,
            }
        }

    return conservative_auditor_node
