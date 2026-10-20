"""LangGraph 노드 및 엣지 설정 (TradingAgents 패턴 기반)."""

import json
from time import perf_counter

from langchain_core.messages import HumanMessage, RemoveMessage
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from rdagents.agents import (
    create_aggressive_auditor,
    create_budget_coordinator,
    create_issue_registrar,
    create_domain_expert_panel,
    create_panel_examiner,
    create_conservative_auditor,
    create_economic_analyst,
    create_feasibility_analyst,
    create_final_approver,
    create_neutral_auditor,
    create_policy_analyst,
    create_project_defender,
    create_question_extractor,
    create_quality_assessor,
    create_regulatory_analyst,
    create_review_manager,
    create_rereview_comparator,
    create_tech_trend_analyst,
    create_tech_value_analyst,
)
from rdagents.agents.utils.agent_states import ReviewAgentState
from rdagents.dataflows.output_validation import mark_texts
from rdagents.dataflows.project_loader import (
    get_budget_details,
    get_institution_info,
    get_policy_alignment,
    get_project_overview,
    get_regulatory_info,
    get_similar_projects,
    get_tech_details,
    search_report,
)
from rdagents.graph.analyst_execution import (
    ANALYST_NODE_SPECS,
    AnalystExecutionPlan,
    get_initial_analyst_node,
)
from rdagents.graph.conditional_logic import ConditionalLogic


def _clear_messages(state: ReviewAgentState):
    """메시지 히스토리 초기화 헬퍼.

    add_messages 리듀서는 빈 리스트를 no-op으로 처리하므로 RemoveMessage로
    기존 메시지를 명시적으로 삭제한다. 일부 프로바이더는 비시스템 메시지가
    하나 이상 필요하므로 진행용 placeholder를 남긴다.
    """
    removals = [RemoveMessage(id=m.id) for m in state["messages"] if m.id]
    return {"messages": removals + [HumanMessage(content="계속 진행하세요.")]}


_REPORT_KEYS = ("domain_expert_report", "tech_value_report", "tech_trend_report", "economic_report",
                "policy_report", "feasibility_report", "regulatory_report")
# 구조화 출력 JSON: 문자열 값에만 표시를 붙인다 (예상 질의 추출기가 최종 결정 JSON을 그대로 읽음)
_JSON_KEYS = ("review_plan", "budget_coordination_plan", "final_review_decision")
# 토론 상태의 글 필드. current_response("Examiner")·latest_speaker는 흐름 제어 값이라 건드리지 않는다.
_DEBATE_TEXT_KEYS = {
    "review_debate_state": ("history", "examiner_history", "defender_history", "judge_decision"),
    "audit_debate_state": ("history", "aggressive_history", "conservative_history", "neutral_history",
                           "current_aggressive_response", "current_conservative_response",
                           "current_neutral_response", "judge_decision"),
}


