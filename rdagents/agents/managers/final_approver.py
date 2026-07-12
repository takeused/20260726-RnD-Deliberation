"""🏆 최종 심의위원장 (Final Approver) — 기획처 재정 검토 토론을 종합하여 최종 결정 도출."""

from langchain_core.prompts import ChatPromptTemplate

from rdagents.agents.schemas import FinalDecision, render_final_decision
from rdagents.agents.utils.agent_utils import clip_text, get_language_instruction, make_ai_message
from rdagents.agents.utils.structured import invoke_structured_model


_REPORT_SECTIONS = [
    ("tech_value_report", "기술 가치"),
    ("tech_trend_report", "기술 트렌드·중복성"),
    ("economic_report", "경제·재무 타당성"),
    ("policy_report", "정책 부합성"),
    ("feasibility_report", "수행체계"),
    ("regulatory_report", "규제·윤리"),
]


def create_final_approver(llm):
    def final_approver_node(state):
        system_message = (
            "당신은 국가과학기술자문회의 및 기획재정부의 R&D 예산을 최종 확정하는 **최종 심의위원장**입니다.\n"
            "6개 전문 분석 보고서, 전문위원회 의견, 예산 조정안과 재정 검토팀의 "
            "3자 토론 내역을 직접 대조하여 최종 결정을 내려야 합니다.\n\n"
            "다음을 명심하세요:\n"
            "1. 국가 재정의 건전성과 미래 성장 동력 확보라는 두 가지 가치를 종합적으로 고려하세요.\n"
            "2. '균형 재정 조율관'의 중재안을 가장 비중 있게 검토하되, 최종 판단은 당신의 몫입니다.\n"
            "3. 최종 결정은 승인, 조건부승인, 감액조정, 보류, 반려 중 하나여야 하며, 최종 승인 예산(억원)을 확정해야 합니다.\n"
            "4. 조건부 승인의 경우, 명확한 이행 조건을 부과하세요.\n"
            "5. 국가 R&D 심의의 최고 책임자로서 위엄 있고 명쾌하게 사유를 설명하세요."
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_message),
            ("human", "다음은 6개 전문 분석 보고서입니다:\n\n{analyst_reports}\n\n"
                      "다음은 전문위원회 위원장 의견입니다:\n\n{review_plan}\n\n"
                      "다음은 예산 조정관의 1차 예산안입니다:\n\n{budget_plan}\n\n"
                      "다음은 재정 검토팀의 3자 토론 내역입니다:\n\n{audit_history}\n\n"
                      "이 사업의 이전 심의 이력 (있는 경우 지적사항 해소 여부를 반영하세요):\n"
                      "{past_context}\n\n"
                      "위 내용을 종합하여 최종 심의 결과를 도출해 주세요."),
        ])

        budget_plan = state.get("budget_coordination_plan", "예산안 없음")
        reports = [
            f"--- {title} 분석 ---\n{state[key]}"
            for key, title in _REPORT_SECTIONS
            if state.get(key)
        ]
        audit_history = state["audit_debate_state"]["history"]
        if not audit_history:
            audit_history = "토론 내역이 없습니다."

        prompt_val = prompt.invoke({
            "analyst_reports": clip_text("\n\n".join(reports), state) or "전문 분석 보고서 없음",
            "review_plan": state.get("review_plan") or "전문위원회 의견 없음",
            "budget_plan": budget_plan,
            "audit_history": clip_text(audit_history, state),
            "past_context": clip_text(state.get("past_context") or "", state) or "이전 심의 이력 없음 (신규 심의).",
        })
        call = invoke_structured_model(llm, FinalDecision, prompt_val, "Final Approver")
        decision = call.model

        if decision is None:
            # 구조화 출력 실패 시 자유 텍스트로 폴백 (파이프라인 중단 방지)
            free_text = llm.invoke(prompt_val).content
            decision = FinalDecision(
                verdict="보류",
                executive_summary="구조화 출력 실패 — 상세 근거 참조",
                review_rationale=free_text,
                approved_budget_billion=None,
            )

        rendered = render_final_decision(decision)

        new_history = state["audit_debate_state"]["history"] + f"\n[최종 심의위원장]:\n{rendered}\n"

        return {
            "messages": [make_ai_message(rendered, "FinalApprover", call.usage)],
            "final_review_decision": decision.model_dump_json(),
            "audit_debate_state": {
                **state["audit_debate_state"],
                "judge_decision": rendered,
                "history": new_history,
            }
        }

    return final_approver_node
