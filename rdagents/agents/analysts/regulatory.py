"""⚖️ 규제/윤리 검토가 — 생명윤리, 안전, 수출통제, 개인정보보호 리스크."""

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from rdagents.agents.utils.agent_utils import get_language_instruction, get_project_context_from_state
from rdagents.agents.utils.review_criteria import get_review_criteria
from rdagents.dataflows.project_loader import get_project_overview, get_regulatory_info, search_report


def create_regulatory_analyst(llm):
    def regulatory_analyst_node(state):
        project_context = get_project_context_from_state(state)
        tools = [get_regulatory_info, get_project_overview, search_report]

        system_message = (
            "당신은 R&D 신규사업 예산 심의를 위한 **규제 및 윤리 검토 전문가**입니다. "
            "다음 관점에서 사업 추진 시 예상되는 규제 리스크와 윤리적 이슈를 분석하세요:\n\n"
            "1. **생명/연구 윤리**: 임상시험, 동물실험, 인체유래물 연구 등에 따른 윤리적 타당성과 IRB/IACUC 승인 가능성.\n"
            "2. **데이터 및 개인정보보호**: 대규모 데이터 활용 시 개인정보보호법 등 관련 법령 준수 여부 및 리스크.\n"
            "3. **안전 및 환경 규제**: 신물질, 생물안전(LMO), 방사선 등 연구 수행에 따른 안전/환경 리스크.\n"
            "4. **수출통제 및 국제 규범**: 양자, 우주, 원자력 등 전략기술의 경우 국제 수출통제(EAR 등)나 보안 이슈 여부.\n"
            "5. **규제 샌드박스 필요성**: 현행 규제로 인해 연구나 사업화가 불가능하여 규제 특례가 필요한가?\n\n"
            "분석 내용을 종합하여 사업 추진에 치명적인(Showstopper) 규제 리스크가 있는지 판단하고, "
            "Markdown 표로 핵심 결과를 정리하세요."
            + get_review_criteria()
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages([
            (
                "system",
                "당신은 다른 전문가들과 협력하는 R&D 예산 심의 분석가입니다. "
                "제공된 도구를 사용하여 규제 및 윤리 리스크를 분석하세요. "
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
        return {"messages": [result], "regulatory_report": report}

    return regulatory_analyst_node
