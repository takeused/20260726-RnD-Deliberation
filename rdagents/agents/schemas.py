"""R&D 예산 심의 에이전트 출력 스키마.

TradingAgents의 schemas.py 패턴을 기반으로 심의 전용 스키마를 정의합니다.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator


def _coerce_str(value):
    """소형 모델이 문자열 필드에 리스트를 반환하는 흔한 오류를 자동 교정."""
    if isinstance(value, list):
        return "\n".join(f"- {item}" for item in value)
    return value


# ---------------------------------------------------------------------------
# 심의 결정 등급
# ---------------------------------------------------------------------------

class ReviewVerdict(str, Enum):
    """5단계 예산 심의 결정."""
    APPROVE = "승인"
    CONDITIONAL_APPROVE = "조건부승인"
    REDUCE = "감액조정"
    DEFER = "보류"
    REJECT = "반려"


# ---------------------------------------------------------------------------
# 전문위원회 위원장 출력
# ---------------------------------------------------------------------------

class ReviewPlan(BaseModel):
    """전문위원회 위원장이 찬반 토론을 종합하여 생성하는 심의 의견."""

    verdict: ReviewVerdict = Field(
        description=(
            "심의 의견. 승인 / 조건부승인 / 감액조정 / 보류 / 반려 중 하나. "
            "양측 논거의 강도를 기반으로 결정."
        ),
    )
    rationale: str = Field(
        description=(
            "찬반 양측 핵심 논거를 요약하고, 최종 의견의 근거를 설명. "
            "자연스러운 대화체로 작성."
        ),
    )
    key_concerns: str = Field(
        description="향후 해결이 필요한 핵심 우려사항 또는 조건.",
    )

    @field_validator("key_concerns", "rationale", mode="before")
    @classmethod
    def coerce_text_fields(cls, value):
        return _coerce_str(value)


def render_review_plan(plan: ReviewPlan) -> str:
    return "\n".join([
        f"**심의 의견**: {plan.verdict.value}",
        "",
        f"**종합 근거**: {plan.rationale}",
        "",
        f"**핵심 우려사항**: {plan.key_concerns}",
    ])


# ---------------------------------------------------------------------------
# 예산 조정관 출력
# ---------------------------------------------------------------------------

class BudgetAction(str, Enum):
    """예산 조정 방향."""
    FULL_APPROVE = "원안통과"
    INCREASE = "증액"
    REDUCE = "감액"
    DEFER = "보류"
    REJECT = "반려"


class BudgetProposal(BaseModel):
    """예산 조정관이 위원장 의견을 기반으로 생성하는 예산 조정안."""

    action: BudgetAction = Field(
        description="예산 조정 방향. 원안통과 / 증액 / 감액 / 보류 / 반려 중 하나.",
    )
    reasoning: str = Field(
        description="예산 조정의 근거. 2~4문장으로 핵심만 기술.",
    )
    original_budget_billion: float = Field(
        ge=0,
        description="원래 요청 예산 (억원).",
    )
    proposed_budget_billion: float | None = Field(
        default=None,
        ge=0,
        description="조정 후 제안 예산 (억원). 보류/반려 시 None.",
    )
    conditions: str | None = Field(
        default=None,
        description="조건부 통과 시 이행 조건.",
    )

    @field_validator("conditions", "reasoning", mode="before")
    @classmethod
    def coerce_text_fields(cls, value):
        return _coerce_str(value)

    @model_validator(mode="after")
    def validate_budget_action(self):
        """예산 조정 방향과 금액·조건 사이의 모순을 차단한다."""
        proposed = self.proposed_budget_billion
        original = self.original_budget_billion

        if self.action in {BudgetAction.DEFER, BudgetAction.REJECT}:
            if proposed not in (None, 0):
                raise ValueError("보류/반려의 제안 예산은 None 또는 0이어야 합니다.")
        elif proposed is None:
            raise ValueError("원안통과/증액/감액에는 조정 후 제안 예산이 필요합니다.")
        elif self.action == BudgetAction.FULL_APPROVE and proposed != original:
            raise ValueError("원안통과의 제안 예산은 원래 요청 예산과 같아야 합니다.")
        elif self.action == BudgetAction.INCREASE and proposed <= original:
            raise ValueError("증액의 제안 예산은 원래 요청 예산보다 커야 합니다.")
        elif self.action == BudgetAction.REDUCE and proposed >= original:
            raise ValueError("감액의 제안 예산은 원래 요청 예산보다 작아야 합니다.")
        return self


def render_budget_proposal(proposal: BudgetProposal) -> str:
    parts = [
        f"**예산 조정 방향**: {proposal.action.value}",
        "",
        f"**조정 근거**: {proposal.reasoning}",
        "",
        f"**원래 요청 예산**: {proposal.original_budget_billion}억원",
    ]
    if proposal.proposed_budget_billion is not None:
        parts.extend(["", f"**조정 후 제안 예산**: {proposal.proposed_budget_billion}억원"])
        ratio = (proposal.proposed_budget_billion / proposal.original_budget_billion * 100
                 if proposal.original_budget_billion else 0)
        parts.append(f"**반영률**: {ratio:.1f}%")
    if proposal.conditions:
        parts.extend(["", f"**이행 조건**: {proposal.conditions}"])
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 최종 심의위원장 출력
# ---------------------------------------------------------------------------

class FinalDecision(BaseModel):
    """최종 심의위원장이 재정 검토 토론을 종합하여 내리는 최종 결정."""

    verdict: ReviewVerdict = Field(
        description="최종 심의 결정. 승인 / 조건부승인 / 감액조정 / 보류 / 반려 중 하나.",
    )
    executive_summary: str = Field(
        description="심의 결과 핵심 요약. 2~4문장으로 결정 사항과 근거 압축.",
    )
    review_rationale: str = Field(
        description=(
            "상세 심의 근거. 각 분석가 보고서와 토론 내용을 인용하여 구체적 근거 제시."
        ),
    )
    approved_budget_billion: float | None = Field(
        default=None,
        ge=0,
        description="최종 승인 예산 (억원). 반려/보류 시 None.",
    )
    conditions: str | None = Field(
        default=None,
        description="조건부 승인 시 이행 조건 목록.",
    )

    @field_validator("conditions", "executive_summary", "review_rationale", mode="before")
    @classmethod
    def coerce_text_fields(cls, value):
        return _coerce_str(value)

    @model_validator(mode="after")
    def validate_decision_consistency(self):
        """최종 판정과 승인 예산·이행 조건 사이의 정합성을 검증한다."""
        budget = self.approved_budget_billion
        if self.verdict in {ReviewVerdict.DEFER, ReviewVerdict.REJECT}:
            if budget not in (None, 0):
                raise ValueError("보류/반려의 승인 예산은 None 또는 0이어야 합니다.")
        elif budget is None or budget <= 0:
            raise ValueError("승인/조건부승인/감액조정에는 0보다 큰 승인 예산이 필요합니다.")

        if self.verdict == ReviewVerdict.CONDITIONAL_APPROVE and not (
            self.conditions and self.conditions.strip()
        ):
            raise ValueError("조건부승인에는 구체적인 이행 조건이 필요합니다.")
        return self


# ---------------------------------------------------------------------------
# 예상 질의 추출기 출력
# ---------------------------------------------------------------------------

class CriterionTag(str, Enum):
    """질의가 겨냥하는 심의기준 분류."""
    GOV_SUPPORT = "정부지원 필요성"
    IMPORTANCE = "기술개발의 중요성"
    URGENCY = "시급성"
    OTHER = "기타"


class Severity(str, Enum):
    """취약점/질의의 심각도."""
    HIGH = "상"
    MEDIUM = "중"
    LOW = "하"


class AnticipatedQuestion(BaseModel):
    """심의위원이 던질 것으로 예상되는 질의 1건."""

    question: str = Field(description="심의위원이 실제로 던질 법한 구체적 질의문.")
    criterion: CriterionTag = Field(
        description="질의가 겨냥하는 심의기준. 정부지원 필요성 / 기술개발의 중요성 / 시급성 / 기타.",
    )
    severity: Severity = Field(
        description="답변 실패 시 심의 결과에 미칠 타격 정도. 상 / 중 / 하.",
    )
    basis: str = Field(
        description="이 질의가 도출된 근거 (분석 보고서·토론에서 지적된 취약점 요약).",
    )
    suggested_answer: str = Field(
        description="사업 담당자가 준비해야 할 권장 답변 초안. 구체적 근거·수치 포함.",
    )


class ImprovementItem(BaseModel):
    """기획보고서 보완 권고 1건."""

    weakness: str = Field(description="보고서에서 발견된 취약점 또는 논리적 허점.")
    severity: Severity = Field(description="심각도. 상 / 중 / 하.")
    recommendation: str = Field(
        description="보고서를 어떻게 수정·보강해야 하는지 구체적 지시.",
    )


class ReviewPreparationReport(BaseModel):
    """심의 대비 자료: 예상 질의 목록 + 보고서 보완 권고."""

    questions: list[AnticipatedQuestion] = Field(
        min_length=5,
        description="예상 질의 목록. 심각도 높은 순으로 8~15개 (최소 5개).",
    )
    improvements: list[ImprovementItem] = Field(
        min_length=3,
        description="기획보고서 보완 권고 목록. 심각도 높은 순으로 5~10개 (최소 3개).",
    )

    @model_validator(mode="after")
    def validate_core_criteria_coverage(self):
        """3대 최우선 심의기준을 겨냥한 질의가 각각 최소 1건 있는지 검증."""
        covered = {q.criterion for q in self.questions}
        required = {CriterionTag.GOV_SUPPORT, CriterionTag.IMPORTANCE, CriterionTag.URGENCY}
        missing = required - covered
        if missing:
            raise ValueError(
                "다음 핵심 심의기준을 겨냥한 질의가 최소 1건씩 필요합니다: "
                + ", ".join(tag.value for tag in sorted(missing, key=lambda t: t.value))
            )
        return self


def render_anticipated_questions(report: ReviewPreparationReport) -> str:
    lines = ["# 예상 질의응답", ""]
    for i, q in enumerate(report.questions, 1):
        lines.extend([
            f"## Q{i}. {q.question}",
            "",
            f"- **심의기준**: {q.criterion.value} | **심각도**: {q.severity.value}",
            f"- **출제 근거**: {q.basis}",
            "",
            f"**권장 답변 초안**:",
            "",
            q.suggested_answer,
            "",
        ])
    return "\n".join(lines)


def render_improvements(report: ReviewPreparationReport) -> str:
    lines = ["# 기획보고서 보완 권고", ""]
    for i, item in enumerate(report.improvements, 1):
        lines.extend([
            f"## {i}. {item.weakness} (심각도: {item.severity.value})",
            "",
            item.recommendation,
            "",
        ])
    return "\n".join(lines)


def render_final_decision(decision: FinalDecision) -> str:
    parts = [
        f"**최종 심의 결정**: {decision.verdict.value}",
        "",
        f"**요약**: {decision.executive_summary}",
        "",
        f"**상세 근거**: {decision.review_rationale}",
    ]
    if decision.approved_budget_billion is not None:
        parts.extend(["", f"**최종 승인 예산**: {decision.approved_budget_billion}억원"])
    if decision.conditions:
        parts.extend(["", f"**이행 조건**: {decision.conditions}"])
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 사후 검증: 실제 질의 vs 예측 질의 대조
# ---------------------------------------------------------------------------

class MatchLevel(str, Enum):
    """실제 질의와 예측 질의의 일치 수준."""
    HIT = "적중"
    PARTIAL = "부분적중"
    MISS = "미적중"


class QuestionMatch(BaseModel):
    """실제 심의에서 받은 질의 1건에 대한 예측 대조 결과."""

    actual_question: str = Field(description="실제 심의에서 받은 질의 원문.")
    match_level: MatchLevel = Field(
        description="적중(같은 논점·근거를 예측) / 부분적중(논점은 겹치나 핵심 각도가 다름) / 미적중.",
    )
    matched_prediction: str | None = Field(
        default=None,
        description="대응하는 예측 질의 원문. 미적중이면 None.",
    )
    note: str = Field(description="판정 근거 한두 문장.")


class QuestionVerificationReport(BaseModel):
    """실제 질의 목록 전체에 대한 예측 대조 보고서. 적중률 수치는 코드에서 계산한다."""

    matches: list[QuestionMatch] = Field(
        min_length=1,
        description="실제 질의 1건당 1개 항목. 실제 질의를 빠짐없이 포함.",
    )
    missed_topics_summary: str = Field(
        description="미적중 질의들의 공통 주제 요약 — 다음 시뮬레이션이 보강해야 할 방향.",
    )


def compute_hit_stats(report: QuestionVerificationReport) -> dict:
    """적중률 통계를 코드에서 계산 (LLM 산출 숫자를 신뢰하지 않음)."""
    total = len(report.matches)
    hits = sum(1 for m in report.matches if m.match_level == MatchLevel.HIT)
    partials = sum(1 for m in report.matches if m.match_level == MatchLevel.PARTIAL)
    misses = total - hits - partials
    weighted = round((hits + 0.5 * partials) / total * 100, 1) if total else 0.0
    return {
        "total": total, "hits": hits, "partials": partials, "misses": misses,
        "weighted_hit_rate": weighted,
    }


def render_verification_report(report: QuestionVerificationReport, stats: dict) -> str:
    lines = [
        "# 예상 질의 적중 검증",
        "",
        f"- **실제 질의 수**: {stats['total']}",
        f"- **적중**: {stats['hits']} / **부분적중**: {stats['partials']} / **미적중**: {stats['misses']}",
        f"- **가중 적중률**: {stats['weighted_hit_rate']}% (적중 1.0 + 부분 0.5)",
        "",
        "| # | 실제 질의 | 판정 | 대응 예측 질의 | 근거 |",
        "|---|---|---|---|---|",
    ]
    for i, m in enumerate(report.matches, 1):
        pred = (m.matched_prediction or "—").replace("|", "/")
        lines.append(
            f"| {i} | {m.actual_question.replace('|', '/')} | {m.match_level.value} "
            f"| {pred} | {m.note.replace('|', '/')} |"
        )
    lines.extend([
        "",
        "## 미적중 주제 요약 (다음 시뮬레이션 보강 방향)",
        "",
        report.missed_topics_summary,
    ])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 심의 품질·불확실성 평가
# ---------------------------------------------------------------------------

class ScoreItem(BaseModel):
    """평가기준 하나의 정량 점수와 근거."""

    score: float = Field(default=0, ge=0, le=100, description="기준별 점수(0~100).")
    confidence: float = Field(default=0, ge=0, le=100, description="근거 충분성 신뢰도(0~100).")
    rationale: str = Field(default="평가 자료 부족", description="점수 산정 근거.")
    evidence_refs: list[str] = Field(
        default_factory=list,
        description="판단에 사용한 [출처: 파일명 Lx-Ly] 또는 심의 산출물 참조.",
    )


class DecisionQualityReport(BaseModel):
    """결정과 독립적으로 산출하는 정량 평가 및 불확실성 보고서."""

    government_support: ScoreItem = Field(default_factory=ScoreItem)
    technology_importance: ScoreItem = Field(default_factory=ScoreItem)
    urgency: ScoreItem = Field(default_factory=ScoreItem)
    technical_feasibility: ScoreItem = Field(default_factory=ScoreItem)
    economic_feasibility: ScoreItem = Field(default_factory=ScoreItem)
    execution_capability: ScoreItem = Field(default_factory=ScoreItem)
    overall_score: float = Field(default=0, ge=0, le=100)
    overall_confidence: float = Field(default=0, ge=0, le=100)
    disagreements: list[str] = Field(default_factory=list)
    contrary_evidence: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    external_evidence_assessment: str = Field(default="독립 외부 근거 미확인")

    @model_validator(mode="after")
    def calculate_overall_score(self):
        self.overall_score = round(
            sum(getattr(self, key).score * weight
                for key, (_, weight) in QUALITY_WEIGHTS.items()), 1
        )
        self.overall_confidence = round(
            sum(getattr(self, key).confidence * weight
                for key, (_, weight) in QUALITY_WEIGHTS.items()), 1
        )
        return self


# 품질 평가 기준의 단일 정의: (한글 라벨, 가중치). 검증자·평가표·프롬프트가 모두 참조.
QUALITY_WEIGHTS: dict[str, tuple[str, float]] = {
    "government_support": ("정부지원 필요성", 0.25),
    "technology_importance": ("기술개발 중요성", 0.20),
    "urgency": ("시급성", 0.15),
    "technical_feasibility": ("기술적 실현 가능성", 0.15),
    "economic_feasibility": ("경제·재무 타당성", 0.15),
    "execution_capability": ("수행 역량", 0.10),
}


def quality_weights_text() -> str:
    """프롬프트 주입용 가중치 설명 문자열."""
    return ", ".join(
        f"{label} {weight * 100:.0f}%" for label, weight in QUALITY_WEIGHTS.values()
    )


_QUALITY_LABELS = [
    (key, label, round(weight * 100)) for key, (label, weight) in QUALITY_WEIGHTS.items()
]


def render_quality_scorecard(report: DecisionQualityReport) -> str:
    lines = [
        "# 정량 평가표",
        "",
        "| 평가기준 | 가중치 | 점수 | 신뢰도 | 핵심 근거 |",
        "|---|---:|---:|---:|---|",
    ]
    for key, label, weight in _QUALITY_LABELS:
        item = getattr(report, key)
        refs = "; ".join(item.evidence_refs) or "근거 참조 없음"
        lines.append(
            f"| {label} | {weight}% | {item.score:.1f} | {item.confidence:.1f} | "
            f"{item.rationale} ({refs}) |"
        )
    lines.extend([
        "",
        f"- **가중 종합점수**: {report.overall_score:.1f}/100",
        f"- **종합 신뢰도**: {report.overall_confidence:.1f}/100",
        "- 점수는 LLM의 구조화 판단이며 공식 평가점수가 아니라 비교·점검용입니다.",
    ])
    return "\n".join(lines)


def render_uncertainty_report(report: DecisionQualityReport) -> str:
    def section(title: str, values: list[str]) -> list[str]:
        return [f"## {title}", ""] + ([f"- {v}" for v in values] if values else ["- 확인된 항목 없음"]) + [""]

    lines = [
        "# 불확실성 및 반대 근거",
        "",
        f"**외부 근거 평가**: {report.external_evidence_assessment}",
        "",
    ]
    lines += section("에이전트 간 불일치", report.disagreements)
    lines += section("결론에 반하는 근거", report.contrary_evidence)
    lines += section("추가 확인이 필요한 자료", report.missing_evidence)
    return "\n".join(lines)


class ReReviewComparison(BaseModel):
    """이전 심의와 이번 심의 사이의 지적사항 변화."""

    status: str = Field(description="신규 심의 또는 재심의")
    resolved_concerns: list[str] = Field(default_factory=list)
    unresolved_concerns: list[str] = Field(default_factory=list)
    new_concerns: list[str] = Field(default_factory=list)
    decision_change: str = Field(default="비교할 이전 결정 없음")
    budget_change: str = Field(default="비교할 이전 예산 없음")
    summary: str = Field(default="이전 심의 이력이 없습니다.")


def render_rereview_comparison(comparison: ReReviewComparison) -> str:
    def bullets(values: list[str]) -> str:
        return "\n".join(f"- {value}" for value in values) or "- 해당 없음"

    return "\n".join([
        "# 재심의 전후 비교",
        "",
        f"- **구분**: {comparison.status}",
        f"- **결정 변화**: {comparison.decision_change}",
        f"- **예산 변화**: {comparison.budget_change}",
        "",
        "## 해소된 지적사항",
        "",
        bullets(comparison.resolved_concerns),
        "",
        "## 미해소 지적사항",
        "",
        bullets(comparison.unresolved_concerns),
        "",
        "## 새로 발견된 우려",
        "",
        bullets(comparison.new_concerns),
        "",
        "## 종합",
        "",
        comparison.summary,
    ])
