# API 키 없이 가짜 LLM으로 전체 심의 그래프 배선을 검증하는 스모크 테스트
"""실행: .venv/Scripts/python.exe -m pytest tests/test_smoke.py -v  (또는 직접 실행)"""

import enum
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.messages import AIMessage

import rdagents.graph.review_graph as review_graph_module
from rdagents.graph.review_graph import RDReviewGraph


def _default_instance(schema):
    """Pydantic 스키마의 필수 필드를 타입별 기본값으로 채운 인스턴스 생성."""
    values = {}
    for name, field in schema.model_fields.items():
        if not field.is_required():
            continue
        ann = field.annotation
        if isinstance(ann, type) and issubclass(ann, enum.Enum):
            values[name] = list(ann)[0]
        elif ann is float:
            values[name] = 100.0
        elif ann is int:
            values[name] = 1
        elif ann is str:
            values[name] = f"[가짜 {name}]"
        else:
            # list 등 컨테이너 타입은 빈 컨테이너 시도
            try:
                values[name] = ann()
            except Exception:
                values[name] = f"[가짜 {name}]"
    # 스키마 간 정합성 검증을 만족하는 대표 정상값
    if schema.__name__ == "BudgetProposal":
        values["proposed_budget_billion"] = values["original_budget_billion"]
    elif schema.__name__ == "FinalDecision":
        values["approved_budget_billion"] = 100.0
    elif schema.__name__ == "QuestionVerificationReport":
        from rdagents.agents.schemas import MatchLevel, QuestionMatch

        values["matches"] = [
            QuestionMatch(actual_question="[실제 질의1]", match_level=MatchLevel.HIT,
                          matched_prediction="[예측 질의1]", note="논점 일치"),
            QuestionMatch(actual_question="[실제 질의2]", match_level=MatchLevel.MISS,
                          matched_prediction=None, note="예측에 없음"),
        ]
        values["missed_topics_summary"] = "[가짜 미적중 요약]"
    elif schema.__name__ == "ReviewPreparationReport":
        from rdagents.agents.schemas import (
            AnticipatedQuestion, CriterionTag, ImprovementItem, Severity,
        )

        def q(criterion):
            return AnticipatedQuestion(
                question="[가짜 질의]", criterion=criterion, severity=Severity.HIGH,
                basis="[가짜 근거]", suggested_answer="[가짜 답변]",
            )

        values["questions"] = [
            q(CriterionTag.GOV_SUPPORT), q(CriterionTag.IMPORTANCE),
            q(CriterionTag.URGENCY), q(CriterionTag.OTHER), q(CriterionTag.GOV_SUPPORT),
        ]
        values["improvements"] = [
            ImprovementItem(weakness="[가짜 취약점]", severity=Severity.MEDIUM,
                            recommendation="[가짜 권고]")
            for _ in range(3)
        ]
    return schema(**values)


def test_budget_schema_rejects_inconsistent_amounts():
    import pytest
    from pydantic import ValidationError

    from rdagents.agents.schemas import BudgetProposal, FinalDecision

    with pytest.raises(ValidationError):
        BudgetProposal(
            action="감액",
            reasoning="감액 필요",
            original_budget_billion=100,
            proposed_budget_billion=120,
        )
    with pytest.raises(ValidationError):
        FinalDecision(
            verdict="반려",
            executive_summary="반려",
            review_rationale="타당성 부족",
            approved_budget_billion=100,
        )
    with pytest.raises(ValidationError):
        FinalDecision(
            verdict="조건부승인",
            executive_summary="조건부 승인",
            review_rationale="조건 이행 필요",
            approved_budget_billion=80,
            conditions=None,
        )


