"""📊 기술 트렌드/중복성 분석가 — 글로벌 R&D 트렌드 대비 선도성, 유사사업 중복성 판정."""

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from rdagents.agents.utils.agent_utils import get_language_instruction, get_project_context_from_state
from rdagents.agents.utils.review_criteria import get_review_criteria
from rdagents.dataflows.project_loader import get_similar_projects, get_tech_details, search_report


def create_tech_trend_analyst(llm):
    def tech_trend_analyst_node(state):
        project_context = get_project_context_from_state(state)

        tools = [get_tech_details, get_similar_projects, search_report]

        system_message = (
            "당신은 R&D 신규사업 예산 심의를 위한 **기술 트렌드 및 유사중복 검토 전문가**입니다. "
            "다음 관점에서 철저하게 분석하여 상세한 보고서를 작성하세요:\n\n"
            "1. **글로벌 기술 트렌드**: 해당 기술 분야의 글로벌 R&D 동향은 어떠한가? 선진국(미국, EU, 중국, 일본)의 투자 현황과 비교하여 본 사업의 선도성은?\n"
            "2. **경쟁국 대비 포지셔닝**: 해당 기술에서 한국의 현재 위치는? 기술 격차(Gap)는 어느 정도인가?\n"
            "3. **유사사업 중복성 분석**: 기존에 수행 완료되거나 진행 중인 국가 R&D 사업 중 유사한 사업이 있는가? 기술 영역, 연구 목표, 연구팀 구성 측면에서 중복 정도를 정량적으로 평가하세요.\n"
            "4. **중복 해소 방안**: 유사사업이 존재할 경우, 본 사업과의 차별화 전략과 시너지 창출 방안은?\n"
            "5. **적시성(Timeliness)**: 지금 이 시점에 이 사업을 시작하는 것이 적절한가? 너무 이르거나 너무 늦은 것은 아닌가?\n\n"
            "반드시 구체적인 근거를 기반으로 분석하고, 보고서 말미에 핵심 분석 결과를 정리한 "
            "Markdown 표를 첨부하세요."
            + get_review_criteria()
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages([
            (
                "system",
                "당신은 다른 전문가들과 협력하는 R&D 예산 심의 분석가입니다. "
                "제공된 도구를 사용하여 기술 트렌드와 유사사업 중복성을 분석하세요. "
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

        return {"messages": [result], "tech_trend_report": report}

    return tech_trend_analyst_node
