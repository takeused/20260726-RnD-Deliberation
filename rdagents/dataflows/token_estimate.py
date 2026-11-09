"""실행 전 토큰 추정: LLM 대신 '재기만 하는 가짜 LLM'으로 심의 그래프를 한 번 돌려 노드별 요청 크기를 센다.

API를 부르지 않으므로 비용·한도 소모가 없다. 실제 보고서·프롬프트·도구 결과·문맥 예산(clip)을 그대로
거치므로 입력 크기는 실제와 가깝다. 출력 크기는 모델이 정하므로 과거 실행에서 관측한 값을 가정으로 쓴다.

알려 주는 것:
  - 요청 하나가 분당 토큰 한도(Groq 무료 8,000)를 넘는지 (넘으면 413으로 멈춤)
  - 심의 1회(또는 체크포인트에서 이어서 실행할 남은 부분)가 하루 한도(Groq 무료 20만) 안에 들어가는지
"""

from __future__ import annotations

import contextlib
import enum
import io
import json
import os
import re
import sqlite3
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool

# 한국어 위주 프롬프트의 글자 수 -> 토큰 수 환산. NDMI 보고서 Groq 실행(gpt-oss-120b)에서 분석가 4명의
# 같은 요청을 비교하니 1.68~1.86자/토큰 -> 토큰을 약간 많게 세는 1.75. 다른 모델·언어에서는 달라진다.
CHARS_PER_TOKEN = 1.75
# 출력 토큰 가정 (같은 실행의 관측값). gpt-oss는 추론 토큰도 출력에 포함된다
OUT_TOOL_TURN = 150        # 도구를 부르는 턴: 36~481, 대개 100 안팎
OUT_REPORT = 3000          # 분석가 보고서 턴: 2,979~3,072 (3,072는 출력 상한에 걸려 잘린 것)
OUT_STRUCTURED = 1500      # 구조화 출력(의견·예산안·결정·예상 질의): 관측 전이라 보수적 가정
OUT_TEXT = 1500            # 공방·토론 발언
RETRY_MARK = "직전 출력이 스키마 검증에 실패했습니다"
# Groq는 '입력 + 출력 상한'을 요청 크기로 보고 분당 한도와 비교한다. 출력 상한을 주지 않으면 3,072(관측값).
# NDMI 실행에서 예상 질의 단계가 입력 약 4,970토큰인데 "Requested 8041"로 413을 받았다.
OUTPUT_CAP = 3072
TPM_MARGIN = 0.9           # 글자 수 환산 오차(~10%)를 감안해 한도의 90%를 넘으면 주의


@dataclass
class Call:
    node: str
    kind: str              # 도구 턴 / 보고서 / 구조화 / 발언
    input_chars: int
    output_tokens: int
    retry: bool = False

    @property
    def input_tokens(self) -> int:
        return round(self.input_chars / CHARS_PER_TOKEN)

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class Estimate:
    calls: list[Call] = field(default_factory=list)
    skipped: list[Call] = field(default_factory=list)       # 체크포인트에서 이미 끝난 부분
    used_tokens: int = 0                                     # 체크포인트에 기록된 실제 사용량


def _current_node() -> str:
    try:
        from langgraph.config import get_config

        return get_config().get("metadata", {}).get("langgraph_node", "?")
    except Exception:
        return "?"


def _chars(prompt: Any) -> int:
    if hasattr(prompt, "to_messages"):
        prompt = prompt.to_messages()
    if isinstance(prompt, list):
        total = 0
        for m in prompt:
            content = m.content if isinstance(m, BaseMessage) else m
            total += len(content if isinstance(content, str) else json.dumps(content, ensure_ascii=False))
            for call in getattr(m, "tool_calls", None) or []:
                total += len(json.dumps(call.get("args", {}), ensure_ascii=False)) + len(call["name"])
        return total
    return len(str(prompt))


