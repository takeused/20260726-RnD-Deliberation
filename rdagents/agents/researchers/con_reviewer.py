"""❌ 사업 우려/보류 전문위원 (Con Reviewer) — 사업의 리스크와 중복성, 예산 낭비 가능성 지적."""

from langchain_core.prompts import ChatPromptTemplate

from rdagents.agents.utils.agent_utils import get_language_instruction, make_ai_message
from rdagents.agents.utils.review_criteria import get_review_criteria


def create_con_reviewer(llm):
    def con_reviewer_node(state):
        system_message = (
            "당신은 R&D 예산 심의에서 **'사업 우려/보류(Con)' 입장을 맡은 전문위원**입니다.\n"
            "당신의 역할은 6명의 전문가가 작성한 분석 보고서를 종합하여, 이 사업의 리스크, "
            "예산 낭비 가능성, 기존 사업과의 중복성 등을 냉철하게 지적하는 것입니다.\n\n"
            "다음을 명심하세요:\n"
            "1. 분석가들의 보고서 중 부정적이거나 불확실한 요소(낮은 기술 성공률, 유사사업 존재, 과도한 예산, 규제 리스크 등)를 부각시키세요.\n"
            "2. 찬성측(추진 옹호 전문위원)의 주장이 있다면, 그 주장의 허점이나 지나치게 낙관적인 가정을 반박하세요.\n"
            "3. 국세가 투입되는 만큼 철저한 검증이 필요하며, 준비되지 않은 사업은 과감히 보류하거나 예산을 삭감해야 함을 주장하세요.\n"
            "4. 결론에는 사업 보류, 대폭 감액, 혹은 까다로운 조건부 승인을 권고하세요.\n\n"
            "전문가적이고 논리적인 어조로 발언을 작성하세요."
            + get_review_criteria()
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_message),
            ("human", "다음은 전문가들의 분석 보고서입니다:\n\n{reports}\n\n"
                      "찬성측(Pro Reviewer)의 이전 발언 내역:\n{pro_history}\n\n"
                      "위 내용을 바탕으로 당신의 반대/우려 논리를 전개해 주세요."),
        ])

        # 보고서 취합 (존재하는 것만)
        reports = []
        for key, name in [
            ("tech_value_report", "기술 가치 분석"),
            ("tech_trend_report", "기술 트렌드/중복성 분석"),
            ("economic_report", "경제/재무 타당성 분석"),
            ("policy_report", "정책 부합성 분석"),
            ("feasibility_report", "수행체계 분석"),
            ("regulatory_report", "규제/윤리 검토"),
        ]:
            if state.get(key):
                reports.append(f"--- {name} ---\n{state[key]}")

        prompt_val = prompt.invoke({
            "reports": "\n\n".join(reports),
            "pro_history": state["review_debate_state"]["pro_history"] or "아직 찬성측 발언이 없습니다.",
        })

        response = llm.invoke(prompt_val)
        new_content = response.content

        # 상태 업데이트 로직
        new_history = state["review_debate_state"]["history"] + f"\n[사업 우려/보류 위원]: {new_content}\n"
        new_con_history = state["review_debate_state"]["con_history"] + f"\n[사업 우려/보류 위원]: {new_content}\n"

        return {
            "messages": [make_ai_message(new_content, "ConReviewer", getattr(response, "usage_metadata", None))],
            "review_debate_state": {
                **state["review_debate_state"],
                "con_history": new_con_history,
                "history": new_history,
                "current_response": "Con",
                "count": state["review_debate_state"]["count"] + 1,  # Pro 발언 후 Con 발언 시 카운트 증가
            }
        }

    return con_reviewer_node
