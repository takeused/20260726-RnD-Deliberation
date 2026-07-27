"""🔬 기술 가치 분석가 — 핵심 기술의 독창성, TRL, 기술 파급력 평가."""

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from rdagents.agents.utils.agent_utils import get_language_instruction, get_project_context_from_state
from rdagents.agents.utils.review_criteria import get_review_criteria
from rdagents.dataflows.project_loader import get_project_overview, get_tech_details, search_report


def create_tech_value_analyst(llm):
    def tech_value_analyst_node(state):
        project_context = get_project_context_from_state(state)

        tools = [get_project_overview, get_tech_details, search_report]

        system_message = (
            "당신은 R&D 신규사업 예산 심의를 위한 **기술 가치 분석 전문가**입니다. "
            "다음 관점에서 사업의 기술적 가치를 철저하게 분석하여 상세한 보고서를 작성하세요:\n\n"
            "1. **핵심 기술의 독창성**: 해당 기술이 국내외에서 얼마나 독창적인가? 기존 기술 대비 차별적 우위가 있는가?\n"
            "2. **기술 성숙도(TRL) 분석**: 현재 TRL에서 목표 TRL까지 달성 가능성은? TRL 갭이 현실적으로 극복 가능한가?\n"
            "3. **기술 파급력과 공공가치**: 이 기술이 성공했을 때 다른 산업·분야 또는 공공서비스에 미치는 효과는? "
            "재난안전 사업이면 인명·재산 피해 저감, 예방·탐지·대응시간 단축, 현장 대응력과 사회 회복력 향상을 우선 평가하세요.\n"
            "4. **기술적 리스크**: 기술 개발 과정에서 예상되는 주요 기술적 난관과 실패 가능성은?\n"
            "5. **핵심 기술 확보 가능성**: 사업 기간 내 목표 기술 확보가 현실적으로 가능한가?\n\n"
            "반드시 구체적인 근거와 데이터를 기반으로 분석하고, 보고서 말미에 핵심 분석 결과를 정리한 "
            "Markdown 표를 첨부하세요."
            + get_review_criteria()
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages([
            (
                "system",
                "당신은 다른 전문가들과 협력하는 R&D 예산 심의 분석가입니다. "
                "제공된 도구를 사용하여 사업의 기술적 가치를 분석하세요. "
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

        report = ""
        if len(result.tool_calls) == 0:
            report = result.content

        return {
            "messages": [result],
            "tech_value_report": report,
        }

    return tech_value_analyst_node
