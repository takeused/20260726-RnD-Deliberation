# 모의 청문 모드 — 예상 질의를 하나씩 던지고 사용자의 답변을 평가·압박하는 대화형 리허설
"""실제 심의는 문서 심사가 아니라 실시간 질의응답이다. 이 모듈은 이전 심의 실행의
예상 질의(07b_예상질의.json)를 심의위원처럼 순서대로 던지고, 사용자가 입력한 답변을
평가한 뒤 압박 후속질의를 제시한다. 전 과정은 실행 디렉터리에 기록된다.

LangGraph를 쓰지 않는 이유: stdin 기반 단순 순차 대화라 그래프 오케스트레이션이 불필요.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from rdagents.agents.schemas import ReviewPreparationReport
from rdagents.agents.utils.structured import invoke_structured_model


class AnswerEvaluation(BaseModel):
    """사용자 답변 1건에 대한 심의위원 관점 평가."""

    score: float = Field(ge=0, le=100, description="답변 설득력 점수(0~100). 심의위원 관점.")
    strengths: str = Field(description="답변에서 좋았던 점 1~2가지.")
    weaknesses: str = Field(description="심의위원이 미흡하다고 느낄 지점 1~2가지.")
    follow_up_question: str = Field(
        description="이 답변을 들은 심의위원이 이어서 던질 압박 후속질의 1개.",
    )
    model_answer_hint: str = Field(
        description="더 나은 답변의 핵심 골격 (근거·수치·인정과 보완 계획 구조).",
    )


def _load_questions(run_dir: Path) -> list:
    json_path = run_dir / "07b_예상질의.json"
    if not json_path.exists() or not json_path.read_text(encoding="utf-8").strip():
        raise FileNotFoundError(
            f"예상 질의 JSON이 없습니다: {json_path}\n"
            "먼저 심의 시뮬레이션을 실행해 예상 질의를 생성하세요."
        )
    report = ReviewPreparationReport(**json.loads(json_path.read_text(encoding="utf-8")))
    return report.questions


def run_hearing(llm, run_dir: str | Path, input_fn=input, print_fn=print) -> Path:
    """모의 청문을 진행하고 기록 파일 경로를 반환.

    input_fn/print_fn은 테스트에서 대화를 주입하기 위한 훅.
    답변 입력에서 'q' 입력 시 종료, 빈 입력 시 해당 질의 건너뜀.
    """
    run_dir = Path(run_dir)
    questions = _load_questions(run_dir)

    eval_prompt = ChatPromptTemplate.from_messages([
        ("system",
         "당신은 R&D 예산 심의위원입니다. 발표자의 답변을 심의위원 관점에서 냉정하게 평가하세요. "
         "근거·수치 없는 수사는 낮게, 솔직한 인정과 구체적 보완 계획은 높게 평가합니다. "
         "모든 출력은 한국어로 작성하세요."),
        ("human",
         "## 심의 질의\n{question}\n\n"
         "## 질의 배경 (모의 심의에서 드러난 취약점)\n{basis}\n\n"
         "## 발표자의 답변\n{answer}\n\n"
         "이 답변을 평가하고 압박 후속질의를 제시하세요."),
    ])

    transcript = [
        "# 모의 청문 기록",
        "",
        f"- 일시: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"- 대상 실행: {run_dir}",
        f"- 질의 수: {len(questions)}",
        "",
    ]

    print_fn(f"\n=== 모의 청문 시작 (질의 {len(questions)}건, 'q' 입력 시 종료, 빈 입력 시 건너뜀) ===\n")

    for i, q in enumerate(questions, 1):
        print_fn(f"[질의 {i}/{len(questions)}] ({q.criterion.value} / 심각도 {q.severity.value})")
        print_fn(f"위원: {q.question}\n")
        answer = input_fn("답변 > ").strip()

        transcript.extend([f"## 질의 {i}. {q.question}",
                           f"- 심의기준: {q.criterion.value} / 심각도: {q.severity.value}", ""])

        if answer.lower() == "q":
            transcript.append("(사용자 종료)")
            print_fn("\n청문을 종료합니다.")
            break
        if not answer:
            transcript.extend(["(건너뜀)", ""])
            print_fn("건너뜁니다.\n")
            continue

        transcript.extend([f"**답변**: {answer}", ""])

        prompt_val = eval_prompt.invoke({
            "question": q.question, "basis": q.basis, "answer": answer,
        })
        call = invoke_structured_model(llm, AnswerEvaluation, prompt_val, "Hearing Evaluator")
        if call.model is None:
            feedback_text = llm.invoke(prompt_val).content
            print_fn(f"\n[평가]\n{feedback_text}\n")
            transcript.extend(["**평가 (자유 형식)**:", feedback_text, ""])
            continue

        ev = call.model
        print_fn(f"\n[평가] {ev.score:.0f}점")
        print_fn(f"- 좋았던 점: {ev.strengths}")
        print_fn(f"- 미흡한 점: {ev.weaknesses}")
        print_fn(f"- 권장 답변 골격: {ev.model_answer_hint}")
        print_fn(f"\n위원(압박): {ev.follow_up_question}\n")
        follow_answer = input_fn("후속 답변 (Enter로 다음 질의) > ").strip()

        transcript.extend([
            f"**평가 점수**: {ev.score:.0f}/100",
            f"- 강점: {ev.strengths}",
            f"- 약점: {ev.weaknesses}",
            f"- 권장 골격: {ev.model_answer_hint}",
            f"- 압박 후속질의: {ev.follow_up_question}",
            f"- 후속 답변: {follow_answer or '(생략)'}",
            "",
        ])
        if follow_answer.lower() == "q":
            print_fn("\n청문을 종료합니다.")
            break

    out_path = run_dir / f"모의청문_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    out_path.write_text("\n".join(transcript), encoding="utf-8")
    print_fn(f"\n청문 기록 저장: {out_path}")
    return out_path
