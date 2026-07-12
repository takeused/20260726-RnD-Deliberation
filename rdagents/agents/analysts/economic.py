"""💰 경제/재무 타당성 분석가 — B/C 분석, 예산 적정성, 경제적 파급효과."""

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from rdagents.agents.utils.agent_utils import get_language_instruction, get_project_context_from_state
from rdagents.agents.utils.review_criteria import get_review_criteria
from rdagents.dataflows.project_loader import get_budget_details, get_project_overview, search_report


def create_economic_analyst(llm):
    def economic_analyst_node(state):
        project_context = get_project_context_from_state(state)
        tools = [get_budget_details, get_project_overview, search_report]

        system_message = (
            "당신은 R&D 신규사업 예산 심의를 위한 **경제/재무 타당성 분석 전문가**입니다. "
            "다음 관점에서 사업의 경제성과 예산 타당성을 철저히 분석하세요:\n\n"
            "1. **비용편익(B/C) 분석**: 투입 예산 대비 기대되는 경제적 편익은 적정한가? B/C ratio를 추정하세요.\n"
            "2. **예산 규모 적정성**: 요청 예산이 사업 목표 달성에 적정한가? 과다 또는 과소 요청은 아닌가?\n"
            "3. **연차별 예산 배분**: 사업 기간 대비 연평균 투자 규모가 합리적인가?\n"
            "4. **민간 투자 유인**: 정부 투자 대비 민간 투자(매칭펀드) 비율은 적절한가?\n"
            "5. **경제적 파급효과**: 고용 창출, 수출 증대, 산업 생태계 구축 등 구체적 경제적 기대효과는?\n"
            "6. **재원 조달 및 재정 부담**: 중장기 재정 부담은 감당 가능한 수준인가?\n\n"
            "반드시 구체적인 수치와 비율을 활용하여 분석하고, Markdown 표로 핵심 결과를 정리하세요."
            + get_review_criteria()
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages([
            (
                "system",
                "당신은 다른 전문가들과 협력하는 R&D 예산 심의 분석가입니다. "
                "제공된 도구를 사용하여 경제/재무 타당성을 분석하세요. "
                "사용 가능한 도구: {tool_names}. "
                "심의 대상 연도: {review_year}. {project_context}\n"
                "{system_message}",
            ),
            MessagesPlaceholder(variable_name="messages"),
        ])

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([t.name for t in tools]))
        prompt = prompt.partial(review_year=state["review_year"])
        prompt = prompt.partial(project_context=project_context)

        chain = prompt | llm.bind_tools(tools)
        result = chain.invoke(state["messages"])

        report = result.content if len(result.tool_calls) == 0 else ""
        return {"messages": [result], "economic_report": report}

    return economic_analyst_node
