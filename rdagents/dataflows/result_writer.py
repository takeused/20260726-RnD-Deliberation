# 심의 결과 전체(분석 보고서·토론 전문·최종 결정·예상 질의)를 디스크에 저장하는 모듈
"""저장 구조: {results_dir}/{project_id}/{YYYYMMDD_HHMMSS}/NN_*.md"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from rdagents.agents.schemas import (
    BudgetProposal,
    FinalDecision,
    ReviewPlan,
    render_budget_proposal,
    render_final_decision,
    render_review_plan,
)

_ANALYST_FILES = [
    ("tech_value_report", "01a_분석_기술가치.md"),
    ("tech_trend_report", "01b_분석_기술트렌드중복성.md"),
    ("economic_report", "01c_분석_경제재무.md"),
    ("policy_report", "01d_분석_정책부합성.md"),
    ("feasibility_report", "01e_분석_수행체계.md"),
    ("regulatory_report", "01f_분석_규제윤리.md"),
]


def _render_json_field(raw: str, schema, renderer) -> str:
    """상태에 JSON으로 저장된 구조화 산출물을 마크다운으로 복원. 실패 시 원문 그대로."""
    try:
        return renderer(schema(**json.loads(raw)))
    except Exception:
        return raw


def save_results(final_state: dict, results_dir: str, project_id: str) -> Path:
    """심의 전 과정을 마크다운 파일로 저장하고 저장 디렉터리 경로를 반환."""
    run_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}-{uuid4().hex[:8]}"
    out_dir = Path(results_dir) / project_id / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    def write(filename: str, content: str) -> None:
        (out_dir / filename).write_text(content or "(내용 없음)", encoding="utf-8")

    write("00_입력문서_출처.md", final_state.get("source_manifest", ""))

    for key, filename in _ANALYST_FILES:
        write(filename, final_state.get(key, ""))

    write("02_심사공방_전문.md", final_state.get("review_debate_state", {}).get("history", ""))
    write(
        "03_전문위원회_의견.md",
        _render_json_field(final_state.get("review_plan", ""), ReviewPlan, render_review_plan),
    )
    write(
        "04_예산조정안.md",
        _render_json_field(
            final_state.get("budget_coordination_plan", ""), BudgetProposal, render_budget_proposal
        ),
    )
    write("05_재정검토토론_전문.md", final_state.get("audit_debate_state", {}).get("history", ""))
    write(
        "06_최종결정.md",
        _render_json_field(
            final_state.get("final_review_decision", ""), FinalDecision, render_final_decision
        ),
    )
    write("07_예상질의응답.md", final_state.get("anticipated_questions_md", ""))
    write("07b_예상질의.json", final_state.get("preparation_report_json", ""))
    write("08_보완권고.md", final_state.get("improvement_recommendations_md", ""))
    write("09_정량평가표.md", final_state.get("quality_scorecard_md", ""))
    write("10_불확실성_반대근거.md", final_state.get("uncertainty_report_md", ""))
    write("11_재심의_전후비교.md", final_state.get("rereview_comparison_md", ""))

    metadata = final_state.get("execution_metadata", {})
    metrics = final_state.get("execution_metrics", [])
    total_seconds = sum(item.get("elapsed_seconds", 0) for item in metrics)
    total_tokens = sum(item.get("total_tokens", 0) for item in metrics)
    observation = [
        "# 실행 관측성",
        "",
        f"- **실행 ID**: {metadata.get('execution_id', '알 수 없음')}",
        f"- **프로바이더**: {metadata.get('provider', '알 수 없음')}",
        f"- **Deep 모델**: {metadata.get('deep_model', '알 수 없음')}",
        f"- **Quick 모델**: {metadata.get('quick_model', '알 수 없음')}",
        f"- **체크포인트**: {'활성' if metadata.get('checkpoint_enabled') else '비활성'}",
        f"- **노드 누적시간**: {total_seconds:.4f}초",
        f"- **보고된 총 토큰**: {total_tokens:,}",
        "- **비용**: 모델별·시점별 가격표를 설정하지 않아 계산하지 않음",
        "",
        "| 노드 | 모델 | 시간(초) | 입력 토큰 | 출력 토큰 | 총 토큰 |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for item in metrics:
        observation.append(
            f"| {item.get('node')} | {item.get('model')} | "
            f"{item.get('elapsed_seconds', 0):.4f} | {item.get('input_tokens', 0)} | "
            f"{item.get('output_tokens', 0)} | {item.get('total_tokens', 0)} |"
        )
    write("12_실행관측성.md", "\n".join(observation))

    return out_dir
