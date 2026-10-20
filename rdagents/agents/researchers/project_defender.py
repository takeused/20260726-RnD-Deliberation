# 🎤 사업 발표자 (Project Defender) — 쟁점 하나에 제출자료 근거로만 답하는 사업 담당자
"""실제 심의에서 사용자가 서게 될 자리를 재현한다. 방어에 실패하거나 '보완하겠다'고
인정한 지점이 곧 예상 질의와 보완 권고의 원석이 된다.

발표자는 구조화 출력으로 답한다 (근거 있음/없음, 답변, 출처, 인용 구절). 실제 심의에서도 발표자는 제출자료로만
답할 수 있다. 코드가 출처·인용 구절을 원문과 대조하고, 답변에 원문에 없는 수치가 있으면 방어 실패로 본다.
NDMI groq7에서 자유 서술 발표자가 피해 저감액·민간 투자액·평균 피해액·비목표(총사업비 2,800억 원)를
원문 없이 지어내 방어했다.
"""

from langchain_core.prompts import ChatPromptTemplate

from rdagents.agents.schemas import DefenseAnswer
from rdagents.agents.utils.agent_utils import clip_text, get_language_instruction, make_ai_message
from rdagents.agents.utils.structured import invoke_structured_model
from rdagents.dataflows.issue_ledger import DEBATING, DEFENDED, FAILED, cited_lines, verify_citation
from rdagents.dataflows.output_validation import mark_texts


def judge_defense(answer: DefenseAnswer, precheck_md: str = "") -> tuple[str, str]:
    """(결과, 사유). 근거를 인정하지 않았고, 출처·인용이 원문과 맞고, 원문에 없는 수치가 없을 때만 방어 성공."""
    if not answer.supported:
        return FAILED, "발표자가 제출자료 근거 없음을 인정"
    ok, note = verify_citation(answer.cite, answer.quote, require_quote=True)
    if not ok:
        return FAILED, f"방어 출처 불일치: {note}"
    marked = mark_texts({"answer": answer.answer}, precheck_md)["answer"]
    if "⚠️" in marked:
        return FAILED, "원문에 없는 수치로 방어: " + marked[marked.index("⚠️"):].split("]")[0].split(": ", 1)[-1]
    return DEFENDED, f"원문 대조 일치 {answer.cite}"


def create_project_defender(llm):
    def project_defender_node(state):
        debate = state["review_debate_state"]
        ledger = [dict(item) for item in state.get("issue_ledger") or []]
        item = next((i for i in ledger if i["status"] == DEBATING), None)
        if item is None:  # 원장 없이 호출되면 공방 종료 (그래프 흐름상 오지 않음)
            return {"review_debate_state": {**debate, "current_response": "Done"}}

        from rdagents.dataflows.project_loader import search_report

        system = (
            "당신은 이 R&D 사업의 **발표자(소관부처 사업 담당자)**입니다. 심사위원의 질의 하나에 답하세요.\n"
            "1. 방어는 아래 '근거 원문'에 있는 내용으로만 하세요. 근거가 되는 줄의 [출처: 파일명 L시작-L끝]을 cite에, "
            "그 줄에 실제로 있는 구절을 quote에 그대로 복사하세요.\n"
            "2. 근거 원문에 방어 근거가 없으면 supported=false로 하고 '제출자료로 확인하지 못했습니다'와 보완 계획을 답하세요. "
            "억지 방어보다 인정과 보완 계획이 신뢰를 얻습니다.\n"
            "3. 근거 원문에 없는 수치(피해액·투자액·예산 내역 등)를 만들어 답하면 방어 실패로 처리됩니다."
            + get_language_instruction()
        )
        prompt = ChatPromptTemplate.from_messages([
            ("system", system),
            ("human", "## 질의 ({member}, 쟁점 #{id})\n{question}\n\n## 근거 원문\n{evidence}"),
        ])
        evidence = "\n\n".join(part for part in (
            clip_text(cited_lines(item["cite"], around=2), state),
            clip_text(search_report.invoke({"query": item["issue"]}), state, fraction=1.5),
        ) if part)
        prompt_val = prompt.invoke({"member": item["member"], "id": item["id"], "question": item["question"],
                                    "evidence": evidence or "근거 원문 없음"})
        call = invoke_structured_model(llm, DefenseAnswer, prompt_val, "Project Defender")
        answer = call.model or DefenseAnswer(supported=False, answer="구조화 답변 실패 — 방어 근거를 제시하지 못함")
        status, note = judge_defense(answer, state.get("precheck_md", ""))
        item.update(status=status, defense=answer.answer, defense_cite=answer.cite, defense_note=note)
        ledger = [item if i["id"] == item["id"] else i for i in ledger]

        line = (f"\n[사업 발표자] (쟁점 #{item['id']}): {answer.answer} {answer.cite}".rstrip()
                + f"\n  → 판정: {status} ({note})\n")
        return {
            "messages": [make_ai_message(answer.answer, "ProjectDefender", call.usage)],
            "issue_ledger": ledger,
            "review_debate_state": {
                **debate,
                "defender_history": debate["defender_history"] + line,
                "history": debate["history"] + line,
                "current_response": "Defender",
                "count": debate["count"] + 1,
            },
        }

    return project_defender_node
