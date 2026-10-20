# 🔎 심사위원 패널 (Panel Examiner) — 쟁점 원장에서 쟁점을 하나씩 골라 담당 위원이 질의
"""실제 심의장에는 사업을 옹호해 주는 위원이 없다. 위원 전원이 각자 전문 분야에서
공격하고, 옹호는 발표자(사업 담당자)의 몫이다. 이 노드는 그 위원 패널을 재현한다.

쟁점 선택(반드시 올릴 쟁점 -> 출처 검증된 쟁점 -> 심각도 순)과 질의 위원 배정은 코드가 하고,
LLM은 배정된 위원으로서 그 쟁점의 질의 문장만 쓴다. 이전에는 라운드마다 질의 3~5개를 자유 서술했고,
보고서 9개를 이어 붙여 한꺼번에 줄였기 때문에 패널이 실제로 읽은 분석은 앞부분 일부뿐이었다.
쟁점이 남지 않았거나 상한에 닿으면 LLM을 부르지 않고 공방을 끝낸다 (current_response="Done").
"""

from langchain_core.prompts import ChatPromptTemplate

from rdagents.agents.utils.agent_utils import clip_text, make_ai_message
from rdagents.agents.utils.committee import panel_roster
from rdagents.agents.utils.review_criteria import get_review_criteria
from rdagents.dataflows.issue_ledger import DEBATING, cited_lines, next_issue

DEFAULT_MAX_DEBATE_ISSUES = 6


def create_panel_examiner(llm):
    def panel_examiner_node(state):
        debate = state["review_debate_state"]
        ledger = [dict(item) for item in state.get("issue_ledger") or []]
        item = next_issue(ledger, int(state.get("max_debate_issues") or DEFAULT_MAX_DEBATE_ISSUES))
        if item is None:
            return {"review_debate_state": {**debate, "current_response": "Done"}}

        project_type = state.get("project_type")
        # 앞선 질의는 반복을 피하는 용도라 앞부분만 (질의를 길게 쓰면 쟁점마다 요청이 커짐)
        asked = [i["question"][:120] for i in ledger if i["question"]]
        system = (
            f"당신은 R&D 예산 심의 심사위원 패널({panel_roster(project_type)}) 중 **{item['member']}**입니다. "
            "주어진 쟁점 하나로 사업 발표자에게 날카로운 질의를 1~2문장으로 하세요. 실제 심의위원이 마이크를 잡고 "
            "던질 법한 완결된 질문이어야 하고, 앞선 질의를 반복하지 마세요. 근거 원문에 없는 수치를 새로 만들지 마세요. "
            "질의만 한국어로 쓰세요."
            + get_review_criteria(project_type)
            + ("\n" + state["gate_profile"] if state.get("gate_profile") else "")
        )
        prompt = ChatPromptTemplate.from_messages([
            ("system", system),
            ("human", "## 쟁점 #{id} ({criterion}, 심각도 {severity}, 출처: {origin})\n{issue}\n\n"
                      "## 근거 원문\n{evidence}\n\n## 앞선 질의\n{asked}"),
        ])
        response = llm.invoke(prompt.invoke({
            "id": item["id"], "criterion": item["criterion"], "severity": item["severity"],
            "origin": item["origin"], "issue": item["issue"],
            # PDF에서 바꾼 원문은 한 줄이 문단 전체일 수 있어 길이를 제한한다 (NDMI 추정: 패널 요청 10,137토큰, 413)
            "evidence": clip_text(cited_lines(item["cite"]), state)
                or "원문 근거 줄 없음 (보고서에 해당 내용이 없다는 지적일 수 있음)",
            "asked": "\n".join(f"- {q}" for q in asked) or "없음 (첫 질의)",
        }))
        question = response.content.strip()
        item.update(status=DEBATING, question=question)
        ledger = [item if i["id"] == item["id"] else i for i in ledger]

        line = (f"\n[심사위원 패널 · {item['member']}] (쟁점 #{item['id']}, {item['criterion']}, "
                f"심각도 {item['severity']}): {question}\n")
        return {
            "messages": [make_ai_message(question, "PanelExaminer", getattr(response, "usage_metadata", None))],
            "issue_ledger": ledger,
            "review_debate_state": {
                **debate,
                "examiner_history": debate["examiner_history"] + line,
                "history": debate["history"] + line,
                "current_response": "Examiner",
                "count": debate["count"] + 1,
            },
        }

    return panel_examiner_node
