# 🎯 예상 질의 추출기 — 전체 심의 이력에서 예상 질의응답과 기획보고서 보완 권고를 구조화 추출
"""이 시뮬레이터의 최종 목적 산출물을 만드는 노드.

심사위원 패널의 공격 논리, 발표자가 방어에 실패한 지점, 재정 검토 토론의 지적 등
전체 심의 이력을 원석으로 삼아 (1) 심의위원 예상 질의 + 권장 답변 초안,
(2) 기획보고서 보완 권고를 도출한다.
"""

from langchain_core.prompts import ChatPromptTemplate

from rdagents.agents.schemas import (
    ReviewPreparationReport,
    render_anticipated_questions,
    render_improvements,
    require_type_questions,
)
from rdagents.agents.utils.agent_utils import _setting, clip_text, get_language_instruction, make_ai_message
from rdagents.agents.utils.review_criteria import get_review_criteria
from rdagents.agents.utils.structured import invoke_structured_model
from rdagents.dataflows.issue_ledger import ledger_summary


# 짧은 문맥 모드(prompt_char_budget > 0)에서는 출력도 줄인다. Groq 무료 등급 NDMI 실행에서 이 노드 출력이
# 2,988토큰으로 출력 상한(3,072)에 거의 닿았고, 앞선 시도에서는 JSON이 상한에서 잘려 실패했다.
_SHORT_OUTPUT_NOTE = (
    "\n\n**출력 길이 제한 (짧은 문맥 모드)**: 위의 개수 대신 예상 질의 5~7개, 보완 권고 3~5개만 작성하고, "
    "권장 답변 초안과 출제 근거는 각각 2문장 이내로 쓰세요."
)

# 사전 점검의 숫자 검산이 불일치를 찾으면 질의·권고에 반드시 넣게 한다. groq4 실행에서 패널은 표 1.1 불일치를
# 공방에서 따졌는데, 질의 개수를 줄이자 예상 질의·보완 권고에서는 빠졌다 (보고서의 가장 확실한 약점인데도)
_NUMBER_CHECK_NOTE = (
    "\n\n**숫자 검산 불일치 반영 (필수)**: 사전 점검의 '[숫자 검산]' 항목은 코드로 계산한 확정 오류 후보입니다. "
    "이를 다루는 예상 질의 1건 이상(심의기준: 예산 타당성 또는 해당 기준)과, 해당 표·수치를 원문과 대조해 "
    "바로잡으라는 보완 권고 1건 이상을 반드시 포함하고, 표 번호·적힌 값·계산 값을 그대로 적으세요. "
    "어느 값이 맞는지는 원자료를 봐야 알 수 있으므로, 권장 답변에서 한쪽을 정답으로 단정하지 말고 "
    "원자료 확인·정정 계획으로 답하세요."
)


def create_question_extractor(llm):
    def question_extractor_node(state):
        system_message = (
            "당신은 R&D 예산 심의 대비를 총괄하는 **심의 대응 전략가**입니다.\n"
            "방금 종료된 모의 심의의 전체 이력(전문가 분석 보고서, 심사 공방, 재정 검토 토론, 최종 결정)을 "
            "분석하여, 사업 담당자가 실제 심의장에 들어가기 전에 준비해야 할 두 가지를 도출하세요:\n\n"
            "1. **예상 질의 목록 (8~15개)**: 심의위원이 실제로 던질 법한 날카로운 질의. "
            "심사위원 패널이 공격했는데 발표자가 방어에 실패했거나 보완을 인정한 지점이 실제 심의에서도 질의로 나옵니다. "
            "각 질의에 심의기준 분류, 심각도, 출제 근거, 권장 답변 초안을 붙이세요.\n"
            "2. **기획보고서 보완 권고 (5~10개)**: 심의 과정에서 드러난 보고서의 취약점과 "
            "구체적 수정·보강 방향.\n\n"
            "질의와 권고 모두 심각도 높은 순으로 정렬하고, 특히 최우선 심의기준 세 가지"
            "(정부지원 필요성, 기술개발의 중요성, 시급성)를 겨냥한 항목과, 예산 규모·비목 산출 근거를 묻는 "
            "'예산 타당성' 질의를 반드시 1건 이상 포함하세요.\n"
            + ("공공임무형 사업이므로 수요기관 참여·실증 이후 제도화 경로·사업 종료 후 운영 재원을 묻는 "
               "'현장 적용·확산' 질의도 반드시 1건 이상 포함하세요.\n"
               if state.get("project_type") == "공공임무형" else "")
            + "권장 답변은 제출자료에서 확인한 사실만 단정하고, 확인하지 못한 항목은 가상의 기업·금액·MOU·해외사례를 만들지 말고 "
            "'제출자료로 확인하지 못했습니다. [확인 필요: 자료명]'로 답하세요.\n"
            + get_review_criteria(state.get("project_type"))
            + ("\n" + state["gate_profile"] if state.get("gate_profile") else "")
            + get_language_instruction()
            + _SHORT_OUTPUT_NOTE * bool(_setting(state, "prompt_char_budget", "RDAGENTS_PROMPT_CHAR_BUDGET"))
            + _NUMBER_CHECK_NOTE * ("[숫자 검산]" in (state.get("precheck_brief") or ""))
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_message),
            ("human", "## 기출·전형 질의 참고 (실제 심의 질의는 이런 패턴으로 나온다)\n\n{question_bank}\n\n"
                      "## 쟁점 원장 (사전 점검·숫자 검산·분석가 9명의 쟁점과 공방 결과, 코드 판정)\n\n{ledger}\n\n"
                      "## 전문위원회 위원장 의견\n\n{review_plan}\n\n"
                      "## 재정 검토 토론\n\n{audit_history}\n\n"
                      "## 최종 심의 결정\n\n{final_decision}\n\n"
                      "위 심의 이력을 바탕으로 예상 질의 목록과 기획보고서 보완 권고를 도출해 주세요."),
        ])

        # 사전 점검 요약·분석 보고서·공방 기록을 각각 잘라 읽는 대신 쟁점 원장 하나를 읽는다 (세 가지가 모두 들어 있고,
        # 방어에 실패한 쟁점이 앞에 온다. 실제 심의에서도 방어 실패·미상정 지적이 질의로 나온다)
        ledger = state.get("issue_ledger") or []
        prompt_val = prompt.invoke({
            "question_bank": clip_text(state.get("question_bank") or "", state, fraction=0.5) or "참고 자료 없음",
            "ledger": ledger_summary(ledger, width=60) if ledger else (state.get("precheck_brief") or "쟁점 원장 없음"),
            "review_plan": clip_text(state.get("review_plan") or "", state, fraction=0.5) or "의견 없음",
            "audit_history": clip_text(state["audit_debate_state"]["history"], state, fraction=0.5) or "토론 내역 없음",
            "final_decision": clip_text(state.get("final_review_decision") or "", state, fraction=0.5) or "결정 없음",
        })

        project_type = state.get("project_type")
        call = invoke_structured_model(
            llm, ReviewPreparationReport, prompt_val, "Question Extractor",
            post_validate=lambda report: require_type_questions(report, project_type),
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
