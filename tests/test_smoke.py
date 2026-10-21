# API 키 없이 가짜 LLM으로 전체 심의 그래프 배선을 검증하는 스모크 테스트
"""실행: .venv/Scripts/python.exe -m pytest tests/test_smoke.py -v  (또는 직접 실행)"""

import enum
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.messages import AIMessage

import rdagents.graph.review_graph as review_graph_module
from rdagents.graph.review_graph import RDReviewGraph


# 스키마 기본값 인스턴스는 토큰 추정기와 같은 함수를 쓴다
from rdagents.dataflows.token_estimate import sample_instance as _default_instance  # noqa: E402


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


def test_verified_budget_facts_anchor_budget_and_final_decision(tmp_path):
    import pytest

    from rdagents.agents.schemas import (
        BudgetProposal,
        FinalDecision,
        align_budget_proposal_to_request,
        align_final_decision_to_budget,
    )
    from rdagents.dataflows.project_loader import get_project_facts, set_current_report

    report = tmp_path / "예산검증.md"
    report.write_text("사업규모: 22,600백만원(2027~2031)\n", encoding="utf-8")
    set_current_report(str(report), project_id="budget-anchor")
    facts = get_project_facts()
    assert facts["requested_budget_eok"] == 226.0
    assert "L1-L1" in facts["budget_source"]

    proposal = BudgetProposal(
        action="원안통과", reasoning="원안 유지", original_budget_billion=0, proposed_budget_billion=0,
    )
    aligned = align_budget_proposal_to_request(proposal, facts["requested_budget_eok"])
    assert aligned.original_budget_billion == 226.0
    assert aligned.proposed_budget_billion == 226.0

    decision = FinalDecision(
        verdict="조건부승인", executive_summary="조건부 승인", review_rationale="근거 보완 필요",
        approved_budget_billion=22.6, conditions="근거자료 제출",
    )
    with pytest.raises(ValueError, match="검증 예산안"):
        align_final_decision_to_budget(decision, 226.0)
    # 검증 예산도, 금액 있는 조정안도 없으면 승인류 결정은 예산을 지어낸 것 -> 보류하라고 되돌림 (NDMI groq6)
    with pytest.raises(ValueError, match="보류"):
        align_final_decision_to_budget(decision, None, budget_known=False)
    deferred = FinalDecision(verdict="보류", executive_summary="보류", review_rationale="예산액 미기재")
    assert align_final_decision_to_budget(deferred, None, budget_known=False) is deferred


def test_citation_content_check_flags_wrong_line(tmp_path):
    """범위는 유효하지만 인용 줄에 없는 수치·무관한 내용을 확인 권고로 올리고, 검증 상태는 바꾸지 않는다."""
    from rdagents.dataflows.output_validation import build_validation_report, check_citation_content
    from rdagents.dataflows.project_loader import set_current_report

    line = "- 총 사업비: 226억 원 (1차년도 60억)"
    assert check_citation_content("총사업비 226억원 [출처: a.md L1-L1]", line) == []       # 단위 표기 차이 허용
    assert check_citation_content("총사업비 300억 원 [출처: a.md L1-L1]", line) == ["인용 줄에 없는 수치 300억"]
    assert check_citation_content("민간 투자 유인이 부족하다 [출처: a.md L1-L1]", line) == [
        "문장과 인용 줄이 공유하는 단어가 없음"]

    report = tmp_path / "대조.md"
    report.write_text("사업규모: 22,600백만원(2027~2031)\n민간 투자 유인이 부족하다.\n", encoding="utf-8")
    set_current_report(str(report), project_id="content-check")
    text = build_validation_report({
        "01a.md": "민간 투자 유인이 부족하다 [출처: 대조.md L2-L2]\n"      # 맞는 인용
                  "민간 투자 유인이 부족하다 [출처: 대조.md L1-L1]\n",     # 범위는 유효, 줄은 엉뚱함
    })
    assert "**검증 상태**: 통과" in text                   # 경험적 검사라 상태는 그대로
    assert "**출처 내용 대조 확인 권고 수**: 1" in text
    assert "`01a.md` L2 → `대조.md` L1-L1" in text


def test_citation_variants_from_gpt_oss_are_resolved(tmp_path):
    """gpt-oss식 출처 표기(비슷한 하이픈, '…'로 줄인 파일명, 앞부분만 쓴 파일명)를 입력 파일로 해석하고,
    내용 대조 오탐(법조문 '제2조', 표의 숫자 칸, 한 줄 여러 출처, 코드가 만든 사전 점검)을 줄인다."""
    from rdagents.dataflows.output_validation import build_validation_report, resolve_source
    from rdagents.dataflows.project_loader import set_current_report

    report = tmp_path / "(NDMI-기본-2025-20)+재난+피해+연쇄적+영향평가.md"
    report.write_text("「자연재해대책법」 제2조제3호에 따른 풍수해를 대상으로 한다.\n"
                      "수집된 7,045건의 기사 중 중복을 제외하였다.\n"
                      "복구비는 251.6% 증가하였다.\n", encoding="utf-8")
    set_current_report(str(report), project_id="variants")
    name = report.name
    known = {name: 3}
    assert resolve_source("(NDMI‑기본‑2025‑20)…", known) == (name, True)       # U+2011 하이픈 + 줄임표
    assert resolve_source("(NDMI-기본-2025-20)", known) == (name, True)         # 줄임표 없이 앞부분만
    assert resolve_source("(NDMI…", known) == (name, True)
    assert resolve_source("(N", known) == (None, False)                          # 너무 짧으면 해석하지 않음
    assert resolve_source("다른파일.md", known) == (None, False)

    text = build_validation_report({
        "01a.md": "풍수해 대상 범위 [출처: (NDMI‑기본‑2025‑20)… L1‑L1]\n"
                  "대응시간 30% 감소 [출처: (NDMI-기본-2025-20) L3-L3]\n",           # 원문에 없는 수치
        "09.md": "| 기술적 실현 가능성 | 15% | 55.0 | 복구비 증가 추세 [출처: (NDMI-기본-2025-20)… L3-L3] |\n",
        "02.md": "| 풍수해, 7,045건 | [출처: (NDMI-기본-2025-20)… L1-L1]; [출처: (NDMI-기본-2025-20)… L2-L2] |\n",
        "00b_사전점검.md": "| 시급성 | 2조 | [출처: (NDMI-기본-2025-20)… L3-L3] |\n",
    })
    assert "**출처 검증 이슈 수**: 0" in text
    assert "**형식·범위가 유효한 출처 인용 수**: 6 (그중 줄여 쓴 파일명을 입력 파일로 해석한 것 6)" in text
    assert "**출처 내용 대조 확인 권고 수**: 2" in text            # "30% 감소" 한 문장 (수치·단어 두 사유)
    assert text.count("`01a.md` L2 →") == 2 and "인용 줄에 없는 수치 30%" in text

