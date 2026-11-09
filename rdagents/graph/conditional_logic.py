"""그래프 흐름 제어를 위한 조건부 로직."""

from rdagents.agents.utils.agent_states import ReviewAgentState


class ConditionalLogic:
    """토론 라운드 및 툴 호출 조건 제어."""

    def __init__(self, max_debate_rounds=2, max_audit_rounds=1):
        self.max_debate_rounds = max_debate_rounds
        self.max_audit_rounds = max_audit_rounds

    def should_continue_domain_experts(self, state: ReviewAgentState):
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_domain_experts"
        return "Msg Clear Domain Experts"

    def should_continue_tech_value(self, state: ReviewAgentState):
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_tech_value"
        return "Msg Clear Tech Value"

    def should_continue_tech_trend(self, state: ReviewAgentState):
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_tech_trend"
        return "Msg Clear Tech Trend"

    def should_continue_economic(self, state: ReviewAgentState):
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_economic"
        return "Msg Clear Economic"

    def should_continue_policy(self, state: ReviewAgentState):
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_policy"
        return "Msg Clear Policy"

    def should_continue_feasibility(self, state: ReviewAgentState):
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_feasibility"
        return "Msg Clear Feasibility"

    def should_continue_regulatory(self, state: ReviewAgentState):
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_regulatory"
        return "Msg Clear Regulatory"

    def should_continue_review_debate(self, state: ReviewAgentState) -> str:
        """쟁점별 심사 공방 제어 (쟁점 하나 = 패널 질의 -> 발표자 방어).

        상정할 쟁점이 남았는지는 패널 노드가 쟁점 원장으로 판단해 current_response="Done"으로 알린다.
        count 상한은 원장이 비정상일 때 무한 루프를 막는 안전장치 (반드시 올릴 쟁점 +2까지 허용).
        """
        debate = state["review_debate_state"]
        hard_cap = 2 * (int(state.get("max_debate_issues") or 6) + 2)
        if debate["current_response"] == "Done" or debate["count"] >= hard_cap:
            return "Review Manager"
        if debate["current_response"] == "Examiner":
            return "Project Defender"
        return "Panel Examiner"

    def should_continue_audit_debate(self, state: ReviewAgentState) -> str:
        """재정 검토 3자 토론 라운드 제어."""
        # 3명이 번갈아가며 발언하므로 한 라운드당 count는 3 증가
        if state["audit_debate_state"]["count"] >= 3 * self.max_audit_rounds:
            return "Final Approver"
            
        latest = state["audit_debate_state"]["latest_speaker"]
        if latest == "Aggressive Auditor":
            return "Conservative Auditor"
        elif latest == "Conservative Auditor":
            return "Neutral Auditor"
        
        # 첫 시작이거나 Neutral 다음이면 Aggressive
        return "Aggressive Auditor"
