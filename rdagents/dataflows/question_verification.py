# 실제 심의 질의를 예측 질의와 대조해 적중률을 계산·누적 기록하는 사후 검증 모듈
"""시뮬레이터 품질의 나침반: 실제 심의 후 받은 질의를 입력하면
해당 실행의 예측 질의(07b_예상질의.json)와 의미 단위로 대조하고,
적중률을 이력(jsonl)에 누적해 회차별 추세를 추적할 수 있게 한다.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate

from rdagents.agents.schemas import (
    QuestionVerificationReport,
    ReviewPreparationReport,
    compute_hit_stats,
    render_verification_report,
)
from rdagents.agents.utils.structured import invoke_structured_model


def load_predictions_text(run_dir: str | Path) -> str:
    """실행 디렉터리에서 예측 질의 목록을 텍스트로 로드."""
    run_dir = Path(run_dir)
    json_path = run_dir / "07b_예상질의.json"
    if json_path.exists() and json_path.read_text(encoding="utf-8").strip():
        report = ReviewPreparationReport(**json.loads(json_path.read_text(encoding="utf-8")))
        return "\n".join(
            f"{i}. [{q.criterion.value}/{q.severity.value}] {q.question}"
            for i, q in enumerate(report.questions, 1)
        )
    md_path = run_dir / "07_예상질의응답.md"
    if md_path.exists():
        # 구조화 저장이 없던 실행(폴백 등)은 마크다운 원문으로 대조
        return md_path.read_text(encoding="utf-8")
    raise FileNotFoundError(f"예측 질의 산출물을 찾을 수 없습니다: {run_dir}")


def verify_questions(
    llm,
    run_dir: str | Path,
    actual_questions_text: str,
    history_path: str,
) -> tuple[str, dict]:
    """실제 질의를 예측과 대조하고 (마크다운 보고서, 적중률 통계)를 반환.

    보고서는 run_dir/13_질의적중검증.md 로 저장되고,
    통계는 history_path(jsonl)에 1줄 append 된다.
    """
    run_dir = Path(run_dir)
    predictions_text = load_predictions_text(run_dir)

    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "당신은 R&D 심의 질의 예측의 적중 여부를 판정하는 감사자입니다. "
         "실제 질의 각각에 대해 예측 목록과 의미 단위로 대조하세요. "
         "적중 = 같은 논점과 공격 각도를 예측함. 부분적중 = 주제는 겹치나 핵심 각도가 다름. "
         "미적중 = 예측에 없던 질의. 관대하게 판정하지 말고, 실제 질의를 하나도 빠뜨리지 마세요. "
         "모든 출력은 한국어로 작성하세요."),
        ("human",
         "## 시뮬레이션이 예측한 질의 목록\n\n{predictions}\n\n"
         "## 실제 심의에서 받은 질의\n\n{actuals}\n\n"
         "실제 질의 1건당 1개 항목으로 판정하고, 미적중 질의들의 공통 주제를 요약하세요."),
    ])
    prompt_val = prompt.invoke({
        "predictions": predictions_text,
        "actuals": actual_questions_text,
    })

    call = invoke_structured_model(
        llm, QuestionVerificationReport, prompt_val, "Question Verifier"
    )
    if call.model is None:
        raise RuntimeError("질의 대조 구조화 출력에 실패했습니다. 다시 실행해 주세요.")

    stats = compute_hit_stats(call.model)
    md = render_verification_report(call.model, stats)
    (run_dir / "13_질의적중검증.md").write_text(md, encoding="utf-8")

    history_file = Path(history_path)
    history_file.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "run_dir": str(run_dir),
        **stats,
    }
    with open(history_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    return md, stats