def _mark_json(raw: str, precheck_md: str) -> str:
    """JSON 문자열의 글 값에 표시를 붙인다. JSON이 아니면 그대로."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return raw
    if not isinstance(data, dict):
        return raw
    texts = {key: value for key, value in data.items() if isinstance(value, str) and value}
    if not texts:
        return raw
    marked = mark_texts(texts, precheck_md)
    if marked == texts:
        return raw
    return json.dumps({**data, **marked}, ensure_ascii=False)


def _mark_numbers(result: dict, state) -> dict:
    """노드가 쓴 글에 원문에 없는 수치 표시를 바로 붙인다 (뒤 노드가 지어낸 수치를 사실로 읽고 이어 쓰지 않게)."""
    precheck_md = state.get("precheck_md", "")
    result = {**result, **{key: _mark_json(result[key], precheck_md)
                           for key in _JSON_KEYS if isinstance(result.get(key), str)}}
    texts = {key: result[key] for key in _REPORT_KEYS if isinstance(result.get(key), str) and result[key]}
    for state_key, fields in _DEBATE_TEXT_KEYS.items():
        debate = result.get(state_key)
        if isinstance(debate, dict):
            texts |= {f"{state_key}.{f}": debate[f] for f in fields if isinstance(debate.get(f), str) and debate[f]}
    if not texts:
        return result
    marked = mark_texts(texts, precheck_md)
    out = {**result, **{key: marked[key] for key in _REPORT_KEYS if key in marked}}
    for state_key in _DEBATE_TEXT_KEYS:
        if isinstance(result.get(state_key), dict):
            prefix = f"{state_key}."
            out[state_key] = {**result[state_key],
                              **{k[len(prefix):]: v for k, v in marked.items() if k.startswith(prefix)}}
    return out


def _timed_node(node_name: str, node, model_name: str = "도구/로직"):
    """노드 실행시간과 응답 토큰 메타데이터를 상태에 누적한다."""
    def wrapped(state):
        started = perf_counter()
        result = node.invoke(state) if hasattr(node, "invoke") else node(state)
        elapsed = perf_counter() - started
        if isinstance(result, dict):
            result = _mark_numbers(result, state)
        input_tokens = output_tokens = total_tokens = 0
        for message in result.get("messages", []):
            usage = getattr(message, "usage_metadata", None) or {}
            input_tokens += usage.get("input_tokens", 0) or 0
            output_tokens += usage.get("output_tokens", 0) or 0
            total_tokens += usage.get("total_tokens", 0) or 0
        metric = {
            "node": node_name,
            "model": model_name,
            "elapsed_seconds": round(elapsed, 4),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens or input_tokens + output_tokens,
            "cost": None,
            "cost_note": "모델별 가격표 미설정으로 비용 계산 안 함",
        }
        result["execution_metrics"] = [*state.get("execution_metrics", []), metric]
        return result
    return wrapped


def setup_graph(
    deep_llm,
    quick_llm,
    max_debate_rounds: int,
    max_audit_rounds: int,
    analyst_plan: AnalystExecutionPlan,
    deep_model_name: str = "deep-model",
    quick_model_name: str = "quick-model",
) -> StateGraph:
    """R&D 심의 파이프라인 그래프 구성."""
    graph = StateGraph(ReviewAgentState)
    logic = ConditionalLogic(max_debate_rounds, max_audit_rounds)

    # 1. 노드 추가 -------------------------------------------------------------

    # 분석가 (Analyst) 노드 팩토리 맵
    analyst_factories = {
        "domain_experts": create_domain_expert_panel(deep_llm),
        "tech_value": create_tech_value_analyst(deep_llm),
        "tech_trend": create_tech_trend_analyst(deep_llm),
        "economic": create_economic_analyst(deep_llm),
        "policy": create_policy_analyst(deep_llm),
        "feasibility": create_feasibility_analyst(deep_llm),
        "regulatory": create_regulatory_analyst(deep_llm),
    }

    # 분석가 ToolNode 맵
    tools_map = {
        "domain_experts": [get_project_overview, get_tech_details, search_report],
        "tech_value": [get_project_overview, get_tech_details, search_report],
        "tech_trend": [get_similar_projects, get_tech_details, search_report],
        "economic": [get_budget_details, get_project_overview, search_report],
        "policy": [get_policy_alignment, get_project_overview, search_report],
        "feasibility": [get_institution_info, get_project_overview, search_report],
        "regulatory": [get_regulatory_info, get_project_overview, search_report],
    }

    # 선택된 분석가 노드 등록
    for spec in analyst_plan.specs:
        graph.add_node(spec.agent_node, _timed_node(spec.agent_node, analyst_factories[spec.key], deep_model_name))
        graph.add_node(spec.tool_node, _timed_node(spec.tool_node, ToolNode(tools_map[spec.key])))
        graph.add_node(spec.clear_node, _timed_node(spec.clear_node, _clear_messages))

    # 심사 공방 노드 등록 (quick_llm 및 deep_llm 조합)
    # 공방은 quick_llm, 종합 및 결정은 deep_llm 사용
    graph.add_node("Issue Registrar", _timed_node("Issue Registrar", create_issue_registrar(quick_llm), quick_model_name))
    graph.add_node("Panel Examiner", _timed_node("Panel Examiner", create_panel_examiner(quick_llm), quick_model_name))
    graph.add_node("Project Defender", _timed_node("Project Defender", create_project_defender(quick_llm), quick_model_name))
    graph.add_node("Review Manager", _timed_node("Review Manager", create_review_manager(deep_llm), deep_model_name))

    graph.add_node("Budget Coordinator", _timed_node("Budget Coordinator", create_budget_coordinator(deep_llm), deep_model_name))

    graph.add_node("Aggressive Auditor", _timed_node("Aggressive Auditor", create_aggressive_auditor(quick_llm), quick_model_name))
    graph.add_node("Conservative Auditor", _timed_node("Conservative Auditor", create_conservative_auditor(quick_llm), quick_model_name))
    graph.add_node("Neutral Auditor", _timed_node("Neutral Auditor", create_neutral_auditor(deep_llm), deep_model_name))

    graph.add_node("Final Approver", _timed_node("Final Approver", create_final_approver(deep_llm), deep_model_name))
    graph.add_node("Question Extractor", _timed_node("Question Extractor", create_question_extractor(deep_llm), deep_model_name))
    graph.add_node("Quality Assessor", _timed_node("Quality Assessor", create_quality_assessor(deep_llm), deep_model_name))
    graph.add_node("Re-review Comparator", _timed_node("Re-review Comparator", create_rereview_comparator(deep_llm), deep_model_name))


    # 2. 엣지 연결 -------------------------------------------------------------

    # 진입점: 첫 번째 분석가
    initial_node = get_initial_analyst_node(analyst_plan)
    graph.set_entry_point(initial_node)

    # 분석가 체이닝 (순차 실행)
    for i, spec in enumerate(analyst_plan.specs):
        is_last = (i == len(analyst_plan.specs) - 1)
        next_node = "Issue Registrar" if is_last else analyst_plan.specs[i + 1].agent_node
        
        # 조건부 로직 메서드 매핑
        cond_func = getattr(logic, f"should_continue_{spec.key}")
        
        # 에이전트 -> [툴 호출 | 클리어]
        graph.add_conditional_edges(
            spec.agent_node,
            cond_func,
            {spec.tool_node: spec.tool_node, spec.clear_node: spec.clear_node},
        )
        
        # 툴 호출 -> 다시 에이전트
        graph.add_edge(spec.tool_node, spec.agent_node)
        
        # 클리어 -> 다음 에이전트 (또는 토론 시작)
        graph.add_edge(spec.clear_node, next_node)


    # 쟁점 등록 -> 쟁점별 심사 공방 루프 (패널 질의 -> 발표자 방어, 쟁점이 끝나면 위원장)
    graph.add_edge("Issue Registrar", "Panel Examiner")
    graph.add_conditional_edges(
        "Panel Examiner",
        logic.should_continue_review_debate,
        {"Project Defender": "Project Defender", "Review Manager": "Review Manager"},
    )
    graph.add_conditional_edges(
        "Project Defender",
        logic.should_continue_review_debate,
        {"Panel Examiner": "Panel Examiner", "Review Manager": "Review Manager"},
    )

    # 위원장 -> 예산 조정관
    graph.add_edge("Review Manager", "Budget Coordinator")

    # 예산 조정관 -> 재정 검토 시작 (Aggressive 먼저)
    graph.add_edge("Budget Coordinator", "Aggressive Auditor")

    # 재정 검토 3자 루프
    graph.add_conditional_edges(
        "Aggressive Auditor",
        logic.should_continue_audit_debate,
        {"Conservative Auditor": "Conservative Auditor", "Final Approver": "Final Approver"}
    )
    graph.add_conditional_edges(
        "Conservative Auditor",
        logic.should_continue_audit_debate,
        {"Neutral Auditor": "Neutral Auditor", "Final Approver": "Final Approver"}
    )
    graph.add_conditional_edges(
        "Neutral Auditor",
        logic.should_continue_audit_debate,
        {"Aggressive Auditor": "Aggressive Auditor", "Final Approver": "Final Approver"}
    )

    # 최종 승인권자 -> 예상 질의 추출 -> 독립 품질평가 -> 종료
    graph.add_edge("Final Approver", "Question Extractor")
    graph.add_edge("Question Extractor", "Quality Assessor")
    graph.add_edge("Quality Assessor", "Re-review Comparator")
    graph.add_edge("Re-review Comparator", END)

    return graph
