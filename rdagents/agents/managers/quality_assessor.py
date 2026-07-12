"""심의 결과를 정량화하고 불확실성·반대 근거를 별도로 드러내는 품질 평가 노드."""

from langchain_core.prompts import ChatPromptTemplate

from rdagents.agents.schemas import (
    DecisionQualityReport,
    quality_weights_text,
    render_quality_scorecard,
    render_uncertainty_report,
)
from rdagents.agents.utils.agent_utils import get_language_instruction, make_ai_message
from rdagents.agents.utils.structured import invoke_structured_model


_REPORT_KEYS = (
    "tech_value_report", "tech_trend_report", "economic_report",
    "policy_report", "feasibility_report", "regulatory_report",
)


def create_quality_assessor(llm):
    def quality_assessor_node(state):
        system = (
            "당신은 최종 승인 결정과 독립적으로 심의 품질을 감사하는 평가자입니다. "
            f"{quality_weights_text()} 기준으로 0~100점을 부여하세요. "
            "각 점수와 별도로 근거 충분성 신뢰도를 평가하고, 반드시 에이전트 간 불일치, 결론에 반하는 근거, "
            "추가 확인 자료를 찾아야 합니다. 사업보고서 주장과 독립 외부 근거를 구분하고, 외부 근거가 없으면 "
            "검증되지 않았다고 명시하세요. 출처 표기가 있는 주장에는 해당 표기를 보존하세요."
            + get_language_instruction()
        )
        prompt = ChatPromptTemplate.from_messages([
            ("system", system),
            ("human", "## 입력 출처\n{sources}\n\n## 전문 분석\n{reports}\n\n"
                      "## 찬반 토론\n{debate}\n\n## 전문위원회 의견\n{review_plan}\n\n"
                      "## 재정 검토\n{audit}\n\n## 최종 결정\n{decision}\n\n"
                      "최종 결정을 그대로 정당화하지 말고 독립적으로 품질을 평가하세요."),
        ])
        reports = "\n\n".join(state.get(key, "") for key in _REPORT_KEYS if state.get(key))
        prompt_val = prompt.invoke({
            "sources": state.get("source_manifest") or "출처 정보 없음",
            "reports": reports or "전문 분석 없음",
            "debate": state["review_debate_state"]["history"] or "토론 없음",
            "review_plan": state.get("review_plan") or "의견 없음",
            "audit": state["audit_debate_state"]["history"] or "재정 검토 없음",
            "decision": state.get("final_review_decision") or "최종 결정 없음",
        })
        call = invoke_structured_model(llm, DecisionQualityReport, prompt_val, "Quality Assessor")
        report = call.model
        if report is None:
            free_text = llm.invoke(prompt_val).content
            report = DecisionQualityReport(
                missing_evidence=[f"구조화 품질평가 실패. 자유 형식 결과: {free_text}"],
                external_evidence_assessment="구조화 평가 실패로 외부 근거 판정 불가",
            )
        scorecard = render_quality_scorecard(report)
        uncertainty = render_uncertainty_report(report)
        return {
            "messages": [make_ai_message(scorecard, "QualityAssessor", call.usage)],
            "quality_scorecard_md": scorecard,
            "uncertainty_report_md": uncertainty,
        }

    return quality_assessor_node
