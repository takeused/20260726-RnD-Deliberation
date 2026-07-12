# 🎯 예상 질의 추출기 — 전체 심의 이력에서 예상 질의응답과 기획보고서 보완 권고를 구조화 추출
"""이 시뮬레이터의 최종 목적 산출물을 만드는 노드.

Con Reviewer의 공격 논리, 재정 검토 토론의 지적, 최종 결정의 조건 등
전체 심의 이력을 원석으로 삼아 (1) 심의위원 예상 질의 + 권장 답변 초안,
(2) 기획보고서 보완 권고를 도출한다.
"""

from langchain_core.prompts import ChatPromptTemplate

from rdagents.agents.schemas import (
    ReviewPreparationReport,
    render_anticipated_questions,
    render_improvements,
)
from rdagents.agents.utils.agent_utils import get_language_instruction, make_ai_message
from rdagents.agents.utils.review_criteria import get_review_criteria
from rdagents.agents.utils.structured import invoke_structured_model

_REPORT_SECTIONS = [
    ("tech_value_report", "기술 가치 분석"),
    ("tech_trend_report", "기술 트렌드/중복성 분석"),
    ("economic_report", "경제/재무 타당성 분석"),
    ("policy_report", "정책 부합성 분석"),
    ("feasibility_report", "수행체계 분석"),
    ("regulatory_report", "규제/윤리 검토"),
]


def create_question_extractor(llm):
    def question_extractor_node(state):
        system_message = (
            "당신은 R&D 예산 심의 대비를 총괄하는 **심의 대응 전략가**입니다.\n"
            "방금 종료된 모의 심의의 전체 이력(전문가 분석 보고서, 찬반 토론, 재정 검토 토론, 최종 결정)을 "
            "분석하여, 사업 담당자가 실제 심의장에 들어가기 전에 준비해야 할 두 가지를 도출하세요:\n\n"
            "1. **예상 질의 목록 (8~15개)**: 심의위원이 실제로 던질 법한 날카로운 질의. "
            "모의 심의에서 우려/보류 측과 재정 건전성 측이 공격한 지점이 실제 심의에서도 질의로 나옵니다. "
            "각 질의에 심의기준 분류, 심각도, 출제 근거, 권장 답변 초안을 붙이세요.\n"
            "2. **기획보고서 보완 권고 (5~10개)**: 심의 과정에서 드러난 보고서의 취약점과 "
            "구체적 수정·보강 방향.\n\n"
            "질의와 권고 모두 심각도 높은 순으로 정렬하고, 특히 최우선 심의기준 세 가지"
            "(정부지원 필요성, 기술개발의 중요성, 시급성)를 겨냥한 항목을 반드시 포함하세요.\n"
            + get_review_criteria()
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_message),
            ("human", "## 전문가 분석 보고서\n\n{reports}\n\n"
                      "## 전문위원회 찬반 토론\n\n{debate_history}\n\n"
                      "## 전문위원회 위원장 의견\n\n{review_plan}\n\n"
                      "## 재정 검토 토론\n\n{audit_history}\n\n"
                      "## 최종 심의 결정\n\n{final_decision}\n\n"
                      "위 심의 이력을 바탕으로 예상 질의 목록과 기획보고서 보완 권고를 도출해 주세요."),
        ])

        reports = []
        for key, name in _REPORT_SECTIONS:
            if state.get(key):
                reports.append(f"--- {name} ---\n{state[key]}")

        prompt_val = prompt.invoke({
            "reports": "\n\n".join(reports) or "분석 보고서 없음",
            "debate_history": state["review_debate_state"]["history"] or "토론 내역 없음",
            "review_plan": state.get("review_plan", "의견 없음"),
            "audit_history": state["audit_debate_state"]["history"] or "토론 내역 없음",
            "final_decision": state.get("final_review_decision", "결정 없음"),
        })

        call = invoke_structured_model(
            llm, ReviewPreparationReport, prompt_val, "Question Extractor"
        )
        report = call.model

        if report is not None:
            questions_md = render_anticipated_questions(report)
            improvements_md = render_improvements(report)
            report_json = report.model_dump_json()
        else:
            # 구조화 출력 실패 시 자유 텍스트로 폴백 (산출물이 비는 것 방지)
            free_text = llm.invoke(prompt_val).content
            questions_md = f"# 예상 질의응답 (자유 형식 폴백)\n\n{free_text}"
            improvements_md = "# 기획보고서 보완 권고\n\n예상 질의응답 문서를 참조하세요."
            report_json = ""

        return {
            "messages": [make_ai_message(questions_md, "QuestionExtractor", call.usage)],
            "anticipated_questions_md": questions_md,
            "improvement_recommendations_md": improvements_md,
            "preparation_report_json": report_json,
        }

    return question_extractor_node