def test_report_identity_and_memory_limits(tmp_path):
    from rdagents.dataflows.memory_log import append_memory, load_past_context
    from rdagents.dataflows.project_loader import set_current_report, validate_project_id

    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    first = first_dir / "기획보고서.md"
    second = second_dir / "기획보고서.md"
    first.write_text("초안", encoding="utf-8")
    second.write_text("다른 사업", encoding="utf-8")

    first_id = set_current_report(str(first))
    first.write_text("보완본", encoding="utf-8")
    assert set_current_report(str(first)) == first_id
    assert set_current_report(str(second)) != first_id

    import pytest
    with pytest.raises(ValueError):
        validate_project_id("../escape")

    memory = tmp_path / "memory.md"
    decision = json.dumps({"verdict": "승인", "executive_summary": "요약"})
    for index in range(7):
        append_memory(str(memory), first_id, "2027", decision, f"우려 {index}")
    limited = load_past_context(str(memory), first_id, max_entries=2, max_chars=1000)
    assert "우려 5" in limited and "우려 6" in limited
    assert "우려 4" not in limited


def test_quality_score_is_weighted_in_code():
    from rdagents.agents.schemas import DecisionQualityReport, ScoreItem

    report = DecisionQualityReport(
        government_support=ScoreItem(score=100, confidence=80),
        technology_importance=ScoreItem(score=80, confidence=80),
        urgency=ScoreItem(score=60, confidence=80),
        technical_feasibility=ScoreItem(score=40, confidence=80),
        economic_feasibility=ScoreItem(score=20, confidence=80),
        execution_capability=ScoreItem(score=0, confidence=80),
        overall_score=99,  # 모델 입력값은 코드 계산값으로 덮어써야 함
    )
    assert report.overall_score == 59.0
    assert report.overall_confidence == 80.0


def run_checkpoint_and_observability():
    """SQLite 체크포인트 생성과 실행 관측값 누적을 검증한다."""
    import sqlite3
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="rdagents_checkpoint_"))
    db_path = root / "checkpoints.sqlite"
    fake = FakeLLM()
    review_graph_module.create_llm_client = lambda **kwargs: _StubClient(fake)
    graph = RDReviewGraph(config={
        "results_dir": str(root / "logs"),
        "memory_log_path": str(root / "memory.md"),
        "checkpoint_enabled": True,
        "checkpoint_path": str(db_path),
    })
    state, _ = graph.propagate(
        project_id="quantum_computing", execution_id="checkpoint-test"
    )
    assert db_path.exists() and db_path.stat().st_size > 0
    with sqlite3.connect(db_path) as conn:
        checkpoint_count = conn.execute("SELECT count(*) FROM checkpoints").fetchone()[0]
    assert checkpoint_count > 0
    assert state["execution_metadata"]["execution_id"] == "checkpoint-test"
    assert len(state["execution_metrics"]) > 10
    assert (Path(state["saved_results_dir"]) / "12_실행관측성.md").exists()
    print("=== 체크포인트 + 실행 관측성 테스트 통과 ===")
class _StructuredStub:
    def __init__(self, schema, include_raw=False):
        self._schema = schema
        self._include_raw = include_raw

    def invoke(self, _prompt_val):
        instance = _default_instance(self._schema)
        if self._include_raw:
            raw = AIMessage(
                content="",
                usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            )
            return {"raw": raw, "parsed": instance, "parsing_error": None}
        return instance


class FakeLLM:
    """bind_tools / with_structured_output / invoke를 지원하는 오프라인 스텁."""

    def __init__(self):
        self.calls = 0

    def bind_tools(self, _tools):
        def _run(_prompt_val):
            return AIMessage(content="[가짜 분석 보고서] 근거와 표를 포함한 상세 분석.")
        return _run

    def with_structured_output(self, schema, include_raw=False):
        return _StructuredStub(schema, include_raw)

    def invoke(self, _prompt_val):
        self.calls += 1
        return AIMessage(content=f"[가짜 발언 {self.calls}] 전문적 논거를 제시합니다.")


class _StubClient:
    def __init__(self, llm):
        self._llm = llm

    def get_llm(self):
        return self._llm


