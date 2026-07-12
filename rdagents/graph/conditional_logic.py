"""그래프 흐름 제어를 위한 조건부 로직."""

from rdagents.agents.utils.agent_states import ReviewAgentState


class ConditionalLogic:
    """토론 라운드 및 툴 호출 조건 제어."""

    def __init__(self, max_debate_rounds=2, max_audit_rounds=1):
        self.max_debate_rounds = max_debate_rounds
        self.max_audit_rounds = max_audit_rounds

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
        """심사 공방 라운드 제어 (패널 질의 -> 발표자 방어 = 1라운드)."""
        # count는 한 명이 발언할 때마다 1씩 증가, 라운드당 2 증가
        if state["review_debate_state"]["count"] >= 2 * self.max_debate_rounds:
            return "Review Manager"

        # 패널 질의 다음은 발표자 방어, 그 다음은 다시 패널
        if state["review_debate_state"]["current_response"] == "Examiner":
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