def test_unsupported_numbers_are_marked_in_body(tmp_path):
    """LLM 산출물에서 입력 원문에 없는 수치가 든 줄 끝에 표시를 붙인다. 반올림 값·0·표 숫자 칸·코드가 만든 파일은 제외,
    표 줄은 마지막 칸 안에 넣고, 다시 돌려도 두 번 붙이지 않는다."""
    from rdagents.dataflows.output_validation import (
        UNSUPPORTED_NOTE,
        build_validation_report,
        mark_unsupported_numbers,
        unsupported_number_summary,
    )
    from rdagents.dataflows.project_loader import set_current_report

    report = tmp_path / "원문.md"
    report.write_text("복구비는 251.6% 증가하였다. 사망 6명, 재산피해 2,150억 원.\n", encoding="utf-8")
    set_current_report(str(report), project_id="marks")
    docs = {
        "01a.md": "재산피해 2,150억 원, 복구비 252% 증가\n"                 # 원문 값과 반올림 값 -> 통과
                  "대응시간 30% 감소 [출처: 원문.md L1-L1]\n",             # 원문에 없음 -> 표시
        "02.md": "| 기대효과 | 인명 피해 15명 감소 |\n",                      # 표 줄
        "04.md": "**원래 요청 예산**: 0.0억원\n",                           # 0은 통과
        "09.md": "| 기술적 실현 가능성 | 15% | 55.0 | 근거 서술 |\n",          # 숫자만 있는 칸은 통과
        "00b_사전점검.md": "| 시급성 | 99% |\n",                            # 코드가 만든 파일
    }
    marked, found = mark_unsupported_numbers(docs)
    assert found == [("01a.md", 2, ["30%"]), ("02.md", 1, ["15명"])]
    assert marked["01a.md"].splitlines()[1].endswith(UNSUPPORTED_NOTE.format("30%"))
    assert marked["02.md"] == "| 기대효과 | 인명 피해 15명 감소 " + UNSUPPORTED_NOTE.format("15명") + " |\n"
    assert marked["00b_사전점검.md"] == docs["00b_사전점검.md"]
    assert mark_unsupported_numbers(marked) == (marked, found)            # 다시 돌려도 두 번 붙이지 않음
    text = build_validation_report(marked, found)
    assert "**원문에 없는 수치를 본문에 표시한 줄 수**: 2" in text and "`02.md` L1: 15명" in text
    # 수치별 요약: 같은 수치가 여러 줄에 나오면 한 행으로 묶고, 표 칸이 깨지지 않게 '|'와 출처·표시를 뺀 문장을 싣는다
    marked["03.md"] = "질의: 대응시간 30% 감소 근거는?\n"
    found.append(("03.md", 1, ["30%"]))
    summary = build_validation_report(marked, found).split("## 검증 안 된 수치 요약 (수치별)")[1].split("\n## ")[0]
    assert "| 30% | 2 | `01a.md`, `03.md` | 대응시간 30% 감소 (`01a.md` L2) |" in summary
    assert "| 15명 | 1 | `02.md` | 기대효과 인명 피해 15명 감소 (`02.md` L1) |" in summary
    assert summary.index("| 30% |") < summary.index("| 15명 |")       # 많이 번진 수치부터
    # 기간 '2개월'은 개수가 아니고, 요약 표의 수치는 쉼표를 되살려 보여준다
    assert mark_unsupported_numbers({"05.md": "지연을 최대 2개월로 제한\n"})[1] == []
    rows = unsupported_number_summary({"02.md": "재산 1,200억 원 손실\n"}, [("02.md", 1, ["1200억"])])
    assert rows[2].startswith("| 1,200억 | 1 |")


def test_table_unit_and_computed_values_are_not_marked(tmp_path):
    """단위가 열 제목·'(단위: …, %)'에만 있는 표 숫자와 사전 점검이 계산한 값은 원문 수치로 본다 (groq5 실행의 오탐).
    규칙이 바뀌면 지난 표시는 지우고 다시 붙인다."""
    from rdagents.dataflows.output_validation import UNSUPPORTED_NOTE, mark_unsupported_numbers
    from rdagents.dataflows.project_loader import set_current_report

    report = tmp_path / "원문.md"
    report.write_text("###### 표 1.1 원인별 피해액\n\n(단위: 백만원, %)\n\n"
                      "|구분|피해액 평균|피해액 비율|사업비(억원)|\n|---|---|---|---|\n"
                      "|태풍·호우|642|0.3|12.5|\n|기타|18,511|2.8|7|\n", encoding="utf-8")
    set_current_report(str(report), project_id="table-units")
    precheck = "## 숫자 검산\n\n| 비율 | 표 1.1 · 태풍·호우 | 0.3% | 3.2% |\n"
    old = "Q4. 비율 0.3%와 계산값 3.2% 중 어느 것이 정확합니까? " + UNSUPPORTED_NOTE.format("0.3%, 3.2%")
    docs = {"00b_사전점검.md": precheck,
            "07.md": old + "\n사업비 12.5억 원, 기타 2.8%, 신규 9.9%\n"}
    marked, found = mark_unsupported_numbers(docs)
    assert found == [("07.md", 2, ["9.9%"])]                            # 원문에 없는 값만 남음
    assert marked["07.md"].splitlines()[0] == "Q4. 비율 0.3%와 계산값 3.2% 중 어느 것이 정확합니까?"
    # 사전 점검 없이는 계산 값 3.2%는 원문에 없는 수치
    assert mark_unsupported_numbers({"07.md": "계산값 3.2%"})[1] == [("07.md", 1, ["3.2%"])]


def test_numbers_are_marked_as_nodes_write(tmp_path):
    """노드가 쓴 보고서·토론 글에 바로 표시를 붙여 뒤 노드가 표시된 글을 읽는다. 흐름 제어 값과 JSON 필드는 그대로."""
    from rdagents.dataflows.output_validation import UNSUPPORTED_NOTE
    from rdagents.dataflows.project_loader import set_current_report
    from rdagents.graph.setup import _timed_node

    report = tmp_path / "원문.md"
    report.write_text("총사업비 120억 원, 사망 6명\n", encoding="utf-8")
    set_current_report(str(report), project_id="in-flight")
    plan = '{"key_concerns": "피해 1,200억 원"}'
    node = _timed_node("Panel Examiner", lambda state: {
        "tech_value_report": "총사업비 120억 원, 피해 1,200억 원 [출처: 원문.md L1-L1]",
        "review_plan": plan,
        "review_debate_state": {"history": "\n[심사위원 패널]: 피해 1,200억 원 근거는?\n", "current_response": "Examiner",
                                "count": 1},
    })
    result = node({"precheck_md": "", "execution_metrics": []})
    assert result["tech_value_report"].endswith(UNSUPPORTED_NOTE.format("1200억"))
    assert UNSUPPORTED_NOTE.format("1200억") in result["review_debate_state"]["history"]
    assert result["review_debate_state"]["current_response"] == "Examiner"   # 흐름 제어 값
    import json
    assert json.loads(result["review_plan"])["key_concerns"].endswith(UNSUPPORTED_NOTE.format("1200억"))  # JSON 글 값
    assert _timed_node("x", lambda s: {"review_plan": "JSON 아님 1,200억 원"})({})["review_plan"] == "JSON 아님 1,200억 원"
    # 다음 노드가 표시된 기록에 덧붙여도 표시가 두 번 붙지 않는다
    again = _timed_node("Defender", lambda state: {"review_debate_state": {
        "history": result["review_debate_state"]["history"] + "[발표자]: 사망 6명\n"}})({"execution_metrics": []})
    assert again["review_debate_state"]["history"].count("⚠️") == 1
    # 근거 원칙이 표시된 수치를 옮겨 쓰지 말라고 알린다
    from rdagents.agents.utils.agent_utils import get_language_instruction
    assert "⚠️[원문에 없는 수치: …]" in get_language_instruction()


