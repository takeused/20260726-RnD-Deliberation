"""✏️ 예산 조정관 (Budget Coordinator) — 전문위원회 심의 의견을 바탕으로 구체적 예산안 제시."""

import json

from langchain_core.prompts import ChatPromptTemplate

from rdagents.agents.schemas import (
    BudgetProposal,
    align_budget_proposal_to_request,
    render_budget_proposal,
)
from rdagents.agents.utils.agent_utils import get_language_instruction, make_ai_message
from rdagents.agents.utils.structured import invoke_structured_model
from rdagents.dataflows.project_loader import get_budget_details


def create_budget_coordinator(llm):
    def budget_coordinator_node(state):
        system_message = (
            "당신은 기획처 소속 **예산 조정관**입니다.\n"
            "전문위원회의 '1차 심의 의견(Review Plan)'과 원래 요청된 예산 내역을 바탕으로, "
            "실제 재정 투입을 위한 '구체적인 1차 예산 조정안'을 작성해야 합니다.\n\n"
            "다음을 명심하세요:\n"
            "1. 전문위원회가 '승인' 또는 '조건부승인'을 권고했다면, 예산 삭감 요인이 없는지 면밀히 검토하여 원안 또는 소폭 감액을 제안하세요.\n"
            "2. '감액조정'을 권고했다면, 구체적으로 몇 %를 삭감할지 명시하고 제안 예산을 계산하세요.\n"
            "3. '보류'나 '반려'를 권고했다면, 제안 예산을 0(또는 None)으로 설정하고 이유를 명시하세요.\n"
            "4. 이 조정안은 이후 '재정 검토팀'의 치열한 3자 토론의 안건이 됩니다."
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_message),
            ("human", "다음은 전문위원회의 1차 심의 의견입니다:\n\n{review_plan}\n\n"
                      "다음은 원본 사업의 예산 요구 내역입니다:\n\n{budget_info}\n\n"
                      "위 내용을 종합하여 기획처의 1차 예산 조정안을 도출해 주세요."),
        ])

        # 원래 예산 정보 가져오기 (문자열로)
        # LLM이 도구를 쓰지 않고 직접 값을 알 수 있도록 시스템 프롬프트에 주입
        # get_budget_details는 tool이지만 직접 호출하여 결과를 문자열로 주입
        try:
            budget_info = get_budget_details.invoke({})
        except Exception:
            budget_info = "예산 정보 조회 실패."

        plan_json = state.get("review_plan", "심의 의견 없음")

        prompt_val = prompt.invoke({"review_plan": plan_json, "budget_info": budget_info})
        requested_budget = state.get("project_facts", {}).get("requested_budget_eok")
        call = invoke_structured_model(
            llm,
            BudgetProposal,
            prompt_val,
            "Budget Coordinator",
            post_validate=lambda proposal: align_budget_proposal_to_request(
                proposal, requested_budget
            ),
        )
        proposal = call.model

        if proposal is None:
            # 구조화 출력 실패 시 자유 텍스트로 폴백 (파이프라인 중단 방지)
            free_text = llm.invoke(prompt_val).content
            proposal = BudgetProposal(
                action="보류",
                reasoning=f"구조화 출력 실패 — 본문 참조:\n{free_text}",
                original_budget_billion=0.0,
            )

        rendered = render_budget_proposal(proposal)

        return {
            "messages": [make_ai_message(rendered, "BudgetCoordinator", call.usage)],
            "budget_coordination_plan": proposal.model_dump_json(),
        }

    return budget_coordinator_node