def _filler(tokens: int) -> str:
    """출력 토큰만큼의 한국어 글. 다음 단계 프롬프트에 실제와 비슷한 길이로 들어가게 한다."""
    sentence = "제출 자료의 근거와 한계를 검토한 결과를 정리합니다. "
    n = int(tokens * CHARS_PER_TOKEN)
    return (sentence * (n // len(sentence) + 1))[:n]


def _usage(call: Call) -> dict:
    return {"input_tokens": call.input_tokens, "output_tokens": call.output_tokens, "total_tokens": call.total}


def sample_instance(schema):
    """Pydantic 스키마의 필수 필드를 타입별 기본값으로 채운, 검증을 통과하는 인스턴스 (테스트와 추정기 공용)."""
    values = {}
    for name, f in schema.model_fields.items():
        if not f.is_required():
            continue
        ann = f.annotation
        if isinstance(ann, type) and issubclass(ann, enum.Enum):
            values[name] = list(ann)[0]
        elif ann is float:
            values[name] = 100.0
        elif ann is int:
            values[name] = 1
        elif ann is str:
            values[name] = f"[가짜 {name}]"
        else:
            try:
                values[name] = ann()
            except Exception:
                values[name] = f"[가짜 {name}]"
    if schema.__name__ == "BudgetProposal":
        values["proposed_budget_billion"] = values["original_budget_billion"]
    elif schema.__name__ == "FinalDecision":
        # 가짜 발표자는 근거 없음을 인정해 모든 쟁점이 방어 실패 -> '승인'은 쟁점 원장 정합성 검증에서 거부되므로 조건부승인
        values["approved_budget_billion"] = 100.0
        values["verdict"] = "조건부승인"
        values["conditions"] = "[가짜 이행 조건]"
    elif schema.__name__ == "QuestionVerificationReport":
        from rdagents.agents.schemas import MatchLevel, QuestionMatch

        values["matches"] = [
            QuestionMatch(actual_question="[실제 질의1]", match_level=MatchLevel.HIT,
                          matched_prediction="[예측 질의1]", note="논점 일치"),
            QuestionMatch(actual_question="[실제 질의2]", match_level=MatchLevel.MISS,
                          matched_prediction=None, note="예측에 없음"),
        ]
        values["missed_topics_summary"] = "[가짜 미적중 요약]"
    elif schema.__name__ == "IssueRegister":
        from rdagents.agents.schemas import CriterionTag, RegisteredIssue, Severity

        values["issues"] = [RegisteredIssue(issue=f"[가짜 쟁점: {c.value}]", criterion=c, severity=Severity.HIGH,
                                            source_report="경제/재무 타당성 분석")
                            for c in (CriterionTag.GOV_SUPPORT, CriterionTag.URGENCY, CriterionTag.BUDGET)]
    elif schema.__name__ == "ReviewPreparationReport":
        from rdagents.agents.schemas import AnticipatedQuestion, CriterionTag, ImprovementItem, Severity

        def q(criterion):
            return AnticipatedQuestion(question="[가짜 질의]", criterion=criterion, severity=Severity.HIGH,
                                       basis="[가짜 근거]", suggested_answer="[가짜 답변]")

        values["questions"] = [q(CriterionTag.GOV_SUPPORT), q(CriterionTag.IMPORTANCE),
                               q(CriterionTag.URGENCY), q(CriterionTag.BUDGET), q(CriterionTag.FIELD)]
        values["improvements"] = [ImprovementItem(weakness="[가짜 취약점]", severity=Severity.MEDIUM,
                                                  recommendation="[가짜 권고]") for _ in range(3)]
    return schema(**values)


class MeasuringLLM:
    """bind_tools / with_structured_output / invoke를 흉내 내며 요청 크기만 기록하는 가짜 LLM."""

    QUERIES = ["예산", "필요성", "기술", "성과", "추진체계"]

    def __init__(self, tool_cap: int):
        self.tool_cap = tool_cap
        self.calls: list[Call] = []

    def _record(self, kind: str, chars: int, out: int, retry: bool = False) -> Call:
        call = Call(_current_node(), kind, chars, out, retry)
        self.calls.append(call)
        return call

    def bind_tools(self, tools, **_kwargs):
        schema_chars = sum(len(json.dumps(convert_to_openai_tool(t), ensure_ascii=False)) for t in tools)
        limit = self.tool_cap or len(tools)

        def run(prompt):
            messages = prompt.to_messages() if hasattr(prompt, "to_messages") else prompt
            used = sum(isinstance(m, ToolMessage) for m in messages)
            chars = _chars(prompt) + schema_chars
            if used < limit:  # 도구를 하나씩 차례로 부름 (실제 모델도 대개 한 턴에 하나)
                tool = tools[used % len(tools)]
                name = getattr(tool, "name", None) or tool.__name__
                args = {"query": self.QUERIES[used % len(self.QUERIES)]} if name == "search_report" else {}
                call = self._record("도구 턴", chars, OUT_TOOL_TURN)
                return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"est-{len(self.calls)}"}],
                                 usage_metadata=_usage(call))
            call = self._record("보고서", chars, OUT_REPORT)
            return AIMessage(content=_filler(OUT_REPORT), usage_metadata=_usage(call))

        return run

    def with_structured_output(self, schema, include_raw=False, **_kwargs):
        llm = self
        schema_chars = len(json.dumps(schema.model_json_schema(), ensure_ascii=False))

        class Structured:
            def invoke(self, prompt):
                chars = _chars(prompt)
                messages = prompt.to_messages() if hasattr(prompt, "to_messages") else prompt
                text = "\n".join(str(getattr(m, "content", "")) for m in (messages if isinstance(messages, list) else []))
                call = llm._record("구조화", chars + schema_chars, OUT_STRUCTURED, retry=RETRY_MARK in text)
                instance = sample_instance(schema)
                # 최종 결정은 앞 단계 예산안과 금액이 같아야 검증을 통과한다 (아니면 재시도·폴백까지 세게 됨)
                if schema.__name__ == "FinalDecision" and (
                        m := re.search(r'"proposed_budget_billion"\s*:\s*([0-9.]+)', text)):
                    instance.approved_budget_billion = float(m.group(1))
                if include_raw:
                    return {"raw": AIMessage(content="", usage_metadata=_usage(call)), "parsed": instance,
                            "parsing_error": None}
                return instance

        return Structured()

    def __call__(self, prompt):  # `prompt | llm`에 바로 쓸 수 있게 (도구 없이 부르는 경로)
        return self.invoke(prompt)

    def invoke(self, prompt, *_args, **_kwargs):
        # 도구 호출 상한 뒤의 분석가는 도구 없이 이 경로로 보고서를 쓴다
        node = _current_node()
        kind, out = ("보고서", OUT_REPORT) if node.endswith("Analyst") else ("발언", OUT_TEXT)
        call = self._record(kind, _chars(prompt), out)
        return AIMessage(content=_filler(out), usage_metadata=_usage(call))