def run_smoke():
    import tempfile

    fake = FakeLLM()
    # 팩토리를 스텁으로 대체해 API 키 없이 전체 파이프라인 실행
    review_graph_module.create_llm_client = lambda **kwargs: _StubClient(fake)

    results_dir = tempfile.mkdtemp(prefix="rdagents_smoke_")
    config = {
        "results_dir": results_dir,
        "memory_log_path": str(Path(results_dir) / "memory.md"),
    }
    graph = RDReviewGraph(config=config, debug=True)
    final_state, decision = graph.propagate(project_id="quantum_computing", review_year="2027")

    # 1. 6개 분석 보고서 생성 확인
    report_keys = [
        "tech_value_report", "tech_trend_report", "economic_report",
        "policy_report", "feasibility_report", "regulatory_report",
    ]
    for key in report_keys:
        assert final_state.get(key), f"{key} 비어 있음"

    # 2. 심사 공방: max_debate_rounds=2 → 발언 4회 (패널 2, 발표자 2)
    rds = final_state["review_debate_state"]
    assert rds["count"] == 4, f"심사 공방 count={rds['count']}, 기대 4"
    assert rds["history"].count("[심사위원 패널]") == 2
    assert rds["history"].count("[사업 발표자]") == 2

    # 3. 재정 검토: max_audit_rounds=1 → 발언 3회 (Agg, Cons, Neut 각 1)
    ads = final_state["audit_debate_state"]
    assert ads["count"] == 3, f"재정 검토 count={ads['count']}, 기대 3"
    for speaker in ("[적극 투자 검토관]", "[재정 건전성 검토관]", "[균형 재정 조율관]"):
        assert ads["history"].count(speaker) == 1, f"{speaker} 발언 수 이상"

    # 4. 중간 산출물 존재
    assert final_state.get("review_plan"), "review_plan 비어 있음"
    assert final_state.get("budget_coordination_plan"), "budget_coordination_plan 비어 있음"

    # 5. 최종 결정이 유효한 JSON이고 verdict 포함
    decision_dict = json.loads(decision)
    assert decision_dict.get("verdict"), "verdict 없음"

    # 6. 예상 질의 추출기 산출물 생성
    assert final_state.get("anticipated_questions_md"), "예상 질의응답 비어 있음"
    assert final_state.get("improvement_recommendations_md"), "보완 권고 비어 있음"

    # 7. 결과 파일 저장 확인
    saved_dir = Path(final_state["saved_results_dir"])
    expected_files = [
        "00_입력문서_출처.md",
        "01a_분석_기술가치.md", "01b_분석_기술트렌드중복성.md", "01c_분석_경제재무.md",
        "01d_분석_정책부합성.md", "01e_분석_수행체계.md", "01f_분석_규제윤리.md",
        "02_심사공방_전문.md", "03_전문위원회_의견.md", "04_예산조정안.md",
        "05_재정검토토론_전문.md", "06_최종결정.md", "07_예상질의응답.md", "08_보완권고.md",
        "09_정량평가표.md", "10_불확실성_반대근거.md",
        "11_재심의_전후비교.md", "12_실행관측성.md",
    ]
    for filename in expected_files:
        assert (saved_dir / filename).exists(), f"{filename} 미생성"
    assert final_state.get("quality_scorecard_md"), "정량 평가표 비어 있음"
    assert final_state.get("uncertainty_report_md"), "불확실성 보고서 비어 있음"
    assert final_state.get("rereview_comparison_md"), "재심의 비교 보고서 비어 있음"
    assert final_state.get("execution_metrics"), "실행 관측값 비어 있음"
    # 구조화 노드가 재포장한 메시지에도 usage_metadata가 보존되어 토큰이 집계돼야 한다
    total_tokens = sum(m.get("total_tokens", 0) for m in final_state["execution_metrics"])
    assert total_tokens > 0, "토큰 집계가 전부 0 — usage_metadata 유실"

    print("\n=== 스모크 테스트 통과 ===")
    print(f"결과 저장 위치: {saved_dir}")
    print(f"심사 공방 발언: {rds['count']}회, 재정 검토 발언: {ads['count']}회")
    print(f"최종 결정: {decision_dict.get('verdict')}")
    return final_state