def test_million_won_amounts_match_eok_in_outputs(tmp_path):
    """원문의 백만원·천원 금액과 억·조 금액을 산출물이 다른 단위로 바꿔 써도 원문 수치로 본다.
    (기관고유 샘플 보고서에서 '14,160백만원'을 '141.6억 원'으로 쓴 줄이 26줄 표시됐음) 단위를 틀리면 그대로 표시."""
    from rdagents.dataflows.output_validation import mark_unsupported_numbers
    from rdagents.dataflows.project_loader import set_current_report

    report = tmp_path / "원문.md"
    report.write_text("사업규모 : 14,160백만원, 연구개발비 4,716,690 천원, 전체 2.11조 원\n\n"
                      "| 연도 | 총사업비(백만원) |\n|---|---|\n| 2024 | 4,500 |\n", encoding="utf-8")
    set_current_report(str(report), project_id="money-units")
    docs = {"04.md": "총 141.6억 원, 연구개발비 47.2억 원, 2024년 45억 원, 전체 21,100억 원\n"
                     "총 1,416억 원\n"}                                  # 단위를 10배 틀림 -> 표시
    assert mark_unsupported_numbers(docs)[1] == [("04.md", 2, ["1416억"])]
    # 줄번호 없는 출처 뒤의 다른 출처를 한 인용으로 묶지 않는다 (기관고유 보고서 07b JSON에서 3건 오탐)
    from rdagents.dataflows.output_validation import build_validation_report
    text = build_validation_report({"07b.json": '{"q":"【출처: 전문위원회 의견】","a":"총 141.6억 원 [출처: 원문.md L1-L1]"}'})
    assert "**출처 검증 이슈 수**: 0" in text
    # 1억 미만·1조 미만 금액은 그 단위로 바꾸지 않는다 (반올림 허용 범위로 지어낸 값이 통과했음)
    report.write_text("피해액 7백만원, 투자 9,600억 원\n", encoding="utf-8")
    set_current_report(str(report), project_id="money-units")
    assert mark_unsupported_numbers({"05.md": "예산 0.1억 원, 매출 1조 원\n"})[1] == [("05.md", 1, ["0.1억", "1조"])]

def test_precheck_includes_number_crosscheck():
    """사전 점검에 숫자 검산(표 합계·비율·본문 합계)이 붙고, 불일치는 패널·질의 요약에 최대 3건 올라간다."""
    from rdagents.dataflows.plan_precheck import run_precheck

    text = "\n".join([
        "## 사업 규모",
        "- 총 사업비: 120억 원 (1차년도 30억, 2차년도 50억, 3차년도 45억)",
        "(단위: 백만원, %)",
        "|구분|피해액|비율|", "|---|---|---|",
        "|가|600|60.0|", "|나|300|30.0|", "|다|170|10.0|", "|총계|1,000|100.0|",
    ])
    full, brief = run_precheck(text, "a.md")
    assert "## 숫자 검산" in full and "| 본문 합계 |" in full and "[출처: a.md L2-L2]" in full
    assert "[숫자 검산] 원인 칸 추정" in brief                     # 원인 칸 추정을 먼저
    assert brief.count("[숫자 검산]") == 3                          # 불일치 4건 이상이어도 3건까지
    clean, clean_brief = run_precheck("- 총 사업비: 120억 원 (1차년도 70억, 2차년도 50억)", "b.md")
    assert "불일치 0건" in clean and "[숫자 검산]" not in clean_brief


def test_question_extractor_short_output_note(monkeypatch):
    """짧은 문맥 모드면 예상 질의 개수·답변 길이를 줄이라는 지시가 붙는다 (출력 상한에서 JSON이 잘리지 않게)."""
    from rdagents.agents.managers import question_extractor as qe

    captured = {}

    def fake_invoke(llm, schema, prompt_val, name, **kw):
        captured["system"] = prompt_val.to_messages()[0].content
        from rdagents.agents.utils.structured import StructuredCallResult
        return StructuredCallResult(_default_instance(schema))

    monkeypatch.setattr(qe, "invoke_structured_model", fake_invoke)
    monkeypatch.delenv("RDAGENTS_PROMPT_CHAR_BUDGET", raising=False)
    state = {"review_debate_state": {"history": ""}, "audit_debate_state": {"history": ""}, "prompt_char_budget": 900}
    qe.create_question_extractor(None)(state)
    assert "출력 길이 제한" in captured["system"]
    qe.create_question_extractor(None)({**state, "prompt_char_budget": 0})
    assert "출력 길이 제한" not in captured["system"]
    assert "숫자 검산 불일치 반영" not in captured["system"]
    # 사전 점검이 숫자 불일치를 찾았으면 질의·권고에 반드시 넣으라는 지시가 붙는다
    qe.create_question_extractor(None)({**state, "precheck_brief": "- [숫자 검산] 비율: 표 1.1 — 적힌 값 0.3%"})
    assert "숫자 검산 불일치 반영" in captured["system"]


def test_analysts_get_short_output_note(monkeypatch):
    """짧은 문맥 모드면 분석가 6명 모두 보고서 길이 제한 지시를 받는다 (출력 상한에서 요약 표가 잘리지 않게)."""
    from rdagents.agents import analysts

    monkeypatch.delenv("RDAGENTS_PROMPT_CHAR_BUDGET", raising=False)
    factories = [getattr(getattr(analysts, m), f) for m in ("economic", "feasibility", "policy", "regulatory",
                                                             "tech_trend", "tech_value")
                 for f in dir(getattr(analysts, m)) if f.startswith("create_")]
    assert len(factories) == 6
    for budget, expected in ((900, True), (0, False)):
        for factory in factories:
            captured = {}

            class CaptureLLM:
                def bind_tools(self, _tools, **_kw):
                    def _run(prompt_val):
                        captured["system"] = prompt_val.to_messages()[0].content
                        return AIMessage(content="보고서")
                    return _run

            factory(CaptureLLM())({"messages": [], "review_year": "2026", "prompt_char_budget": budget})
            assert ("출력 길이 제한" in captured["system"]) is expected, factory.__name__


def test_more_citation_variants_from_gpt_oss(tmp_path):
    """groq4 실행에서 나온 표기: 줄임표 뒤 공백 없음, 앞 괄호 빠짐, 가운데를 줄인 이름, 한 인용에 범위 여러 개."""
    from rdagents.dataflows.output_validation import build_validation_report, resolve_source
    from rdagents.dataflows.project_loader import set_current_report

    report = tmp_path / "(NDMI-기본-2025-20)+재난+피해+연쇄적+영향평가.md"
    report.write_text("풍수해를 대상으로 한다.\n중복 기사를 제외하였다.\n복구비가 증가하였다.\n", encoding="utf-8")
    set_current_report(str(report), project_id="variants2")
    name = report.name
    known = {name: 3}
    assert resolve_source("NDMI‑기본‑2025‑20…", known) == (name, True)        # 앞 괄호 빠짐
    assert resolve_source("(NDMI‑기본‑2025‑20)…md", known) == (name, True)     # 가운데를 줄임
    assert resolve_source("(NDMI‑기본‑2025‑20)…txt", known) == (None, False)   # 끝부분이 다르면 해석하지 않음

    text = build_validation_report({
        "01a.md": "풍수해 대상 [출처: (NDMI‑기본‑2025‑20)…L1‑L1]\n"
                  "중복 기사 제외 [출처: NDMI‑기본‑2025‑20… L2‑L2]\n"
                  "풍수해 대상 [출처: (NDMI‑기본‑2025‑20)…md L1‑L1]\n",
        "02.md": f"풍수해 복구비 증가 [출처: {name} L1-L1, L3-L3, L9-L9]\n",       # L9는 범위 밖
    })
    assert "**형식·범위가 유효한 출처 인용 수**: 5" in text
    assert "**출처 검증 이슈 수**: 1" in text and "L9-L9가" in text
    assert "줄번호가 생략" not in text and "인용 원문을 찾을 수 없음" not in text

