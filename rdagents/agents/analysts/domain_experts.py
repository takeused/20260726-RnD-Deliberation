"""🧪 분야 기술전문가 3명 — 사업 유형에 맞는 해당 분야 기술전문가가 기술 내용을 검토.

기능별 분석가 6명(기술가치·트렌드중복·경제재무·정책·수행체계·규제윤리)과 별도로 둔다. 실제 재난안전 R&D 심의는
해당 분야 기술전문가가 기술 내용을 따로 검토한다. Groq 무료 등급의 하루 토큰 한도 때문에 3명을 노드 하나에서
각자의 절로 쓰게 한다 (도구 호출·출력 상한은 다른 분석가와 같은 규칙).
"""

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from rdagents.agents.utils.agent_utils import (
    analyst_length_note,
    bind_analyst_tools,
    get_language_instruction,
    get_project_context_from_state,
)
from rdagents.agents.utils.committee import domain_experts
from rdagents.agents.utils.review_criteria import get_review_criteria
from rdagents.dataflows.project_loader import get_project_overview, get_tech_details, search_report


def create_domain_expert_panel(llm):
    def domain_expert_panel_node(state):
        project_context = get_project_context_from_state(state)
        tools = [get_project_overview, get_tech_details, search_report]
        experts = domain_experts(state.get("project_type"))
        roster = "\n".join(f"{i}. **{name}**: {focus}" for i, (name, focus) in enumerate(experts, 1))

        system_message = (
            "당신들은 R&D 신규사업 예산 심의에 참여한 **해당 분야 기술전문가 3명**입니다. "
            "기능별 분석(기술가치·중복성·경제성 등)은 다른 분석가가 하므로, 각자의 전문 분야에서 기술 내용 자체를 검토하세요.\n\n"
            f"{roster}\n\n"
            "보고서는 전문가마다 '## 전문가 이름' 절로 나눠 쓰고, 각 절에 다음을 담으세요:\n"
            "- 기술적으로 타당한 점과 의문점 (출처 줄을 붙여서)\n"
            "- 그 전문가가 심의에서 던질 핵심 질의 1~2개\n"
            "- 심각도(상·중·하)\n"
            "보고서 말미에 세 전문가의 핵심 의견을 정리한 Markdown 표를 첨부하세요."
            + get_review_criteria(state.get("project_type"))
            + get_language_instruction()
            + analyst_length_note(state)
        )

        prompt = ChatPromptTemplate.from_messages([
            (
                "system",
                "당신들은 다른 전문가들과 협력하는 R&D 예산 심의 기술전문가입니다. "
                "제공된 도구로 기획보고서의 기술 내용을 확인하세요. "
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

        model, messages = bind_analyst_tools(llm, tools, state)
        result = (prompt | model).invoke(messages)
        return {
            "messages": [result],
            "domain_expert_report": result.content if len(result.tool_calls) == 0 else "",
        }

    return domain_expert_panel_node
