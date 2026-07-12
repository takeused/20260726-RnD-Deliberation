"""🏛️ 정책 부합성 분석가 — 국가 전략기술, 과학기술 기본계획 정합성."""

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from rdagents.agents.utils.agent_utils import get_language_instruction, get_project_context_from_state
from rdagents.agents.utils.review_criteria import get_review_criteria
from rdagents.dataflows.project_loader import get_policy_alignment, get_project_overview, search_report


def create_policy_analyst(llm):
    def policy_analyst_node(state):
        project_context = get_project_context_from_state(state)
        tools = [get_policy_alignment, get_project_overview, search_report]

        system_message = (
            "당신은 R&D 신규사업 예산 심의를 위한 **정책 부합성 분석 전문가**입니다. "
            "다음 관점에서 사업의 국가 정책 부합도를 분석하세요:\n\n"
            "1. **국가 전략기술 12대 분야 부합성**: 본 사업이 반도체·디스플레이, AI, 양자, 바이오, 우주항공 등 12대 국가전략기술에 부합하는가?\n"
            "2. **과학기술 기본계획 정합성**: 제5차 과학기술 기본계획의 핵심 추진 과제와 얼마나 일치하는가?\n"
            "3. **국정과제 연계성**: 현 정부의 국정과제 및 R&D 혁신 방안과의 연계성은?\n"
            "4. **범부처 정책 정합성**: 관련 부처(과기부, 산업부, 복지부 등)의 정책 방향과 모순되지 않는가?\n"
            "5. **정책 우선순위**: 현 시점에서 이 사업의 정책적 우선순위는 어느 정도인가?\n\n"
            "반드시 구체적인 정책 문서를 인용하여 분석하고, Markdown 표로 핵심 결과를 정리하세요."
            + get_review_criteria()
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages([
            (
                "system",
                "당신은 다른 전문가들과 협력하는 R&D 예산 심의 분석가입니다. "
                "제공된 도구를 사용하여 정책 부합성을 분석하세요. "
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
        return {"messages": [result], "policy_report": report}

    return policy_analyst_node