def test_rerender_and_compare_runs(tmp_path):
    """저장된 결과를 LLM 없이 다시 렌더링하고(이전 검증보고서는 검사 대상에서 제외), 두 실행을 같은 지표로 비교한다."""
    from rdagents.dataflows.project_loader import set_current_report
    from rdagents.dataflows.result_writer import rerender_results
    from rdagents.dataflows.run_compare import collect, render

    review_graph_module.create_llm_client = lambda **kwargs: _StubClient(FakeLLM())
    report_path = tmp_path / "보고서.md"
    report_path.write_text("# 기획보고서\n\n총 예산 450억원, 5년. 사망 6명.\n", encoding="utf-8")
    graph = RDReviewGraph(config={"results_dir": str(tmp_path / "logs"), "memory_log_path": str(tmp_path / "m.md")})
    state, _ = graph.propagate(report_path=str(report_path), review_year="2027")
    graph.close()
    run = Path(state["saved_results_dir"])
    # 사업 유형 판별이 상태·사전 점검 문서·정량 평가표·HTML까지 이어진다 (공공 키워드 1줄뿐이라 혼합형)
    assert state["project_type"] == "혼합형"
    assert (run / "00b_사전점검.md").read_text(encoding="utf-8").startswith("## 사업 유형 판별")
    assert "- **사업 유형**: 혼합형" in (run / "09_정량평가표.md").read_text(encoding="utf-8")
    assert "<dt>사업 유형</dt><dd>혼합형 (자동 판별)</dd>" in (run / "심의종합리포트.html").read_text(encoding="utf-8")
    # 쟁점 원장: 파일로 남고 HTML 의결 요약과 실행 비교에 공방 결과가 나온다. 분야 기술전문가 보고서도 저장
    assert (run / "02b_쟁점원장.md").read_text(encoding="utf-8").startswith("# 쟁점 원장")
    html = (run / "심의종합리포트.html").read_text(encoding="utf-8")
    assert re.search(r"쟁점 원장 \(코드 판정\)</strong><br>쟁점 수 \d+: 방어 성공 0 · 방어 실패 \d+ · 공방 미상정", html)
    assert "⚠️" not in (run / "02b_쟁점원장.md").read_text(encoding="utf-8").split("| #")[0]   # 코드가 쓴 개수엔 표시 없음
    assert collect(str(run))["쟁점 원장 (공방 결과)"].startswith("방어 성공 0 · 방어 실패")
    assert (run / "01_분석_분야기술전문가.md").exists()

    before = collect(str(run))
    assert before["LLM 호출 수"] > 10                             # 가짜 응답의 예산 100.0억도 원문에 없어 표시됨

    # 산출물을 바꾼 뒤 다시 렌더링하면 새 규칙이 적용되고 HTML도 다시 만들어진다
    analysis = run / "01a_분석_기술가치.md"
    analysis.write_text(analysis.read_text(encoding="utf-8") + "\n대응시간 30% 감소 [확인 필요: 근거]\n", encoding="utf-8")
    set_current_report(str(report_path))
    rerender_results(str(run), review_year="2027")
    rerender_results(str(run), review_year="2027")                 # 두 번 해도 결과 같음 (자기 검사·중복 표시 없음)
    after = collect(str(run))
    assert after["원문에 없는 수치 표시 줄"] == before["원문에 없는 수치 표시 줄"] + 1
    assert after["미확인 사실형 문장"] == before["미확인 사실형 문장"] + 1
    html = (run / "심의종합리포트.html").read_text(encoding="utf-8")
    assert "⚠️[원문에 없는 수치: 30%]" in html
    assert '<h3 id="unsupported">검증 안 된 수치</h3>' in html and 'href="#unsupported"' in html  # 의결 바로 아래

    table = render(str(run), str(run))
    n = after["원문에 없는 수치 표시 줄"]
    assert f"| 원문에 없는 수치 표시 줄 | {n} | {n} | 같음 |" in table

    # 숫자 검산 표 번호가 공방·권고에 언급됐는지: 좁은 공백(U+202F)으로 쓴 '표 1.1'도 센다
    (run / "00b_사전점검.md").write_text("## 숫자 검산\n\n불일치 1건\n\n| 비율 | 표 1.1 · 기타 |\n", encoding="utf-8")
    (run / "02_심사공방_전문.md").write_text("표 1.1 값이 맞지 않습니다\n", encoding="utf-8")
    (run / "08_보완권고.md").write_text("표 1.1을 원문과 대조하세요\n", encoding="utf-8")
    assert collect(str(run))["숫자 검산 표가 공방·질의에 언급된 줄"] == 2

def test_preparation_report_requires_budget_question():
    """예상 질의에 예산 타당성 질의가 없으면 3대 기준과 똑같이 검증 오류(-> 구조화 재시도)."""
    import pytest

    from rdagents.agents.schemas import CriterionTag, ReviewPreparationReport

    complete = _default_instance(ReviewPreparationReport)
    assert CriterionTag.BUDGET in {q.criterion for q in complete.questions}
    values = complete.model_dump()
    values["questions"] = [q for q in values["questions"] if q["criterion"] != CriterionTag.BUDGET]
    values["questions"].append({**values["questions"][0], "criterion": CriterionTag.OTHER})
    with pytest.raises(ValueError, match="예산 타당성"):
        ReviewPreparationReport(**values)


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


def test_groq_profile_uses_short_context_and_json_schema():
    """Groq 무료 등급용 프로필: 짧은 문맥 예산 + 구조화 출력은 json_schema (tool_use_failed 회피)."""
    import main
    from rdagents.llm_clients.capabilities import get_capabilities

    profile = main.PROFILES["test-groq"]
    assert profile["llm_provider"] == "groq"
    assert profile["prompt_char_budget"] == 800
    assert get_capabilities(profile["deep_think_llm"]).preferred_structured_method == "json_schema"
    assert "test-cerebras" not in main.PROFILES  # Cerebras는 정책 변경으로 쓰지 않음
    assert main._validate_provider_auth("groq") in (None, "groq 프로바이더에 필요한 GROQ_API_KEY가 설정되어 있지 않습니다.")


def test_quality_score_is_weighted_in_code():
    from rdagents.agents.schemas import DecisionQualityReport, ScoreItem

    report = DecisionQualityReport(
        government_support=ScoreItem(score=100, confidence=80),
        technology_importance=ScoreItem(score=80, confidence=80),
        urgency=ScoreItem(score=60, confidence=80),
        technical_feasibility=ScoreItem(score=40, confidence=80),
        economic_feasibility=ScoreItem(score=20, confidence=80),
        execution_capability=ScoreItem(score=0, confidence=80),
        field_deployment=ScoreItem(score=50, confidence=80),
        disaster_phase_fit=ScoreItem(score=90, confidence=80),
        overall_score=99,  # 모델 입력값은 코드 계산값으로 덮어써야 함
    )
    # 유형을 모르면 혼합형 가중치: 20/20/15/15/10/10/10 (재난관리 단계 적합성은 쓰지 않음)
    assert report.overall_score == 58.0
    assert report.overall_confidence == 80.0
    from rdagents.agents.schemas import TYPE_QUALITY_WEIGHTS, apply_quality_weights, render_quality_scorecard
    for weights in TYPE_QUALITY_WEIGHTS.values():
        assert round(sum(w for _, w in weights.values()), 6) == 1.0
    # 공공임무형: 정부지원 20, 공공가치 20, 시급성 15, 단계 적합성 10, 현장 적용 15, 실현가능성 8, 역량 7, 비용효과성 5
    assert apply_quality_weights(report, "공공임무형").overall_score == 65.7
    table = render_quality_scorecard(report, "공공임무형")
    assert "| 현장 적용·확산 경로 | 15% |" in table and "| 비용효과성 | 5% |" in table
    assert "재난관리 단계 적합성" not in render_quality_scorecard(report, "산업형")


def test_common_prompt_forbids_fabricated_evidence():
    from rdagents.agents.utils.agent_utils import get_language_instruction

    instruction = get_language_instruction()
    assert "제공되지 않은 통계" in instruction
    assert "[확인 필요: 필요한 자료]" in instruction
    assert "사업보고서 주장" in instruction and "외부근거 확인" in instruction


