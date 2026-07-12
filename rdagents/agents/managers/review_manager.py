"""📋 전문위원회 위원장 (Review Manager) — 심사 공방 종합 및 1차 심의 의견 도출."""

import json

from langchain_core.prompts import ChatPromptTemplate

from rdagents.agents.schemas import ReviewPlan, render_review_plan
from rdagents.agents.utils.agent_utils import clip_text, get_language_instruction, make_ai_message
from rdagents.agents.utils.review_criteria import get_review_criteria
from rdagents.agents.utils.structured import invoke_structured_model


def create_review_manager(llm):
    def review_manager_node(state):
        system_message = (
            "당신은 R&D 예산 심의를 주관하는 **전문위원회 위원장**입니다.\n"
            "전문가들의 분석 보고서와, 심사위원 패널의 질의·지적 및 사업 발표자의 방어 공방을 "
            "종합하여 최종적인 '1차 심의 의견'을 도출해야 합니다.\n\n"
            "다음을 명심하세요:\n"
            "1. 발표자가 근거로 방어에 성공한 지적과, 방어에 실패했거나 '보완하겠다'고 인정한 "
            "지적을 구분하세요. 방어 실패 지적이 곧 핵심 우려사항(Key Concerns)입니다.\n"
            "2. 최종 의견은 승인, 조건부승인, 감액조정, 보류, 반려 중 하나여야 합니다.\n"
            "3. 결정을 내린 합리적 근거(Rationale)와 향후 해결해야 할 핵심 우려사항(Key Concerns)을 명확히 제시하세요."
            + get_review_criteria()
            + ("\n" + state["gate_profile"] if state.get("gate_profile") else "")
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_message),
            ("human", "다음은 심사위원 패널과 사업 발표자의 공방 내역입니다:\n\n{debate_history}\n\n"
                      "이 사업의 이전 심의 이력 (있는 경우 지적사항 해소 여부를 중점 확인하세요):\n"
                      "{past_context}\n\n"
                      "위 토론을 종합하여 전문위원회의 심의 의견을 결정해 주세요."),
        ])

        debate_history = state["review_debate_state"]["history"]
        if not debate_history:
            debate_history = "토론 내역이 없습니다."

        prompt_val = prompt.invoke({
            "debate_history": clip_text(debate_history, state),
            "past_context": clip_text(state.get("past_context") or "", state) or "이전 심의 이력 없음 (신규 심의).",
        })
        call = invoke_structured_model(llm, ReviewPlan, prompt_val, "Review Manager")
        plan = call.model

        if plan is None:
            # 구조화 출력 실패 시 자유 텍스트로 폴백 (파이프라인 중단 방지)
            free_text = llm.invoke(prompt_val).content
            plan = ReviewPlan(
                verdict="보류",
                rationale=free_text,
                key_concerns="구조화 출력 실패 — 본문(rationale) 참조",
            )

        rendered = render_review_plan(plan)

        new_history = state["review_debate_state"]["history"] + f"\n[전문위원회 위원장]:\n{rendered}\n"

        return {
            "messages": [make_ai_message(rendered, "ReviewManager", call.usage)],
            "review_plan": plan.model_dump_json(),
            "review_debate_state": {
                **state["review_debate_state"],
                "judge_decision": rendered,
                "history": new_history,
            }
        }

    return review_manager_node
