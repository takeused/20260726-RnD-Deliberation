"""분석가 실행 계획 정의 (TradingAgents 패턴 개조)."""

from collections.abc import Iterable
from dataclasses import dataclass
from time import monotonic


@dataclass(frozen=True)
class AnalystNodeSpec:
    key: str
    agent_node: str
    clear_node: str
    tool_node: str
    report_key: str


@dataclass(frozen=True)
class AnalystExecutionPlan:
    specs: list[AnalystNodeSpec]


# R&D 심의 6인 분석가 정의
ANALYST_NODE_SPECS: dict[str, AnalystNodeSpec] = {
    "tech_value": AnalystNodeSpec(
        key="tech_value",
        agent_node="Tech Value Analyst",
        clear_node="Msg Clear Tech Value",
        tool_node="tools_tech_value",
        report_key="tech_value_report",
    ),
    "tech_trend": AnalystNodeSpec(
        key="tech_trend",
        agent_node="Tech Trend Analyst",
        clear_node="Msg Clear Tech Trend",
        tool_node="tools_tech_trend",
        report_key="tech_trend_report",
    ),
    "economic": AnalystNodeSpec(
        key="economic",
        agent_node="Economic Analyst",
        clear_node="Msg Clear Economic",
        tool_node="tools_economic",
        report_key="economic_report",
    ),
    "policy": AnalystNodeSpec(
        key="policy",
        agent_node="Policy Analyst",
        clear_node="Msg Clear Policy",
        tool_node="tools_policy",
        report_key="policy_report",
    ),
    "feasibility": AnalystNodeSpec(
        key="feasibility",
        agent_node="Feasibility Analyst",
        clear_node="Msg Clear Feasibility",
        tool_node="tools_feasibility",
        report_key="feasibility_report",
    ),
    "regulatory": AnalystNodeSpec(
        key="regulatory",
        agent_node="Regulatory Analyst",
        clear_node="Msg Clear Regulatory",
        tool_node="tools_regulatory",
        report_key="regulatory_report",
    ),
}


def build_analyst_execution_plan(selected_analysts: Iterable[str]) -> AnalystExecutionPlan:
    specs: list[AnalystNodeSpec] = []
    for analyst_key in selected_analysts:
        spec = ANALYST_NODE_SPECS.get(analyst_key)
        if spec is None:
            raise ValueError(f"unknown analyst key: {analyst_key}")
        specs.append(spec)

    if not specs:
        raise ValueError("at least one analyst must be selected")

    return AnalystExecutionPlan(specs=specs)


def get_initial_analyst_node(plan: AnalystExecutionPlan) -> str:
    return plan.specs[0].agent_node