def test_review_criteria_adapts_to_public_safety_projects():
    from rdagents.agents.utils.review_criteria import get_review_criteria

    public = get_review_criteria("공공임무형")
    assert "사업 유형: 공공임무형" in public
    for phrase in ("인명·재산 피해 저감", "지역 간 안전격차", "억지 B/C", "재난관리 단계 적합성",
                   "수요기관", "운영·유지관리 주체와 재원", "부처 간 역할 분담"):
        assert phrase in public
    industry = get_review_criteria("산업형")
    assert "기술 주권" in industry and "재난관리 단계" not in industry
    assert "사업 유형: 혼합형" in get_review_criteria() == get_review_criteria("혼합형")  # 유형을 모르면 혼합형


def test_project_type_drives_precheck_and_required_questions(tmp_path):
    """사업 유형을 규칙으로 판별해 사전 점검 항목과 필수 질의가 달라진다. --project-type이 판별보다 우선."""
    import pytest

    from rdagents.agents.schemas import CriterionTag, ReviewPreparationReport, require_type_questions
    from rdagents.dataflows.plan_precheck import check_lines, checklist_for
    from rdagents.dataflows.project_type import classify, render_section

    public = {"a.md": ["## 추진 배경", "- 최근 5년 풍수해 인명 피해 증가, 재난 대응 공백", "- 소방 현장 대피 지원",
                       "- 피해 저감 목표 20%"]}
    industry = {"b.md": ["- 글로벌 시장 규모 10조 원, 수출 확대", "- 기술 이전과 사업화로 매출 창출"]}
    assert classify(public).project_type == "공공임무형"
    assert classify(industry).project_type == "산업형"
    assert classify({**public, **industry}).project_type == "혼합형"
    assert classify({}).project_type == "혼합형"                              # 판별할 원문 없음
    forced = classify(public, override="산업형")
    assert (forced.project_type, forced.decided_by) == ("산업형", "사용자 지정")
    section = render_section(classify(public))
    assert "- 판별: **공공임무형** (자동 판별)" in section and "[출처: a.md L2-L2]" in section

    # 공공임무형·혼합형만 재난안전 점검 항목(수요기관·재난관리 단계·제도화·운영 재원)이 붙는다
    assert len(checklist_for("산업형")) == 9 and len(checklist_for("공공임무형")) == 13
    status = {r.item.key: r.status for r in check_lines(
        ["- 수요기관: 시·도 재난안전대책본부 참여", "- 대응 단계의 상황 공유 공백", "- 운영 매뉴얼 개정 반영"],
        checklist_for("공공임무형"))}
    assert status["demand_agency"] == status["disaster_phase"] == status["institutionalize"] == "충족"
    assert status["maintenance"] == "누락"

    # 공공임무형은 '현장 적용·확산' 질의가 있어야 한다 (산업형은 없어도 통과)
    from rdagents.dataflows.token_estimate import sample_instance
    report = sample_instance(ReviewPreparationReport)
    assert require_type_questions(report, "공공임무형") is report
    without = report.model_copy(update={"questions": [q for q in report.questions if q.criterion != CriterionTag.FIELD]
                                        + [report.questions[0]]})
    with pytest.raises(ValueError, match="현장 적용·확산"):
        require_type_questions(without, "공공임무형")
    assert require_type_questions(without, "산업형") is without


def test_protected_report_keeps_internal_navigation_unlocked():
    """암호 해제 후 목차 링크가 상위 잠금 페이지를 다시 탐색하지 않아야 한다."""
    generator = (
        Path(__file__).resolve().parent.parent / "tools" / "protect_report.mjs"
    ).read_text(encoding="utf-8")

    assert 'sandbox="allow-same-origin"' in generator
    assert "bindInternalNavigation" in generator
    assert "event.preventDefault()" in generator
    assert "target.scrollIntoView" in generator
    assert "input.value = ''" in generator
    assert "sessionStorage" not in generator and "localStorage" not in generator


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
        if self._schema.__name__ == "FinalDecision":
            messages = _prompt_val.to_messages() if hasattr(_prompt_val, "to_messages") else _prompt_val
            prompt_text = "\n".join(str(getattr(message, "content", message)) for message in messages)
            match = re.search(r'"proposed_budget_billion"\s*:\s*([0-9.]+)', prompt_text)
            if match:
                instance.approved_budget_billion = float(match.group(1))
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

    def bind_tools(self, _tools, **_kwargs):
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

    # 2. 쟁점별 심사 공방: 가짜 쟁점 3개(정부지원·시급성 '상', 예산)는 모두 반드시 올릴 쟁점 → 발언 6회
    rds = final_state["review_debate_state"]
    ledger = final_state["issue_ledger"]
    assert [i["status"] for i in ledger] == ["방어 실패"] * 3          # 가짜 발표자는 근거 없음을 인정
    assert rds["count"] == 6, f"심사 공방 count={rds['count']}, 기대 6"
    assert rds["history"].count("[심사위원 패널 · ") == 3 and rds["history"].count("[사업 발표자]") == 3
    assert "재정위원" in rds["history"]                               # 예산 쟁점은 재정위원이 질의

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
    assert final_state.get("preparation_report_json"), "예상 질의 JSON 비어 있음"

    # 6b. 관문 프로파일·질의 은행이 상태에 주입되는지 확인
    assert "심의 관문: 부처 내 심의" in final_state.get("gate_profile", ""), "기본 관문 프로파일 누락"
    assert "전형 질의 패턴" in final_state.get("question_bank", ""), "질의 은행 시드 미로드"

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
        "14_검증보고서.md",
        "심의종합리포트.html",
    ]
    for filename in expected_files:
        assert (saved_dir / filename).exists(), f"{filename} 미생성"
    assert final_state.get("quality_scorecard_md"), "정량 평가표 비어 있음"
    assert final_state.get("uncertainty_report_md"), "불확실성 보고서 비어 있음"
    assert final_state.get("rereview_comparison_md"), "재심의 비교 보고서 비어 있음"
    assert final_state.get("execution_metrics"), "실행 관측값 비어 있음"
    html_report = saved_dir / "심의종합리포트.html"
    html_text = html_report.read_text(encoding="utf-8")
    assert "국가연구개발사업 심의결과 보고서" in html_text
    assert "심의 기준연도</strong> 2027" in html_text
    assert 'id="decision"' in html_text and 'id="appendix"' in html_text
    assert "<pre>" not in html_text, "Markdown 원문이 pre 블록으로 그대로 노출됨"
    validation_text = (saved_dir / "14_검증보고서.md").read_text(encoding="utf-8")
    assert "생성물 근거 검증 보고서" in validation_text
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

    # 원문 모드에서는 심의 전에 규칙 기반 사전 점검이 돌고 결과가 저장된다
    assert "기획보고서 사전 점검" in fs1["precheck_md"]
    assert "정부지원 필요성" in fs1["precheck_brief"]          # 짧은 보고서라 누락 항목이 요약에 올라감
    saved = list((tmp / "logs").rglob("00b_사전점검.md"))
    assert saved and "[출처: 양자컴퓨팅_기획보고서.md L" in saved[0].read_text(encoding="utf-8")

    print("=== 원문 모드 + 재심의 메모리 테스트 통과 ===")


GROQ_TPD_MESSAGE = (
    "Error code: 429 - {'error': {'message': 'Rate limit reached for model `openai/gpt-oss-120b` in organization "
    "`org_x` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 194723, Requested 6678. "
    "Please try again in 10m5.232s.', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}"
)


def test_daily_quota_detection():
    from rdagents.llm_clients.quota import DailyQuotaExceeded, as_daily_quota

    daily = as_daily_quota(RuntimeError(GROQ_TPD_MESSAGE))
    assert isinstance(daily, DailyQuotaExceeded) and daily.retry_after == "10m5.232s"
    per_minute = GROQ_TPD_MESSAGE.replace("tokens per day (TPD)", "tokens per minute (TPM)")
    assert as_daily_quota(RuntimeError(per_minute)) is None      # 분당 한도는 기존처럼 재시도
    assert as_daily_quota(ValueError("schema validation failed")) is None