def run_report_mode_and_memory():
    """원문(.md) 모드 + 재심의 시 이전 이력(past_context) 주입 검증."""
    import tempfile

    fake = FakeLLM()
    review_graph_module.create_llm_client = lambda **kwargs: _StubClient(fake)

    tmp = Path(tempfile.mkdtemp(prefix="rdagents_report_"))
    report_path = tmp / "양자컴퓨팅_기획보고서.md"
    report_path.write_text(
        "# 차세대 양자컴퓨팅 기획보고서\n\n총 예산 450억원, 5년. TRL 3→7.\n", encoding="utf-8"
    )

    config = {
        "results_dir": str(tmp / "logs"),
        "memory_log_path": str(tmp / "memory.md"),
    }
    graph = RDReviewGraph(config=config, debug=False)

    # 1차 심의: 이전 이력 없음
    fs1, d1 = graph.propagate(report_path=str(report_path), review_year="2027")
    assert fs1["past_context"] == "", "1차 심의에 past_context가 있으면 안 됨"
    assert "신규 심의" in fs1["rereview_comparison_md"]
    assert json.loads(d1).get("verdict")

    # 원문 모드에서 도구가 관련 청크와 출처·신뢰 경계를 반환하는지 확인
    from rdagents.dataflows.project_loader import get_project_overview
    tool_out = get_project_overview.invoke({})
    assert "기획보고서 검색 결과" in tool_out and "450억원" in tool_out, "원문 모드 도구 출력 이상"
    assert "<untrusted_document>" in tool_out and "[출처:" in tool_out

    # 2차 심의(보완 후 재심의 시나리오): 이전 이력 주입 확인
    fs2, _ = graph.propagate(report_path=str(report_path), review_year="2027")
    assert fs2["past_context"], "재심의에 past_context가 비어 있음"
    assert "양자컴퓨팅_기획보고서" in fs2["past_context"]
    assert "재심의" in fs2["rereview_comparison_md"]

    print("=== 원문 모드 + 재심의 메모리 테스트 통과 ===")


def test_structured_retry_recovers_after_validation_error():
    """구조화 출력이 1차 검증 실패 후 오류 피드백 재시도로 복구되는지 확인."""
    from rdagents.agents.schemas import ReviewPlan
    from rdagents.agents.utils.structured import invoke_structured_model

    class FlakyStructured:
        def __init__(self, schema):
            self._schema = schema
            self.attempts = 0

        def invoke(self, _messages):
            self.attempts += 1
            if self.attempts == 1:
                raise ValueError("의도적 검증 실패")
            return _default_instance(self._schema)

    class FlakyLLM(FakeLLM):
        def __init__(self):
            super().__init__()
            self.stub = None

        def with_structured_output(self, schema, include_raw=False):
            self.stub = FlakyStructured(schema)
            return self.stub

    llm = FlakyLLM()
    result = invoke_structured_model(llm, ReviewPlan, "심의 의견을 도출하세요", "테스트")
    assert result.model is not None, "재시도 후에도 모델이 None"
    assert llm.stub.attempts == 2, f"재시도 횟수 이상: {llm.stub.attempts}"


