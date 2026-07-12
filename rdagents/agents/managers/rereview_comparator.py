"""과거 심의 요약과 현재 심의 결과를 비교하는 재심의 변화 분석 노드."""

from langchain_core.prompts import ChatPromptTemplate

from rdagents.agents.schemas import ReReviewComparison, render_rereview_comparison
from rdagents.agents.utils.agent_utils import clip_text, get_language_instruction, make_ai_message
from rdagents.agents.utils.structured import invoke_structured_model


def create_rereview_comparator(llm):
    def rereview_comparator_node(state):
        past = state.get("past_context", "")
        usage = None
        if not past:
            comparison = ReReviewComparison(status="신규 심의")
        else:
            prompt = ChatPromptTemplate.from_messages([
                ("system", "당신은 R&D 재심의 변경사항 감사자입니다. 이전 지적이 실제로 해소됐다는 "
                           "현재 근거가 있을 때만 해소로 분류하고, 불명확하면 미해소로 분류하세요. "
                           "이전·현재 결정 및 승인 예산 변화도 명시하세요."),
                ("human", "## 이전 심의 이력\n{past}\n\n## 현재 전문위원회 의견\n{plan}\n\n"
                          "## 현재 최종결정\n{decision}\n\n## 현재 보완 권고\n{improvements}\n\n"
                          "해소·미해소·신규 우려를 근거 중심으로 비교하세요."),
            ])
            prompt_val = prompt.invoke({
                "past": clip_text(past, state),
                "plan": state.get("review_plan") or "없음",
                "decision": state.get("final_review_decision") or "없음",
                "improvements": clip_text(state.get("improvement_recommendations_md") or "", state) or "없음",
            })
            call = invoke_structured_model(
                llm, ReReviewComparison, prompt_val, "Re-review Comparator"
            )
            usage = call.usage
            comparison = call.model
            if comparison is None:
                comparison = ReReviewComparison(
                    status="재심의",
                    unresolved_concerns=[llm.invoke(prompt_val).content],
                    summary="구조화 비교 실패로 자유 형식 결과를 미해소 항목에 기록했습니다.",
                )
        rendered = render_rereview_comparison(comparison)
        return {
            "messages": [make_ai_message(rendered, "ReReviewComparator", usage)],
            "rereview_comparison_md": rendered,
        }

    return rereview_comparator_node