def test_per_minute_limit_waits_as_told_and_413_stops(monkeypatch):
    """분당 한도는 공급자가 알려 준 시간만큼 기다렸다 재시도, 요청 초과(413)는 재시도 없이 멈춤."""
    import httpx
    import pytest
    from langchain_openai import ChatOpenAI
    from openai import APIStatusError, RateLimitError

    from rdagents.llm_clients.openai_client import NormalizedChatOpenAI
    from rdagents.llm_clients.quota import RequestTooLarge, as_request_too_large

    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    tpm = GROQ_TPD_MESSAGE.replace("tokens per day (TPD)", "tokens per minute (TPM)").replace("10m5.232s", "2.5s")
    calls, sleeps = {"n": 0}, []

    def flaky(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RateLimitError(tpm, response=httpx.Response(429, request=req), body=None)
        return AIMessage(content="ok")

    monkeypatch.setattr(ChatOpenAI, "invoke", flaky)
    monkeypatch.setattr("time.sleep", sleeps.append)
    llm = NormalizedChatOpenAI(model="openai/gpt-oss-120b", api_key="test", base_url="https://api.groq.com/openai/v1")
    assert llm.invoke("hi").content == "ok"
    assert sleeps == [3.0, 3.0]  # 안내된 2.5초 + 여유 0.5초

    too_large = ("Error code: 413 - {'error': {'message': 'Request too large for model `openai/gpt-oss-120b` "
                 "on tokens per minute (TPM): Limit 8000, Requested 8555'}}")

    def huge(self, *args, **kwargs):
        raise APIStatusError(too_large, response=httpx.Response(413, request=req), body=None)

    monkeypatch.setattr(ChatOpenAI, "invoke", huge)
    with pytest.raises(RequestTooLarge):
        llm.invoke("hi")
    assert as_request_too_large(RuntimeError("Requested 4130 tokens")) is None  # 숫자 4130에 속지 않음


def test_tool_results_fit_budget_without_touching_state():
    """도구 결과 총량을 예산 안으로: 최근 결과는 그대로, 오래된 결과는 앞부분만. 원본 상태는 그대로."""
    from langchain_core.messages import HumanMessage, ToolMessage

    from rdagents.agents.utils.agent_utils import fit_tool_messages

    msgs = [HumanMessage(content="시작")] + [
        ToolMessage(content=f"[결과{i}]" + "가" * 2000, tool_call_id=f"t{i}") for i in range(4)
    ]
    assert fit_tool_messages(msgs, {"tool_result_char_budget": 0}) is msgs     # 0이면 그대로
    fitted = fit_tool_messages(msgs, {"tool_result_char_budget": 3500})
    assert fitted[-1].content == msgs[-1].content                             # 가장 최근 결과는 온전히
    assert all("요청 크기 예산" in m.content for m in fitted[1:3])          # 오래된 결과는 줄임
    assert fitted[1].content.startswith("[결과0]")                           # 앞부분은 남김
    assert all(len(m.content) == 2005 for m in msgs[1:])                     # 상태의 원본은 그대로
    assert sum(len(m.content) for m in fitted[1:]) < 2005 * 4 * 0.6

def test_analyst_tool_call_cap(monkeypatch):
    """도구 결과가 상한에 이르면 도구 없이(바인딩 안 함) 보고서 작성을 지시한다. 도구 호출·결과는 글로 펼친다.
    상태에 값이 없으면(설정 추가 전 체크포인트) 환경변수를 읽는다."""
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    from rdagents.agents.utils.agent_utils import TOOL_LIMIT_NOTE, bind_analyst_tools

    class Recorder:
        def bind_tools(self, tools, **kwargs):
            return ("bound", kwargs)

    llm = Recorder()
    call = AIMessage(content="", tool_calls=[{"name": "search_report", "args": {"query": "예산"}, "id": "t0"}])
    two = [HumanMessage(content="시작"), call] + [
        ToolMessage(content="결과", tool_call_id=f"t{i}", name="search_report") for i in range(2)
    ]
    three = two + [ToolMessage(content="결과", tool_call_id="t2", name="search_report")]

    model, msgs = bind_analyst_tools(llm, [], {"messages": two, "max_analyst_tool_calls": 3})
    assert model == ("bound", {}) and msgs[-1].content == "결과"            # 아직 상한 전
    model, msgs = bind_analyst_tools(llm, [], {"messages": three, "max_analyst_tool_calls": 3})
    assert model is llm and msgs[-1].content == TOOL_LIMIT_NOTE             # 도구 없이 호출
    assert not any(isinstance(m, ToolMessage) or getattr(m, "tool_calls", None) for m in msgs)
    assert "[도구 결과: search_report]" in msgs[2].content and "search_report" in msgs[1].content
    model, _ = bind_analyst_tools(llm, [], {"messages": three, "max_analyst_tool_calls": 0})
    assert model == ("bound", {})                                           # 0이면 무제한

    monkeypatch.setenv("RDAGENTS_MAX_ANALYST_TOOL_CALLS", "3")
    model, _ = bind_analyst_tools(llm, [], {"messages": three})             # 상태에 값 없음 -> 환경변수
    assert model is llm

def test_explicit_env_beats_profile(monkeypatch):
    """프로파일보다 사용자가 직접 준 RDAGENTS_* 환경변수가 우선 (요청 초과 안내대로 조각만 줄여 재실행 가능)."""
    import main

    captured = {}

    class Graph:
        def __init__(self, config=None, debug=False):
            captured.update(config or {})
            self.config = {**captured}

        def propagate(self, **kwargs):
            raise RuntimeError("stop")

        def close(self):
            pass

    monkeypatch.setattr(main, "RDReviewGraph", Graph)
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setenv("RDAGENTS_REPORT_CHUNK_CHARS", "600")
    monkeypatch.setattr(sys, "argv", ["main.py", "--profile", "test-groq"])
    assert main.main() == 1
    assert "report_chunk_chars" not in captured            # 환경변수 값(600)이 DEFAULT_CONFIG로 들어가게 둠
    assert captured["report_retrieval_top_k"] == 2         # 환경변수로 안 준 값은 프로파일 그대로


def test_daily_quota_stops_retries_immediately(monkeypatch):
    """하루 한도면 클라이언트 재시도(3초·6초)와 구조화 출력 재시도를 하지 않고 바로 올린다."""
    import httpx
    import pytest
    from langchain_openai import ChatOpenAI
    from openai import RateLimitError

    from rdagents.agents.schemas import ReviewPlan
    from rdagents.agents.utils.structured import invoke_structured_model
    from rdagents.llm_clients.openai_client import NormalizedChatOpenAI
    from rdagents.llm_clients.quota import DailyQuotaExceeded

    calls = {"n": 0}
    response = httpx.Response(429, request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"))

    def always_daily_limit(self, *args, **kwargs):
        calls["n"] += 1
        raise RateLimitError(GROQ_TPD_MESSAGE, response=response, body=None)

    monkeypatch.setattr(ChatOpenAI, "invoke", always_daily_limit)
    monkeypatch.setattr("time.sleep", lambda s: pytest.fail("하루 한도인데 재시도 대기함"))
    llm = NormalizedChatOpenAI(model="openai/gpt-oss-120b", api_key="test", base_url="https://api.groq.com/openai/v1")
    with pytest.raises(DailyQuotaExceeded):
        llm.invoke("hi")
    assert calls["n"] == 1

    class Raising:
        def __init__(self):
            self.n = 0

        def with_structured_output(self, schema, include_raw=False):
            return self

        def invoke(self, _messages):
            self.n += 1
            raise DailyQuotaExceeded(GROQ_TPD_MESSAGE, "10m")

    fake = Raising()
    with pytest.raises(DailyQuotaExceeded):
        invoke_structured_model(fake, ReviewPlan, "prompt", "Review Manager")
    assert fake.n == 1  # 구조화 출력 재시도(최대 3회)도 하지 않음


def test_plan_precheck_rules():
    from rdagents.dataflows.plan_precheck import check_lines, precheck_brief, run_precheck

    lines = [
        "<!-- p.2 -->",
        "## 1. 추진 배경",
        "- 최근 5년간 온열질환자가 증가 추세이다.",          # 수치 없는 시급성 -> 근거 약함
        "- 민간 기업은 투자 유인이 적어 정부 지원이 필요하다.",
        "- 총 사업비: 120억 원, 비목별 단가 산출 근거 별첨",
        "- 실증 이후 운영 주체는 사업 착수 후 협의한다.",   # 미정 표현 -> 근거 약함
        "「재난 및 안전관리 기본법 시행령」 제3조의2(재난관리주관기관)",  # 법령 용어는 추진체계 아님
    ]
    status = {r.item.key: r.status for r in check_lines(lines)}
    assert status["urgency"] == "근거 약함" and status["operation"] == "근거 약함"
    assert status["gov_support"] == "충족" and status["budget"] == "충족"
    assert status["governance"] == "누락" and status["novelty"] == "누락"
    brief = precheck_brief(check_lines(lines), "a.md")
    assert "[시급성] 시급성의 정량 근거 — 근거 약함" in brief and "[출처: a.md L3-L3] (p.2)" in brief
    assert "추진 배경" not in brief                            # 충족 항목은 요약에서 뺀다 (토큰 절약)
    assert run_precheck(None, None) == ("", "")                # 샘플 JSON 모드면 점검 안 함
    # 다른 표현의 배경·목표 (근거 파일이 나뉜 보고서에서 누락으로 나왔던 표현)
    other = ["## 1. 추진 목적과 핵심 문제", "- 최종성과물: 시제품 3종",
             "- 대응시간: 2년차 대비 4년차 15% 단축 목표"]
    status = {r.item.key: r.status for r in check_lines(other)}
    assert status["background"] == "충족" and status["goal_kpi"] == "충족"

    # 근거 파일(--evidence)도 함께 본다: 주 보고서에 없고 근거 파일에만 있는 항목은 누락이 아니고, 근거 줄은 그 파일로 인용
    from rdagents.dataflows.plan_precheck import precheck_issues
    main_text = "## 사업 개요\n- 총 사업비 120억 원\n"
    evidence = {"04_중복검토.md": "## 유사·중복 검토\n- 기존 사업과 차별화된다\n"}
    alone = {r["issue"].split(" ")[0] for r in precheck_issues(main_text, "a.md")}
    joined = precheck_issues(main_text, "a.md", evidence=evidence)
    assert "기술" in alone and not any(i["issue"].startswith("기술 차별성") for i in joined)
    full, _ = run_precheck(main_text, "a.md", evidence=evidence)
    assert "+ 근거 파일 1개 (`04_중복검토.md`)" in full and "[출처: 04_중복검토.md L1-L1]" in full


def test_panel_asks_one_ledger_issue_and_stops_when_done():
    """패널은 쟁점 원장에서 쟁점 하나를 골라 담당 위원으로 질의한다. 원문의 중괄호가 템플릿을 깨지 않고,
    상정할 쟁점이 없으면 LLM을 부르지 않고 공방을 끝낸다."""
    from rdagents.agents.researchers.panel_examiner import create_panel_examiner
    from rdagents.dataflows.issue_ledger import build_ledger

    seen = {}

    class Capture:
        def invoke(self, prompt_val):
            seen["text"] = prompt_val.to_string()
            return AIMessage(content="[가짜 질의]")

    ledger = build_ledger([], [{"issue": "시급성의 정량 근거 근거 약함 {중괄호 포함 원문}", "criterion": "시급성",
                                "severity": "중", "origin": "사전 점검 (근거 약함)", "cite": "", "quote": "",
                                "verified": True, "verify_note": "코드 점검"}], "공공임무형")
    debate = {"examiner_history": "", "defender_history": "", "history": "", "count": 0, "current_response": ""}
    out = create_panel_examiner(Capture())({"issue_ledger": ledger, "project_type": "공공임무형",
                                            "review_debate_state": debate})
    assert "{중괄호 포함 원문}" in seen["text"] and "재난안전 정책위원" in seen["text"]
    assert out["issue_ledger"][0]["status"] == "공방 중" and out["review_debate_state"]["current_response"] == "Examiner"
    assert "[심사위원 패널 · 재난안전 정책위원] (쟁점 #1, 시급성" in out["review_debate_state"]["history"]
    seen.clear()
    done = create_panel_examiner(Capture())({"issue_ledger": [{**ledger[0], "status": "방어 실패"}],
                                             "review_debate_state": debate})
    assert done["review_debate_state"]["current_response"] == "Done" and not seen   # LLM 호출 없음


def test_issue_ledger_verifies_citations_orders_debate_and_judges_defense(tmp_path):
    """쟁점 원장: 출처를 원문과 대조하고, 반드시 올릴 쟁점부터 상정하고, 발표자 답변의 출처·인용·수치로 방어를 판정하고,
    방어 실패한 3대 기준 '상' 쟁점이 남으면 '승인'을 거부한다."""
    import pytest

    from rdagents.agents.researchers.project_defender import judge_defense
    from rdagents.agents.schemas import DefenseAnswer
    from rdagents.dataflows.issue_ledger import (
        build_ledger, check_decision_against_ledger, next_issue, render_ledger, verify_citation,
    )
    from rdagents.dataflows.project_loader import set_current_report

    report = tmp_path / "원문.md"
    report.write_text("총사업비 120억 원\n최근 5년 풍수해 사망 6명\n수요기관: 시·도 재난안전대책본부\n", encoding="utf-8")
    set_current_report(str(report), project_id="ledger")
    assert verify_citation("[출처: 원문.md L2-L2]", "풍수해 사망 6명") == (True, "원문 대조 일치")
    assert verify_citation("[출처: 원문.md L2-L2]", "피해액 1,200억 원")[1] == "인용 구절이 그 줄에 없음"
    assert verify_citation("[출처: 원문.md L9-L9]", "")[0] is False                   # 없는 줄
    assert verify_citation("", "", require_quote=True)[0] is False

    # 등록기에는 긴 출처 대신 번호(R1…)를 보여 주고, 등록기가 적은 번호를 코드가 출처로 되돌린다
    from rdagents.dataflows.issue_ledger import cited_claims, resolve_refs
    claims = cited_claims("## 요약\n- 사망 통계 근거가 약함 [출처: 원문.md L2-L2]\n출처 없는 의견\n", start=4)
    assert claims == [{"ref": "R4", "claim": "사망 통계 근거가 약함", "cite": "[출처: 원문.md L2-L2]"}]
    assert [r["cite"] for r in resolve_refs([{"cite": "R4"}, {"cite": "R9"}, {"cite": ""}], claims)] == [
        "[출처: 원문.md L2-L2]", "R9", ""]

    registered = [
        {"issue": "중요성 근거 약함", "criterion": "기술개발의 중요성", "severity": "하", "source_report": "기술 가치 분석",
         "cite": "", "quote": ""},
        {"issue": "시급성 수치 근거", "criterion": "시급성", "severity": "상", "source_report": "정책 부합성 분석",
         "cite": "[출처: 원문.md L2-L2]", "quote": "사망 6명"},
        {"issue": "지어낸 출처", "criterion": "정부지원 필요성", "severity": "상", "source_report": "규제/윤리 검토",
         "cite": "[출처: 원문.md L3-L3]", "quote": "민간 투자 0원"},
    ]
    code = [{"issue": "예산 산출 근거 누락", "criterion": "예산 타당성", "severity": "상", "origin": "사전 점검 (누락)",
             "cite": "", "quote": "", "verified": True, "verify_note": "코드 점검"}]
    ledger = build_ledger(registered, code, "공공임무형")
    assert [i["verified"] for i in ledger] == [True, False, True, False]   # 코드 쟁점, 출처 없음, 검증, 지어낸 인용
    assert ledger[3]["member"] == "법·제도위원" and ledger[0]["member"] == "재정위원"
    order = []
    for _ in range(4):
        item = next_issue(ledger, max_issues=2)
        if item is None:
            break
        order.append(item["id"])
        item["status"] = "방어 실패"
    assert order == [1, 3]           # 반드시 올릴 쟁점 2개(예산 누락, 검증된 시급성 '상')로 상한 2를 채움

    # 방어 판정: 근거 없음 인정 / 인용 불일치 / 원문에 없는 수치 -> 실패, 원문과 맞으면 성공
    ok = DefenseAnswer(supported=True, answer="최근 5년 사망 6명입니다.", cite="[출처: 원문.md L2-L2]", quote="사망 6명")
    assert judge_defense(ok)[0] == "방어 성공"
    assert judge_defense(DefenseAnswer(supported=False, answer="제출자료로 확인하지 못했습니다."))[0] == "방어 실패"
    assert "인용 구절" in judge_defense(ok.model_copy(update={"quote": "사망 60명"}))[1]
    fabricated = ok.model_copy(update={"answer": "사망 6명, 연간 피해 1,200억 원입니다."})
    assert judge_defense(fabricated) == ("방어 실패", "원문에 없는 수치로 방어: 1200억")

    with pytest.raises(ValueError, match="#3 시급성"):
        check_decision_against_ledger("승인", ledger)
    check_decision_against_ledger("조건부승인", ledger)            # 조건부승인 이하는 통과
    table = render_ledger(ledger)
    assert "방어 실패 2 · 공방 미상정 2" in table and "인용 구절이 그 줄에 없음" in table


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
    bank_dir = tmp / "bank"
    fake = FakeLLM()
    md, stats = verify_questions(
        fake, run_dir, "1. 실제 질의1\n2. 실제 질의2", str(history),
        question_bank_dir=str(bank_dir),
    )

    assert stats == {"total": 2, "hits": 1, "partials": 0, "misses": 1,
                     "weighted_hit_rate": 50.0}, stats
    assert (run_dir / "13_질의적중검증.md").exists()
    assert "가중 적중률" in md
    lines = history.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["weighted_hit_rate"] == 50.0

    # 검증된 실제 질의가 질의 은행에 축적되는지 확인
    bank_files = list(bank_dir.glob("실제질의_*.md"))
    assert len(bank_files) == 1, "실제 질의가 은행에 축적되지 않음"
    assert "실제 질의1" in bank_files[0].read_text(encoding="utf-8")

    # 2회차 검증 시 이력이 누적되는지 확인
    verify_questions(fake, run_dir, "1. 실제 질의1\n2. 실제 질의2", str(history))
    assert len(history.read_text(encoding="utf-8").strip().splitlines()) == 2
    print("=== 질의 적중 검증 테스트 통과 ===")


def run_hearing_rehearsal():
    """모의 청문: 스크립트 입력으로 답변→평가→압박 후속질의→기록 저장을 검증."""
    import tempfile

    from rdagents.agents.schemas import ReviewPreparationReport
    from rdagents.hearing import run_hearing

    run_dir = Path(tempfile.mkdtemp(prefix="rdagents_hearing_"))
    prediction = _default_instance(ReviewPreparationReport)
    (run_dir / "07b_예상질의.json").write_text(prediction.model_dump_json(), encoding="utf-8")

    inputs = iter([
        "정부지원이 필요한 이유는 시장실패 때문입니다.",  # 질의1 답변
        "",                                              # 질의1 후속 답변 생략
        "q",                                             # 질의2에서 종료
    ])
    printed = []
    out_path = run_hearing(
        FakeLLM(), run_dir,
        input_fn=lambda _prompt: next(inputs),
        print_fn=printed.append,
    )

    assert out_path.exists()
    transcript = out_path.read_text(encoding="utf-8")
    assert "평가 점수" in transcript, "평가가 기록되지 않음"
    assert "압박 후속질의" in transcript
    assert "(사용자 종료)" in transcript
    assert any("위원:" in line for line in printed), "질의가 출력되지 않음"
    print("=== 모의 청문 테스트 통과 ===")


def test_question_verification():
    run_question_verification()
    run_hearing_rehearsal()


def test_hearing_rehearsal():
    run_hearing_rehearsal()


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



def test_token_estimate_counts_calls_without_api():
    """추정기는 API 없이 그래프를 끝까지 돌려 노드별 호출을 세고, 도구 상한·체크포인트 진행을 반영한다."""
    import tempfile

    from rdagents.dataflows import token_estimate as te
    from rdagents.default_config import DEFAULT_CONFIG

    root = Path(tempfile.mkdtemp(prefix="rdagents_est_"))
    config = {**DEFAULT_CONFIG, "checkpoint_path": str(root / "none.sqlite"), "prompt_char_budget": 1200,
              "max_analyst_tool_calls": 2}
    est = te.estimate(config, dict(project_id="quantum_computing"))
    nodes = {c.node for c in est.calls}
    assert {"Tech Value Analyst", "Panel Examiner", "Final Approver", "Question Extractor"} <= nodes
    tech = [c.kind for c in est.calls if c.node == "Tech Value Analyst"]
    assert tech == ["도구 턴", "도구 턴", "보고서"]                 # 상한 2 -> 도구 2번 뒤 보고서
    assert all(c.input_tokens > 0 for c in est.calls) and not est.skipped
    assert not any(c.retry for c in est.calls)                      # 가짜 응답이 검증을 통과 (재시도 없음)
    assert [c.kind for c in est.calls if c.node == "Final Approver"] == ["구조화"]
    out = te.render(est, tpm=8000, tpd=200000)
    assert "남은 호출" in out and "출력 상한 3,072" in out           # 요청 크기 = 입력 + 출력 상한 (Groq 방식)
    assert "분당 한도 100,000 안" in te.render(est, tpm=100000, tpd=200000)
    assert "⛔" in te.render(est, tpm=3000, tpd=200000)              # 분당 한도보다 큰 요청 표시

    # 체크포인트: 보고서가 저장된 분석가와 이미 실행된 노드는 남은 부분에서 뺀다
    state = {"tech_value_report": "끝", "execution_metrics": [{"node": "Panel Examiner", "total_tokens": 10}]}
    done = te._done(est.calls, state)
    skipped = {c.node for c, d in zip(est.calls, done) if d}
    assert skipped == {"Tech Value Analyst", "Panel Examiner"}
    assert sum(d for c, d in zip(est.calls, done) if c.node == "Panel Examiner") == 1   # 2번 중 1번만 끝남


def test_truncated_response_is_marked():
    """출력 한도에서 끊긴 글 응답에는 잘림 표시, 구조화 출력·도구 호출은 그대로 둔다."""
    from rdagents.llm_clients.openai_client import TRUNCATED_NOTE, mark_truncated

    cut = AIMessage(content="연쇄 영향 분석 엔진은 학제", response_metadata={"finish_reason": "length"})
    assert mark_truncated(cut, {}).content.endswith(TRUNCATED_NOTE)
    done = AIMessage(content="완결된 보고서.", response_metadata={"finish_reason": "stop"})
    assert mark_truncated(done, {}).content == "완결된 보고서."
    js = AIMessage(content='{"verdict": "승', response_metadata={"finish_reason": "length"})
    assert mark_truncated(js, {"response_format": {}}).content == '{"verdict": "승'

if __name__ == "__main__":
    run_smoke()
    run_report_mode_and_memory()
    run_checkpoint_and_observability()
    run_parallel_context_isolation()
    run_checkpoint_resume()
    run_question_verification()
    run_hearing_rehearsal()