def run_parallel_context_isolation():
    """두 스레드가 서로 다른 원문을 설정해도 교차 오염이 없는지 확인."""
    import tempfile
    import threading

    from rdagents.dataflows.project_loader import get_project_overview, set_current_report

    tmp = Path(tempfile.mkdtemp(prefix="rdagents_parallel_"))
    outputs = {}

    def worker(tag, marker):
        path = tmp / f"{tag}.md"
        path.write_text(f"# {tag} 보고서\n\n{marker} 예산 사업.\n", encoding="utf-8")
        set_current_report(str(path))
        outputs[tag] = get_project_overview.invoke({})

    threads = [
        threading.Thread(target=worker, args=("사업A", "AAA-마커")),
        threading.Thread(target=worker, args=("사업B", "BBB-마커")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert "AAA-마커" in outputs["사업A"] and "BBB-마커" not in outputs["사업A"]
    assert "BBB-마커" in outputs["사업B"] and "AAA-마커" not in outputs["사업B"]
    print("=== 병렬 컨텍스트 격리 테스트 통과 ===")


def run_checkpoint_resume():
    """크래시 후 같은 execution_id로 중단 지점부터 재개되는지 확인."""
    import tempfile

    class CrashOnQuality(FakeLLM):
        def __init__(self):
            super().__init__()
            self.armed = True

        def with_structured_output(self, schema, include_raw=False):
            if self.armed and schema.__name__ == "DecisionQualityReport":
                raise RuntimeError("의도적 크래시 (품질 평가 노드)")
            return super().with_structured_output(schema, include_raw)

    root = Path(tempfile.mkdtemp(prefix="rdagents_resume_"))
    fake = CrashOnQuality()
    review_graph_module.create_llm_client = lambda **kwargs: _StubClient(fake)
    graph = RDReviewGraph(config={
        "results_dir": str(root / "logs"),
        "memory_log_path": str(root / "memory.md"),
        "checkpoint_enabled": True,
        "checkpoint_path": str(root / "checkpoints.sqlite"),
    })

    try:
        graph.propagate(project_id="quantum_computing", execution_id="resume-test")
        raise AssertionError("첫 실행이 품질 평가 노드에서 크래시해야 함")
    except RuntimeError:
        pass

    fake.armed = False
    calls_before = fake.calls
    state, decision = graph.propagate(project_id="quantum_computing", execution_id="resume-test")
    assert json.loads(decision).get("verdict")
    assert state.get("quality_scorecard_md"), "재개 후 정량 평가표 비어 있음"
    # 재개라면 크래시 이전 단계(토론 노드들의 plain invoke)는 재실행되지 않아야 한다
    assert fake.calls == calls_before, (
        f"재개인데 이전 단계가 재실행됨 (plain invoke {fake.calls - calls_before}회)"
    )
    graph.close()
    print("=== 체크포인트 재개 테스트 통과 ===")


def run_question_verification():
    """실제 질의 대조: 13_질의적중검증.md 생성과 적중률 이력 누적을 검증."""
    import tempfile

    from rdagents.agents.schemas import ReviewPreparationReport
    from rdagents.dataflows.question_verification import verify_questions

    tmp = Path(tempfile.mkdtemp(prefix="rdagents_verify_"))
    run_dir = tmp / "run"
    run_dir.mkdir()
    prediction = _default_instance(ReviewPreparationReport)
    (run_dir / "07b_예상질의.json").write_text(prediction.model_dump_json(), encoding="utf-8")

    history = tmp / "history.jsonl"
    fake = FakeLLM()
    md, stats = verify_questions(
        fake, run_dir, "1. 실제 질의1\n2. 실제 질의2", str(history)
    )

    assert stats == {"total": 2, "hits": 1, "partials": 0, "misses": 1,
                     "weighted_hit_rate": 50.0}, stats
    assert (run_dir / "13_질의적중검증.md").exists()
    assert "가중 적중률" in md
    lines = history.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["weighted_hit_rate"] == 50.0

    # 2회차 검증 시 이력이 누적되는지 확인
    verify_questions(fake, run_dir, "1. 실제 질의1\n2. 실제 질의2", str(history))
    assert len(history.read_text(encoding="utf-8").strip().splitlines()) == 2
    print("=== 질의 적중 검증 테스트 통과 ===")


def test_question_verification():
    run_question_verification()


def test_full_pipeline_smoke():
    run_smoke()


def test_report_mode_and_memory():
    run_report_mode_and_memory()


def test_checkpoint_and_observability():
    run_checkpoint_and_observability()


def test_parallel_context_isolation():
    run_parallel_context_isolation()


def test_checkpoint_resume():
    run_checkpoint_resume()


if __name__ == "__main__":
    run_smoke()
    run_report_mode_and_memory()
    run_checkpoint_and_observability()
    run_parallel_context_isolation()
    run_checkpoint_resume()
    run_question_verification()
