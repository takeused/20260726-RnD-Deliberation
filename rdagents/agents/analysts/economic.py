"""💰 경제/재무·공공가치 분석가 — 비용편익·비용효과, 예산 적정성, 공공편익 평가."""

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from rdagents.agents.utils.agent_utils import get_language_instruction, get_project_context_from_state
from rdagents.agents.utils.review_criteria import get_review_criteria
from rdagents.dataflows.project_loader import get_budget_details, get_project_overview, search_report


def create_economic_analyst(llm):
    def economic_analyst_node(state):
        project_context = get_project_context_from_state(state)
        tools = [get_budget_details, get_project_overview, search_report]

        system_message = (
            "당신은 R&D 신규사업 예산 심의를 위한 **경제/재무·공공가치 타당성 분석 전문가**입니다. "
            "먼저 사업이 산업·시장 창출형인지 공공임무·사회문제 해결형인지 구분하고, 사업 성격에 맞는 편익과 예산 타당성을 분석하세요:\n\n"
            "1. **편익 유형과 평가방법**: 산업형은 시장·산업 편익을, 재난안전 등 공공임무형은 피해회피액, "
            "인명피해 저감, 대응시간 단축, 서비스 지속성 등 공공편익을 평가하세요. 화폐화 근거가 충분할 때만 B/C를 제시하고, "
            "그렇지 않으면 비용효과성·다기준평가를 사용하세요.\n"
            "2. **예산 규모 적정성**: 요청 예산이 사업 목표 달성에 적정한가? 과다 또는 과소 요청은 아닌가?\n"
            "3. **연차별 예산 배분**: 사업 기간 대비 연평균 투자 규모가 합리적인가?\n"
            "4. **공공가치와 형평성**: 재난안전 사업이면 국민 안전, 취약계층 보호, 지역 안전격차 완화와 공공서비스 개선 효과는 구체적인가?\n"
            "5. **민간투자·산업 파급의 적용 가능성**: 시장수익이 기대되는 사업에만 민간 매칭, 고용·수출·산업 생태계를 평가하세요. "
            "공공재형 사업은 낮은 민간투자를 감점 사유로 삼지 마세요.\n"
            "6. **재원 조달 및 재정 부담**: 중장기 재정 부담은 감당 가능한 수준인가?\n\n"
            "가용한 수치와 지표를 활용하되 확인되지 않은 편익을 임의로 화폐화하지 말고, Markdown 표로 핵심 결과를 정리하세요."
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
