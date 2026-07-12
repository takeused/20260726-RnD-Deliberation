# 🔎 심사위원 패널 (Panel Examiner) — 실제 심의위원처럼 보고서의 허점을 공격하는 질의·지적 생성
"""실제 심의장에는 사업을 옹호해 주는 위원이 없다. 위원 전원이 각자 전문 분야에서
공격하고, 옹호는 발표자(사업 담당자)의 몫이다. 이 노드는 그 위원 패널을 재현한다."""

from langchain_core.prompts import ChatPromptTemplate

from rdagents.agents.utils.agent_utils import get_language_instruction, make_ai_message
from rdagents.agents.utils.review_criteria import get_review_criteria

_REPORT_SECTIONS = [
    ("tech_value_report", "기술 가치 분석"),
    ("tech_trend_report", "기술 트렌드/중복성 분석"),
    ("economic_report", "경제/재무 타당성 분석"),
    ("policy_report", "정책 부합성 분석"),
    ("feasibility_report", "수행체계 분석"),
    ("regulatory_report", "규제/윤리 검토"),
]


def create_panel_examiner(llm):
    def panel_examiner_node(state):
        system_message = (
            "당신은 R&D 예산 심의의 **심사위원 패널**입니다. 기술·경제·정책·수행체계 분야의 "
            "위원들이 각자의 전문성으로 사업 발표자를 심문합니다.\n\n"
            "다음을 명심하세요:\n"
            "1. 이번 발언에서 서로 다른 각도의 날카로운 질의·지적을 3~5개 제시하세요. "
            "각 질의는 실제 심의위원이 마이크를 잡고 던질 법한 형태의 완결된 질문이어야 합니다.\n"
            "2. 최우선 심의기준(정부지원 필요성, 기술개발의 중요성, 시급성)을 겨냥한 공격을 "
            "반드시 포함하되, 이전 라운드에서 이미 던진 질의를 반복하지 마세요.\n"
            "3. 발표자의 이전 방어에 허점·회피·근거 부족이 있으면 그 지점을 재차 파고드세요.\n"
            "4. 예의는 갖추되 봐주지 마세요. 국가 예산이 걸린 심의입니다.\n"
            + get_review_criteria()
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_message),
            ("human", "다음은 전문가들의 사전 분석 보고서입니다:\n\n{reports}\n\n"
                      "발표자(사업 담당자)의 이전 방어 발언:\n{defender_history}\n\n"
                      "패널이 이전에 던진 질의·지적:\n{examiner_history}\n\n"
                      "위 내용을 바탕으로 이번 라운드의 심사 질의·지적을 제시하세요."),
        ])

        reports = []
        for key, name in _REPORT_SECTIONS:
            if state.get(key):
                reports.append(f"--- {name} ---\n{state[key]}")

        prompt_val = prompt.invoke({
            "reports": "\n\n".join(reports) or "분석 보고서 없음",
            "defender_history": state["review_debate_state"]["defender_history"]
                or "아직 발표자 발언이 없습니다. 보고서 자체의 허점을 공격하세요.",
            "examiner_history": state["review_debate_state"]["examiner_history"]
                or "첫 라운드입니다.",
        })

        response = llm.invoke(prompt_val)
        new_content = response.content

        new_history = state["review_debate_state"]["history"] + f"\n[심사위원 패널]: {new_content}\n"
        new_examiner_history = (
            state["review_debate_state"]["examiner_history"] + f"\n[심사위원 패널]: {new_content}\n"
        )

        return {
            "messages": [make_ai_message(new_content, "PanelExaminer",
                                         getattr(response, "usage_metadata", None))],
            "review_debate_state": {
                **state["review_debate_state"],
                "examiner_history": new_examiner_history,
                "history": new_history,
                "current_response": "Examiner",
                "count": state["review_debate_state"]["count"] + 1,
            }
        }

    return panel_examiner_node
