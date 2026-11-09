"""상태 초기화 및 그래프 인자 전달."""

from typing import Any

from rdagents.agents.utils.agent_states import AuditDebateState, ReviewDebateState


class Propagator:
    """초기 상태 생성기."""

    def __init__(self, max_recur_limit=150):
        self.max_recur_limit = max_recur_limit

    def create_initial_state(
        self,
        project_id: str,
        review_year: str,
        project_context: str = "",
        project_facts: dict[str, Any] | None = None,
        past_context: str = "",
        source_manifest: str = "",
        gate_profile: str = "",
        question_bank: str = "",
        precheck_md: str = "",
        precheck_brief: str = "",
        project_type: str = "혼합형",
        precheck_issues: list[dict] | None = None,
        max_debate_issues: int = 6,
        prompt_char_budget: int = 0,
        tool_result_char_budget: int = 0,
        max_analyst_tool_calls: int = 0,
        execution_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """그래프 초기 상태 생성."""
        return {
            "messages": [("human", f"사업 ID: {project_id} 심의 시작")],
            "project_id": project_id,
            "review_year": review_year,
            "project_context": project_context,
            "project_facts": project_facts or {},
            "past_context": past_context,
            "source_manifest": source_manifest,
            "gate_profile": gate_profile,
            "question_bank": question_bank,
            "precheck_md": precheck_md,
            "precheck_brief": precheck_brief,
            "project_type": project_type,
            "precheck_issues": precheck_issues or [],
            "issue_ledger": [],
            "max_debate_issues": max_debate_issues,
            "prompt_char_budget": prompt_char_budget,
            "tool_result_char_budget": tool_result_char_budget,
            "max_analyst_tool_calls": max_analyst_tool_calls,
            "rereview_comparison_md": "",
            "execution_metrics": [],
            "execution_metadata": execution_metadata or {},
            "review_debate_state": ReviewDebateState(
                {
                    "examiner_history": "",
                    "defender_history": "",
                    "history": "",
                    "current_response": "",
                    "judge_decision": "",
                    "count": 0,
                }
            ),
            "audit_debate_state": AuditDebateState(
                {
                    "aggressive_history": "",
                    "conservative_history": "",
                    "neutral_history": "",
                    "history": "",
                    "latest_speaker": "",
                    "current_aggressive_response": "",
                    "current_conservative_response": "",
                    "current_neutral_response": "",
                    "judge_decision": "",
                    "count": 0,
                }
            ),
            "domain_expert_report": "",
            "tech_value_report": "",
            "tech_trend_report": "",
            "economic_report": "",
            "policy_report": "",
            "feasibility_report": "",
            "regulatory_report": "",
            "review_plan": "",
            "budget_coordination_plan": "",
            "final_review_decision": "",
            "anticipated_questions_md": "",
            "preparation_report_json": "",
            "improvement_recommendations_md": "",
            "quality_scorecard_md": "",
            "uncertainty_report_md": "",
        }

    def get_graph_args(
        self, callbacks: list | None = None, thread_id: str | None = None
    ) -> dict[str, Any]:
        """그래프 호출 인자 생성."""
        config = {"recursion_limit": self.max_recur_limit}
        if callbacks:
            config["callbacks"] = callbacks
        if thread_id:
            config.setdefault("configurable", {})["thread_id"] = thread_id
        return {
            "stream_mode": "values",
            "config": config,
        }