class _Client:
    def __init__(self, llm):
        self._llm = llm

    def get_llm(self):
        return self._llm


def checkpoint_progress(checkpoint_path: str, execution_id: str) -> tuple[dict | None, int]:
    """(체크포인트 상태, 지금까지 실제 사용 토큰). 없으면 (None, 0)."""
    if not os.path.exists(checkpoint_path):
        return None, 0
    from langgraph.checkpoint.sqlite import SqliteSaver

    conn = sqlite3.connect(checkpoint_path, check_same_thread=False)
    try:
        saved = SqliteSaver(conn).get_tuple({"configurable": {"thread_id": execution_id}})
    finally:
        conn.close()
    if saved is None:
        return None, 0
    state = saved.checkpoint["channel_values"]
    used = sum(m.get("total_tokens", 0) or 0 for m in state.get("execution_metrics", []))
    return state, used


def _done(calls: list[Call], state: dict | None) -> list[bool]:
    """체크포인트에서 이미 끝난 호출인지. 보고서가 저장된 분석가는 전부, 다른 노드는 실행된 횟수만큼 앞에서부터."""
    if not state:
        return [False] * len(calls)
    from rdagents.graph.analyst_execution import ANALYST_NODE_SPECS

    finished_analysts = {s.agent_node for s in ANALYST_NODE_SPECS.values() if state.get(s.report_key)}
    ran = Counter(m["node"] for m in state.get("execution_metrics", []) if m.get("total_tokens"))
    seen: Counter = Counter()
    flags = []
    for c in calls:
        if c.node.endswith("Analyst"):
            flags.append(c.node in finished_analysts)
        else:
            seen[c.node] += 1
            flags.append(seen[c.node] <= ran[c.node])
    return flags


