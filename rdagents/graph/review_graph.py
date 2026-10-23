"""메인 오케스트레이터 클래스 (TradingAgentsGraph 개조)."""

import json
import os
import sqlite3
from typing import Any, Callable
from uuid import uuid4

from langchain_core.runnables.config import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from rdagents.dataflows.plan_precheck import precheck_issues, run_precheck
from rdagents.dataflows.project_type import classify as classify_project_type
from rdagents.dataflows.project_type import render_section as render_type_section
from rdagents.default_config import DEFAULT_CONFIG
from rdagents.agents.utils.gate_profiles import get_gate_profile
from rdagents.dataflows.memory_log import append_memory, load_past_context
from rdagents.dataflows.question_bank import load_question_bank
from rdagents.dataflows.project_loader import (
    get_project_facts,
    get_report_text_and_name,
    get_source_lines,
    get_source_manifest,
    load_project,
    set_current_project,
    set_current_report,
)
from rdagents.dataflows.result_writer import save_results
from rdagents.graph.analyst_execution import build_analyst_execution_plan
from rdagents.graph.propagation import Propagator
from rdagents.graph.setup import setup_graph
from rdagents.llm_clients.factory import create_llm_client


HUMAN_REVIEW_PENDING = "사람 검토 대기"


class RDReviewGraph:
    """R&D 사업 예산 심의 시뮬레이터 워크플로우를 캡슐화합니다."""

    def __init__(self, config: dict | None = None, debug: bool = False):
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self.debug = debug

        # LLM 클라이언트 초기화 (TradingAgents 공용 팩토리 사용)
        self.deep_llm = create_llm_client(
            provider=self.config["llm_provider"],
            model=self.config["deep_think_llm"],
            base_url=self.config["backend_url"],
            **self._build_llm_kwargs(),
        ).get_llm()

        self.quick_llm = create_llm_client(
            provider=self.config["llm_provider"],
            model=self.config["quick_think_llm"],
            base_url=self.config["backend_url"],
            **self._build_llm_kwargs(),
        ).get_llm()

        # 분석가 실행 계획 구성
        self.analyst_plan = build_analyst_execution_plan(self.config["selected_analysts"])
        self.propagator = Propagator(max_recur_limit=self.config["max_recur_limit"])

        # 그래프 빌드
        builder = setup_graph(
            self.deep_llm,
            self.quick_llm,
            max_debate_rounds=self.config["max_debate_rounds"],
            max_audit_rounds=self.config["max_audit_rounds"],
            analyst_plan=self.analyst_plan,
            deep_model_name=self.config["deep_think_llm"],
            quick_model_name=self.config["quick_think_llm"],
            human_review=bool(self.config.get("human_review")),
        )

        self._checkpoint_conn = None
        checkpointer = None
        if self.config["checkpoint_enabled"]:
            checkpoint_path = os.path.abspath(self.config["checkpoint_path"])
            os.makedirs(os.path.dirname(checkpoint_path), exist_ok=True)
            self._checkpoint_conn = sqlite3.connect(checkpoint_path, check_same_thread=False)
            checkpointer = SqliteSaver(self._checkpoint_conn)
        elif self.config.get("human_review"):
            checkpointer = InMemorySaver()  # interrupt는 체크포인트가 있어야 멈췄다 이어 갈 수 있다 (같은 프로세스 안에서만)
        self.graph = builder.compile(checkpointer=checkpointer)

    def _build_llm_kwargs(self) -> dict:
        """프로바이더별 effort 인자명을 매핑하고 None 값은 전달하지 않는다."""
        provider = self.config["llm_provider"]
        kwargs = {}
        if self.config["temperature"] is not None:
            kwargs["temperature"] = self.config["temperature"]
        if self.config.get("llm_timeout") is not None:
            kwargs["timeout"] = self.config["llm_timeout"]
        # 프로바이더마다 사고 수준 인자명이 다름
        effort_map = {
            "google": ("thinking_level", self.config["google_thinking_level"]),
            "openai": ("reasoning_effort", self.config["openai_reasoning_effort"]),
            "azure": ("reasoning_effort", self.config["openai_reasoning_effort"]),
            "anthropic": ("effort", self.config["anthropic_effort"]),
            "groq": ("reasoning_effort", self.config["openai_reasoning_effort"]),
        }
        if provider in effort_map:
            key, value = effort_map[provider]
            if value is not None:
                kwargs[key] = value
        return kwargs

    def propagate(
        self,
        project_id: str | None = None,
        review_year: str = "2027",
        report_path: str | None = None,
        report_project_id: str | None = None,
        evidence_paths: list[str] | None = None,
        execution_id: str | None = None,
        human_reviewer: Callable[[dict], dict] | None = None,
    ) -> tuple[dict[str, Any], str]:
        """전체 심의 파이프라인을 실행합니다.

        project_id: sample_data의 구조화 JSON 모드.
        report_path: 기획보고서 원문(.md/.txt) 모드. 지정 시 project_id보다 우선.
        human_reviewer: human_review 설정에서 그래프가 멈추면 받은 쟁점 목록(dict)으로 사람의 판단을 돌려주는 함수.
            없으면 멈춘 채로 (상태, HUMAN_REVIEW_PENDING)을 돌려준다 — 같은 execution_id로 다시 부르면 이어 간다.
        """
        if report_path:
            project_id = set_current_report(
                report_path,
                report_project_id,
                max_bytes=self.config["max_report_bytes"],
                chunk_chars=self.config["report_chunk_chars"],
                retrieval_top_k=self.config["report_retrieval_top_k"],
                evidence_paths=evidence_paths,
            )
        elif project_id:
            set_current_project(project_id, self.config["sample_data_dir"])
        else:
            raise ValueError("project_id 또는 report_path 중 하나는 지정해야 합니다.")

        # 동일 사업의 이전 심의 이력 로드 (보완 전후 비교용)
        past_context = load_past_context(
            self.config["memory_log_path"],
            project_id,
            max_entries=self.config["max_memory_entries"],
            max_chars=self.config["max_memory_chars"],
        )

        # 사업 유형 판별 (규칙 기반): 모든 노드의 심의기준·평가 가중치·점검 항목·필수 질의가 이 결과를 따른다
        type_result = classify_project_type(
            get_source_lines() or self._sample_lines(project_id), self.config.get("project_type")
        )
        # 원문 모드면 심의 전에 규칙 기반 사전 점검 (LLM 호출 없음). 근거 파일(--evidence)도 함께 본다
        report_text, report_name = get_report_text_and_name()
        evidence = {name: "\n".join(lines) for name, lines in get_source_lines().items() if name != report_name}
        precheck_md, precheck_brief = run_precheck(report_text, report_name, type_result.project_type, evidence)
        # 판별 결과를 사전 점검 문서 맨 앞에 둔다 ('## 숫자 검산' 절 뒤에 두면 수치 표시의 계산값 근거에 섞임)
        precheck_md = render_type_section(type_result) + ("\n\n" + precheck_md if precheck_md else "")

        execution_id_provided = execution_id is not None
        execution_id = execution_id or uuid4().hex
        initial_state = self.propagator.create_initial_state(
            project_id=project_id,
            review_year=review_year,
            project_context=f"프로젝트 ID: {project_id} ({review_year}년도 예산 심의)",
            project_facts=get_project_facts(),
            past_context=past_context,
            source_manifest=get_source_manifest(),
            gate_profile=get_gate_profile(self.config["review_gate"]),
            question_bank=load_question_bank(
                [self.config["question_bank_seed_dir"], self.config["question_bank_dir"]]
            ),
            precheck_md=precheck_md,
            precheck_brief=precheck_brief,
            project_type=type_result.project_type,
            precheck_issues=precheck_issues(report_text, report_name, type_result.project_type, evidence=evidence),
            max_debate_issues=int(self.config.get("max_debate_issues") or 6),
            prompt_char_budget=int(self.config.get("prompt_char_budget") or 0),
            tool_result_char_budget=int(self.config.get("tool_result_char_budget") or 0),
            max_analyst_tool_calls=int(self.config.get("max_analyst_tool_calls") or 0),
            execution_metadata={
                "execution_id": execution_id,
                "provider": self.config["llm_provider"],
                "deep_model": self.config["deep_think_llm"],
                "quick_model": self.config["quick_think_llm"],
                "review_year": review_year,
                "review_gate": self.config["review_gate"],
                "project_type": type_result.project_type,
                "project_type_decided_by": type_result.decided_by,
                "checkpoint_enabled": self.config["checkpoint_enabled"],
                "checkpoint_path": self.config["checkpoint_path"] if self.config["checkpoint_enabled"] else None,
            },
        )

        graph_args = self.propagator.get_graph_args(
            thread_id=execution_id if self.config["checkpoint_enabled"] else None
        )
        
        # 사용자가 지정한 execution_id에 미완료 체크포인트가 있으면 입력 None으로
        # 중단 지점부터 재개한다 (초기 상태를 다시 넣으면 처음부터 재시작됨).
        stream_input: Any = initial_state
        if self._checkpoint_conn is not None and execution_id_provided:
            try:
                snapshot = self.graph.get_state({"configurable": {"thread_id": execution_id}})
            except Exception:
                snapshot = None
            if snapshot is not None and snapshot.next:
                stream_input = None
                print(
                    f"--> 체크포인트에서 재개: {execution_id} "
                    f"(다음 노드: {', '.join(snapshot.next)})"
                )

        # 스트리밍 모드로 실행 (stream_mode="values": 청크 자체가 전체 상태)
        final_state = None
        last_speaker = None

        if self.debug:
            print(f"=== R&D 심의 시뮬레이션 시작: {project_id} ===")

        while True:
            pending = None
            for s in self.graph.stream(stream_input, **graph_args):
                if "__interrupt__" in s:  # 사람 검토 노드가 멈춤 (상태 청크가 아님)
                    pending = s["__interrupt__"][0].value
                    continue
                final_state = s
                messages = s.get("messages") or []
                if messages:
                    speaker = getattr(messages[-1], "name", None)
                    if speaker and speaker != last_speaker:
                        last_speaker = speaker
                        print(f"--> [발언 완료] {speaker}")
            if pending is None:
                break
            if human_reviewer is None:
                print(f"--> 사람 검토 대기: 쟁점 {len(pending.get('issues', []))}개 (실행 번호 {execution_id})")
                return final_state or {}, HUMAN_REVIEW_PENDING
            stream_input = Command(resume=human_reviewer(pending))

        if final_state is None:
            return {}, "결정 도출 실패"

        decision = final_state.get("final_review_decision", "결정 도출 실패")

        # 심의 전 과정 저장 (과정 기록이 이 도구의 핵심 산출물)
        try:
            out_dir = save_results(final_state, self.config["results_dir"], project_id)
            final_state["saved_results_dir"] = str(out_dir)
        except Exception as exc:
            print(f"[경고] 결과 저장 실패: {exc}")

        # 심의 이력 메모리에 요약 기록 (다음 재심의 시 past_context로 주입)
        # 단, 구조화 출력 실패 폴백 결과는 기록하지 않는다 — 재심의 컨텍스트 오염 방지.
        if "구조화 출력 실패" in decision:
            print("[경고] 최종 결정이 폴백 결과이므로 심의 이력에 기록하지 않습니다.")
        else:
            try:
                key_concerns = ""
                try:
                    key_concerns = json.loads(final_state.get("review_plan", "")).get("key_concerns", "")
                except Exception:
                    pass
                append_memory(
                    self.config["memory_log_path"], project_id, review_year, decision, key_concerns
                )
            except Exception as exc:
                print(f"[경고] 심의 이력 기록 실패: {exc}")

        return final_state, decision

    def _sample_lines(self, project_id: str) -> dict[str, list[str]]:
        """구조화 샘플 JSON 모드의 판별 입력: JSON 본문 줄 (원문 모드에서는 쓰지 않음)."""
        try:
            data = load_project(project_id, self.config["sample_data_dir"])
        except (FileNotFoundError, ValueError):
            return {}
        return {f"{project_id}.json": json.dumps(data, ensure_ascii=False, indent=1).splitlines()}

    def close(self) -> None:
        """체크포인트 SQLite 연결을 닫는다."""
        if self._checkpoint_conn is not None:
            try:
                self._checkpoint_conn.close()
            finally:
                self._checkpoint_conn = None
