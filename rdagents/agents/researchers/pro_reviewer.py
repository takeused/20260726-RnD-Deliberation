"""✅ 사업 추진 옹호 전문위원 (Pro Reviewer) — 사업의 당위성과 기대효과 강조."""

from langchain_core.prompts import ChatPromptTemplate

from rdagents.agents.utils.agent_utils import get_language_instruction, make_ai_message
from rdagents.agents.utils.review_criteria import get_review_criteria


def create_pro_reviewer(llm):
    def pro_reviewer_node(state):
        system_message = (
            "당신은 R&D 예산 심의에서 **'사업 추진 옹호(Pro)' 입장을 맡은 전문위원**입니다.\n"
            "당신의 역할은 6명의 전문가가 작성한 분석 보고서를 종합하여, 이 사업이 왜 반드시 "
            "추진되어야 하는지, 국가 경제와 기술 발전에 어떤 긍정적 파급효과를 가져올지 강력하게 "
            "주장하는 것입니다.\n\n"
            "다음을 명심하세요:\n"
            "1. 분석가들의 보고서 중 긍정적인 요소(높은 기술 가치, 명확한 정책 부합성, 탁월한 연구팀 등)를 부각시키세요.\n"
            "2. 반대측(우려/보류 전문위원)의 주장이 있다면, 이를 반박할 수 있는 논리를 제시하세요.\n"
            "3. 리스크가 존재하더라도, 이를 감수하고 투자해야만 하는 '전략적 당위성'을 강조하세요.\n"
            "4. 결론에는 사업 원안 통과 또는 과감한 투자를 강력히 권고하세요.\n\n"
            "전문가적이고 논리적인 어조로 발언을 작성하세요."
            + get_review_criteria()
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_message),
            ("human", "다음은 전문가들의 분석 보고서입니다:\n\n{reports}\n\n"
                      "반대측(Con Reviewer)의 이전 발언 내역:\n{con_history}\n\n"
                      "위 내용을 바탕으로 당신의 옹호 논리를 전개해 주세요."),
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
            "con_history": state["review_debate_state"]["con_history"] or "아직 반대측 발언이 없습니다.",
        })

        response = llm.invoke(prompt_val)
        new_content = response.content

        # 상태 업데이트 로직
        new_history = state["review_debate_state"]["history"] + f"\n[사업 추진 옹호 위원]: {new_content}\n"
        new_pro_history = state["review_debate_state"]["pro_history"] + f"\n[사업 추진 옹호 위원]: {new_content}\n"

        return {
            "messages": [make_ai_message(new_content, "ProReviewer", getattr(response, "usage_metadata", None))],
            "review_debate_state": {
                **state["review_debate_state"],
                "pro_history": new_pro_history,
                "history": new_history,
                "current_response": "Pro",
                "count": state["review_debate_state"]["count"] + 1,
            }
        }

    return pro_reviewer_node
