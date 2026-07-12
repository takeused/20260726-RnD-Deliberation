# 🎤 사업 발표자 (Project Defender) — 심사위원 패널의 공격에 근거 기반으로 방어하는 사업 담당자
"""실제 심의에서 사용자가 서게 될 자리를 재현한다. 방어에 실패하거나 '보완하겠다'고
인정한 지점이 곧 예상 질의와 보완 권고의 원석이 된다."""

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


def create_project_defender(llm):
    def project_defender_node(state):
        system_message = (
            "당신은 이 R&D 사업의 **발표자(소관부처 사업 담당자)**입니다. "
            "심사위원 패널의 질의·지적에 대해 사업의 당위성을 방어해야 합니다.\n\n"
            "다음을 명심하세요:\n"
            "1. 패널의 질의 하나하나에 번호를 달아 빠짐없이 답변하세요.\n"
            "2. 방어는 반드시 분석 보고서와 사업계획서에 있는 근거로 하세요. "
            "자료에 없는 수치나 사실을 지어내는 것은 실제 심의에서 치명적입니다.\n"
            "3. 근거가 부족한 지적은 억지로 반박하지 말고 '타당한 지적이며 ~방식으로 보완하겠다'고 "
            "인정하세요. 인정과 보완 계획이 무리한 방어보다 신뢰를 얻습니다.\n"
            "4. 최우선 심의기준(정부지원 필요성, 중요성, 시급성)에 대한 공격에는 "
            "가장 공들여 답변하세요.\n"
            + get_review_criteria()
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_message),
            ("human", "다음은 사업에 대한 전문가 분석 보고서입니다 (당신의 방어 근거 자료):\n\n{reports}\n\n"
                      "심사위원 패널의 질의·지적 내역 (최신 발언에 집중하세요):\n{examiner_history}\n\n"
                      "당신의 이전 방어 발언:\n{defender_history}\n\n"
                      "패널의 최신 질의·지적에 조목조목 답변하세요."),
        ])

        reports = []
        for key, name in _REPORT_SECTIONS:
            if state.get(key):
                reports.append(f"--- {name} ---\n{state[key]}")

        prompt_val = prompt.invoke({
            "reports": "\n\n".join(reports) or "분석 보고서 없음",
            "examiner_history": state["review_debate_state"]["examiner_history"]
                or "질의가 없습니다.",
            "defender_history": state["review_debate_state"]["defender_history"]
                or "첫 답변입니다.",
        })

        response = llm.invoke(prompt_val)
        new_content = response.content

        new_history = state["review_debate_state"]["history"] + f"\n[사업 발표자]: {new_content}\n"
        new_defender_history = (
            state["review_debate_state"]["defender_history"] + f"\n[사업 발표자]: {new_content}\n"
        )

        return {
            "messages": [make_ai_message(new_content, "ProjectDefender",
                                         getattr(response, "usage_metadata", None))],
            "review_debate_state": {
                **state["review_debate_state"],
                "defender_history": new_defender_history,
                "history": new_history,
                "current_response": "Defender",
                "count": state["review_debate_state"]["count"] + 1,
            }
        }

    return project_defender_node
