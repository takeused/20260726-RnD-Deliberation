"""🏗️ 수행체계 분석가 — 수행기관 역량, 연구팀 구성, 인프라, 성과관리."""

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from rdagents.agents.utils.agent_utils import get_language_instruction, get_project_context_from_state
from rdagents.agents.utils.review_criteria import get_review_criteria
from rdagents.dataflows.project_loader import get_institution_info, get_project_overview, search_report


def create_feasibility_analyst(llm):
    def feasibility_analyst_node(state):
        project_context = get_project_context_from_state(state)
        tools = [get_institution_info, get_project_overview, search_report]

        system_message = (
            "당신은 R&D 신규사업 예산 심의를 위한 **수행체계 분석 전문가**입니다. "
            "다음 관점에서 사업의 수행 가능성을 분석하세요:\n\n"
            "1. **수행기관 역량**: 주관기관 및 공동연구기관의 해당 분야 연구 역량과 실적은 충분한가?\n"
            "2. **연구팀 구성**: 연구책임자(PI)의 전문성과 연구팀 규모가 사업 목표 달성에 적합한가?\n"
            "3. **연구 인프라**: 필요한 시설·장비·데이터가 확보되어 있거나 조달 계획이 수립되어 있는가?\n"
            "4. **성과 관리 체계**: 연차별 성과 목표가 구체적이고 측정 가능한가? 성과 관리 체계는 적절한가?\n"
            "5. **연구팀 안정성**: 핵심 연구인력의 이탈 리스크는 없는가? 후속 인력 양성 계획은?\n"
            "6. **기관 간 협력 체계**: 공동연구기관 간 역할 분담과 협력 체계가 명확한가?\n\n"
            "반드시 구체적인 근거를 기반으로 분석하고, Markdown 표로 핵심 결과를 정리하세요."
            + get_review_criteria()
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages([
            (
                "system",
                "당신은 다른 전문가들과 협력하는 R&D 예산 심의 분석가입니다. "
                "제공된 도구를 사용하여 수행체계를 분석하세요. "
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
        return {"messages": [result], "feasibility_report": report}

    return feasibility_analyst_node
