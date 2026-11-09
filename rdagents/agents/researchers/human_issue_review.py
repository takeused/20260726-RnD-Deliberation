# 🙋 사람 검토 (Human Issue Review) — 정책 판단이 필요한 쟁점을 공방 전에 사람에게 묻는다
"""쟁점 등록 뒤, 패널 공방 전에 그래프를 멈추고(LangGraph interrupt) 사람이 쟁점의 상정 여부를 정한다.

정부지원 필요성·정책·규제의 '상' 쟁점은 부처 정책 방향에 달려 있고, 출처를 확인하지 못한 '상' 쟁점은 코드 규칙상
공방에서 빠진다. 이런 쟁점만 골라 보여 주고, 사람은 '상정'(반드시 공방) 또는 '제외'를 고른다. 답하지 않은 쟁점은
코드 규칙대로 둔다. --human-review를 켰을 때만 그래프에 들어간다 (기본 실행은 그대로).
"""

from langgraph.types import interrupt

from rdagents.dataflows.issue_ledger import HUMAN_DROP, HUMAN_RAISE, apply_human_decisions, human_review_request

GUIDE = (f"쟁점마다 '{HUMAN_RAISE}'(반드시 공방에 올림) 또는 '{HUMAN_DROP}'(공방에서 뺌)를 고르세요. "
         "답하지 않은 쟁점은 코드 규칙(출처 검증·심각도 순)대로 둡니다.")


def create_human_issue_review():
    def human_issue_review_node(state):
        ledger = state.get("issue_ledger") or []
        request = human_review_request(ledger)
        if not request:
            return {}  # 물을 쟁점이 없으면 멈추지 않는다
        # 재개할 때 이 노드는 처음부터 다시 실행되고, interrupt가 사람의 답을 돌려준다
        decisions = interrupt({"type": "issue_review", "guide": GUIDE, "issues": request})
        return {"issue_ledger": apply_human_decisions(ledger, decisions)}

    return human_issue_review_node