def estimate(config: dict, propagate_kwargs: dict, execution_id: str | None = None) -> Estimate:
    """가짜 LLM으로 그래프를 한 번 실행해 호출별 크기를 센다. 결과·기억 파일은 임시 폴더에 쓰고 버린다."""
    import rdagents.graph.review_graph as rg

    from rdagents.agents.utils.agent_utils import _setting

    tool_cap = _setting(config, "max_analyst_tool_calls", "RDAGENTS_MAX_ANALYST_TOOL_CALLS")
    llm = MeasuringLLM(tool_cap)
    original = rg.create_llm_client
    rg.create_llm_client = lambda **_kw: _Client(llm)
    try:
        with tempfile.TemporaryDirectory(prefix="rdagents_estimate_") as tmp:
            graph = rg.RDReviewGraph(config={
                **config, "checkpoint_enabled": False,
                "results_dir": os.path.join(tmp, "results"),
                "memory_log_path": os.path.join(tmp, "memory.md"),
            })
            try:
                with contextlib.redirect_stdout(io.StringIO()):  # 발언 진행 표시는 숨김
                    graph.propagate(**propagate_kwargs)
            finally:
                graph.close()
    finally:
        rg.create_llm_client = original

    state, used = (None, 0)
    if execution_id:
        state, used = checkpoint_progress(os.path.abspath(config["checkpoint_path"]), execution_id)
    result = Estimate(used_tokens=used)
    for call, done in zip(llm.calls, _done(llm.calls, state)):
        (result.skipped if done else result.calls).append(call)
    return result


def render(est: Estimate, tpm: int, tpd: int) -> str:
    calls = [c for c in est.calls if not c.retry]
    total = sum(c.total for c in calls)
    biggest = max(calls, key=lambda c: c.input_tokens, default=None)

    def request(c: Call) -> int:
        return c.input_tokens + OUTPUT_CAP

    def mark(tokens: int) -> str:
        return " ⛔" if tokens > tpm else " ⚠️" if tokens > tpm * TPM_MARGIN else ""
    by_node: dict[str, list[Call]] = {}
    for c in calls:
        by_node.setdefault(c.node, []).append(c)
    lines = ["# 실행 전 토큰 추정 (API 호출 없음)", ""]
    if est.skipped or est.used_tokens:
        lines.append(f"체크포인트: 이미 끝난 호출 {len(est.skipped)}건, 지금까지 실제 사용 {est.used_tokens:,}토큰. "
                     "아래는 이어서 실행할 남은 부분입니다.")
        lines.append("")
    lines += ["| 노드 | 호출 | 가장 큰 입력 | 요청 크기(입력+출력 상한) | 합계(입력+출력) |", "|---|---|---|---|---|"]
    for node, cs in by_node.items():
        top = max(c.input_tokens for c in cs)
        lines.append(f"| {node} | {len(cs)} | {top:,} | {top + OUTPUT_CAP:,}{mark(top + OUTPUT_CAP)} | "
                     f"{sum(c.total for c in cs):,} |")
    lines += ["", f"- 남은 호출 {len(calls)}건, 예상 {total:,}토큰 (하루 한도 {tpd:,}의 {total / tpd:.0%})"]
    if biggest:
        size = request(biggest)
        verdict = (f"분당 한도 {tpm:,} 넘음 -> 413으로 멈춤" if size > tpm else
                   f"분당 한도 {tpm:,}의 {TPM_MARGIN:.0%} 넘음 -> 추정 오차로 413이 날 수 있음"
                   if size > tpm * TPM_MARGIN else f"분당 한도 {tpm:,} 안")
        lines.append(f"- 가장 큰 요청: {biggest.node} 입력 약 {biggest.input_tokens:,} + 출력 상한 {OUTPUT_CAP:,} "
                     f"= {size:,}토큰 ({verdict})")
        if size > tpm * TPM_MARGIN:
            lines.append("  - 줄이는 법: 분석가 단계면 RDAGENTS_REPORT_CHUNK_CHARS·RDAGENTS_TOOL_RESULT_CHAR_BUDGET, "
                         "그 뒤 단계면 RDAGENTS_PROMPT_CHAR_BUDGET (환경변수가 체크포인트 값보다 우선)")
    lines.append("- 하루 한도는 최근 24시간 합계라, 그사이 다른 실행에서 쓴 토큰도 빼고 생각해야 합니다")
    lines += ["", "가정: 글자 수 ÷ {:.2f} = 토큰. 출력은 도구 턴 {}, 분석 보고서 {}, 구조화 {}, 발언 {}토큰. "
              "구조화 출력이 검증에 실패해 다시 요청하면 그만큼 늘어납니다.".format(
                  CHARS_PER_TOKEN, OUT_TOOL_TURN, OUT_REPORT, OUT_STRUCTURED, OUT_TEXT)]
    return "\n".join(lines)
