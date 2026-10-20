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
    minority_opinions: list[str] = Field(
        default_factory=list,
        description="결론과 다른 위원·분석가 의견(소수의견). '위원: 의견' 형식. 없으면 빈 목록.",
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
        *render_minority(plan.minority_opinions),
    ])


def render_minority(opinions: list[str]) -> list[str]:
    """소수의견 절. 실제 심의록처럼 결론과 다른 의견도 남긴다 (없으면 절을 만들지 않음)."""
    return ["", "**소수의견**:", *[f"- {o}" for o in opinions]] if opinions else []


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


def align_budget_proposal_to_request(
    proposal: BudgetProposal, requested_budget_eok: float | None
) -> BudgetProposal:
    """원문에서 검증한 예산을 예산 조정안의 기준값으로 강제한다."""
    if requested_budget_eok is None:
        return proposal
    if requested_budget_eok <= 0:
        raise ValueError("검증된 원래 요청 예산은 0보다 커야 합니다.")

    values = proposal.model_dump()
    values["original_budget_billion"] = requested_budget_eok
    if proposal.action == BudgetAction.FULL_APPROVE:
        values["proposed_budget_billion"] = requested_budget_eok
    elif proposal.action in {BudgetAction.DEFER, BudgetAction.REJECT}:
        values["proposed_budget_billion"] = None
    elif proposal.proposed_budget_billion is None:
        raise ValueError("감액/증액 조정안에는 검증 기준과 비교 가능한 제안 예산이 필요합니다.")
    return BudgetProposal(**values)


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
    minority_opinions: list[str] = Field(
        default_factory=list,
        description="결론과 다른 재정 검토관·위원 의견(소수의견). '발언자: 의견' 형식. 없으면 빈 목록.",
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
            # 재시도 피드백으로 그대로 전달된다: 예산 근거가 없을 때 금액을 지어내지 않게 보류를 안내 (NDMI groq6의 120.0억원)
            raise ValueError("승인/조건부승인/감액조정에는 0보다 큰 승인 예산이 필요합니다. "
                             "입력에 근거가 되는 예산액이 없으면 금액을 만들지 말고 판정을 '보류'로 하세요.")

        if self.verdict == ReviewVerdict.CONDITIONAL_APPROVE and not (
            self.conditions and self.conditions.strip()
        ):
            raise ValueError("조건부승인에는 구체적인 이행 조건이 필요합니다.")
        return self


def align_final_decision_to_budget(
    decision: FinalDecision, approved_budget_eok: float | None, budget_known: bool = True
) -> FinalDecision:
    """최종 결정의 승인 예산이 직전 검증 예산안과 일치하는지 확인한다.

    budget_known=False: 원문에서 검증한 예산도, 금액이 있는 예산 조정안도 없다. 이때 승인류 결정은 승인 예산을
    지어낼 수밖에 없다 (NDMI groq6: 예산액이 없는 보고서에 '조건부승인 120.0억원'이 나와 예상 질의까지 번졌음).
    """
    if decision.verdict in {ReviewVerdict.DEFER, ReviewVerdict.REJECT}:
        if decision.approved_budget_billion not in (None, 0):
            raise ValueError("보류/반려 결정은 승인 예산을 포함할 수 없습니다.")
        return decision
    if approved_budget_eok is None and not budget_known:
        raise ValueError("원문에서 확인한 예산과 금액이 있는 예산 조정안이 모두 없어 승인 예산의 근거가 없습니다. "
                         "원문에 없는 예산액을 만들지 말고 판정을 '보류'로 하세요.")
    if approved_budget_eok is None:
        return decision
    if decision.approved_budget_billion is None:
        raise ValueError("승인성 결정에는 검증 예산안과 같은 승인 예산이 필요합니다.")
    if abs(decision.approved_budget_billion - approved_budget_eok) > 0.01:
        raise ValueError(
            "최종 승인 예산이 검증 예산안과 다릅니다: "
            f"{decision.approved_budget_billion}억원 != {approved_budget_eok}억원"
        )
    return decision


# ---------------------------------------------------------------------------
# 예상 질의 추출기 출력
# ---------------------------------------------------------------------------

class CriterionTag(str, Enum):
    """질의가 겨냥하는 심의기준 분류."""
    GOV_SUPPORT = "정부지원 필요성"
    IMPORTANCE = "기술개발의 중요성"
    URGENCY = "시급성"
    BUDGET = "예산 타당성"  # 예산 규모·비목 산출 근거. 3대 기준이 아니어도 감액 결론을 바꾸므로 별도 보장
    FIELD = "현장 적용·확산"  # 공공임무형: 수요기관 참여·실증·제도화·사후 운영 재원. 이 유형에서만 별도 보장
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
        description=(
            "질의가 겨냥하는 심의기준. 정부지원 필요성 / 기술개발의 중요성 / 시급성 / "
            "예산 타당성(예산 규모·비목·단가 산출 근거) / 기타."
        ),
    )
    severity: Severity = Field(
        description="답변 실패 시 심의 결과에 미칠 타격 정도. 상 / 중 / 하.",
    )
    basis: str = Field(
        description="이 질의가 도출된 근거 (분석 보고서·토론에서 지적된 취약점 요약).",
    )
    suggested_answer: str = Field(
        description=(
            "사업 담당자가 준비해야 할 권장 답변 초안. 입력 근거에 실제 수치가 있을 때만 포함하고, "
            "근거가 없는 수치·기관·사례는 만들지 말고 '제출자료로 확인하지 못했습니다. "
            "[확인 필요: 필요한 자료]'로만 표시. 사실형 문장에는 [출처: 파일명 L시작-L끝]을 붙일 것."
        ),
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
        """3대 최우선 심의기준과 예산 타당성을 겨냥한 질의가 각각 최소 1건 있는지 검증.

        예산 타당성을 따로 요구하는 이유: 3대 기준만 요구하면 예산 산출 근거를 묻는 질의가 하나도 없어도
        통과한다. 학습 저장소의 모의 심의에서 예산 지적이 공방에서 빠지면 감액 결론이 사라지는 것을 확인했다.
        """
        covered = {q.criterion for q in self.questions}
        required = {CriterionTag.GOV_SUPPORT, CriterionTag.IMPORTANCE, CriterionTag.URGENCY,
                    CriterionTag.BUDGET}
        missing = required - covered
        if missing:
            raise ValueError(
                "다음 핵심 심의기준을 겨냥한 질의가 최소 1건씩 필요합니다: "
                + ", ".join(tag.value for tag in sorted(missing, key=lambda t: t.value))
            )
        return self


def require_type_questions(report: ReviewPreparationReport, project_type: str | None) -> ReviewPreparationReport:
    """사업 유형별 필수 질의. 공공임무형은 '현장 적용·확산' 질의가 1건 이상 있어야 한다.

    재난안전 R&D는 기술을 개발해도 현장에 쓰이지 않는다는 지적이 잦은데, 3대 기준·예산 질의만 보장하면
    수요기관·제도화·사후 운영을 묻는 질의가 빠져도 통과한다.
    """
    if project_type == "공공임무형" and CriterionTag.FIELD not in {q.criterion for q in report.questions}:
        raise ValueError("공공임무형 사업이므로 '현장 적용·확산'(수요기관 참여, 실증 이후 제도화 경로, "
                         "사업 종료 후 운영·유지관리 주체와 재원)을 묻는 질의가 최소 1건 필요합니다.")
    return report


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
    parts.extend(render_minority(decision.minority_opinions))
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 쟁점 원장: 분석 보고서의 지적을 쟁점으로 등록하고, 쟁점별 공방의 방어 결과를 기록
# ---------------------------------------------------------------------------

class RegisteredIssue(BaseModel):
    """분석 보고서에서 뽑은 쟁점 하나. 출처는 코드가 원문과 대조해 검증한다."""

    issue: str = Field(description="쟁점을 한 문장으로. 무엇이 부족하거나 의심스러운가.")
    criterion: CriterionTag = Field(description="쟁점이 겨냥하는 심의기준.")
    severity: Severity = Field(description="심각도 (상/중/하).")
    source_report: str = Field(description="이 쟁점을 지적한 분석 보고서 이름 (예: '경제/재무 타당성 분석').")
    cite: str = Field(default="", description="근거 원문 위치 [출처: 파일명 L시작-L끝]. 분석 보고서가 단 출처를 그대로 옮김.")
    quote: str = Field(default="", description="그 줄에 실제로 있는 원문 구절 (10~40자, 그대로 복사).")


class IssueRegister(BaseModel):
    issues: list[RegisteredIssue] = Field(
        min_length=3, max_length=12,
        description="심의에서 다룰 쟁점 5~10개. 심각도 높은 순. 서로 중복되지 않게.",
    )


class DefenseAnswer(BaseModel):
    """발표자의 쟁점 하나에 대한 답변. 근거가 없으면 supported=false로 솔직히 답한다."""

    supported: bool = Field(description="제출자료(기획보고서 원문)에 방어 근거가 있으면 true, 없으면 false.")
    answer: str = Field(description="답변. 근거가 없으면 '제출자료로 확인하지 못했습니다'와 보완 계획.")
    cite: str = Field(default="", description="방어 근거 원문 위치 [출처: 파일명 L시작-L끝]. supported=false면 빈 문자열.")
    quote: str = Field(default="", description="그 줄에 실제로 있는 원문 구절 (10~40자, 그대로 복사).")

    @field_validator("answer", mode="before")
    @classmethod
    def coerce_text_fields(cls, value):
        return _coerce_str(value)


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
    """결정과 독립적으로 산출하는 정량 평가 및 불확실성 보고서.

    평가 항목은 모든 사업 유형의 합집합이다. 유형마다 쓰는 항목·라벨·가중치는 TYPE_QUALITY_WEIGHTS가 정하고,
    가중치가 없는 항목은 기본값으로 두면 된다 (예: 산업형의 재난관리 단계 적합성).
    """

    government_support: ScoreItem = Field(default_factory=ScoreItem)
    technology_importance: ScoreItem = Field(default_factory=ScoreItem)
    urgency: ScoreItem = Field(default_factory=ScoreItem)
    technical_feasibility: ScoreItem = Field(default_factory=ScoreItem)
    economic_feasibility: ScoreItem = Field(default_factory=ScoreItem)
    execution_capability: ScoreItem = Field(default_factory=ScoreItem)
    field_deployment: ScoreItem = Field(default_factory=ScoreItem, description="현장 적용·확산(공공임무형) 또는 사업화·확산(산업형) 경로.")
    disaster_phase_fit: ScoreItem = Field(default_factory=ScoreItem, description="재난관리 단계(예방·대비·대응·복구) 적합성. 공공임무형만.")
    overall_score: float = Field(default=0, ge=0, le=100)
    overall_confidence: float = Field(default=0, ge=0, le=100)
    disagreements: list[str] = Field(default_factory=list)
    contrary_evidence: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    external_evidence_assessment: str = Field(default="독립 외부 근거 미확인")

    @model_validator(mode="after")
    def calculate_overall_score(self):
        return apply_quality_weights(self, None)


# 품질 평가 기준의 단일 정의: 사업 유형 -> {항목: (한글 라벨, 가중치)}. 검증자·평가표·프롬프트가 모두 참조.
# 공공임무형은 경제성(B/C) 비중을 낮추고 현장 적용·확산과 재난관리 단계 적합성을 넣었다. 재난안전 R&D는
# 기술을 개발해도 현장에 쓰이지 않는다는 지적이 잦고, 시장성 잣대로 보면 공익 사업이 감점되기 때문이다.
# 가중치는 비교·점검용 초안이며 공식 배점이 아니다.
TYPE_QUALITY_WEIGHTS: dict[str, dict[str, tuple[str, float]]] = {
    "공공임무형": {
        "government_support": ("정부지원 필요성 (국가 책무·시장실패)", 0.20),
        "technology_importance": ("공공가치·피해저감 효과", 0.20),
        "urgency": ("시급성", 0.15),
        "disaster_phase_fit": ("재난관리 단계 적합성", 0.10),
        "field_deployment": ("현장 적용·확산 경로", 0.15),
        "technical_feasibility": ("기술적 실현 가능성", 0.08),
        "execution_capability": ("수행 역량·부처 간 역할", 0.07),
        "economic_feasibility": ("비용효과성", 0.05),
    },
    "산업형": {
        "government_support": ("정부지원 필요성 (시장실패·민간 매칭)", 0.20),
        "technology_importance": ("기술개발 중요성 (기술 주권·산업 파급)", 0.20),
        "urgency": ("시급성", 0.15),
        "technical_feasibility": ("기술적 실현 가능성", 0.15),
        "economic_feasibility": ("경제성·시장성", 0.15),
        "field_deployment": ("사업화·확산 경로", 0.10),
        "execution_capability": ("수행 역량", 0.05),
    },
    "혼합형": {
        "government_support": ("정부지원 필요성", 0.20),
        "technology_importance": ("기술개발 중요성·공공가치", 0.20),
        "urgency": ("시급성", 0.15),
        "technical_feasibility": ("기술적 실현 가능성", 0.15),
        "economic_feasibility": ("경제·공공가치 타당성", 0.10),
        "field_deployment": ("현장 적용·사업화 경로", 0.10),
        "execution_capability": ("수행 역량", 0.10),
    },
}
QUALITY_WEIGHTS = TYPE_QUALITY_WEIGHTS["혼합형"]  # 유형을 모를 때 (구조화 샘플 모드 기본값)


def quality_weights(project_type: str | None = None) -> dict[str, tuple[str, float]]:
    return TYPE_QUALITY_WEIGHTS.get(project_type or "혼합형", QUALITY_WEIGHTS)


def apply_quality_weights(report: "DecisionQualityReport", project_type: str | None) -> "DecisionQualityReport":
    """사업 유형의 가중치로 종합점수·종합 신뢰도를 다시 계산한다."""
    weights = quality_weights(project_type)
    report.overall_score = round(sum(getattr(report, k).score * w for k, (_, w) in weights.items()), 1)
    report.overall_confidence = round(sum(getattr(report, k).confidence * w for k, (_, w) in weights.items()), 1)
    return report


def quality_weights_text(project_type: str | None = None) -> str:
    """프롬프트 주입용 가중치 설명 문자열 (항목 필드명 포함: LLM이 어느 필드에 점수를 넣을지 알게)."""
    return ", ".join(
        f"{label}({key}) {weight * 100:.0f}%" for key, (label, weight) in quality_weights(project_type).items()
    )


def render_quality_scorecard(report: DecisionQualityReport, project_type: str | None = None) -> str:
    lines = [
        "# 정량 평가표",
        "",
        f"- **사업 유형**: {project_type or '혼합형'} (유형별 평가 항목·가중치 적용)",
        "",
        "| 평가기준 | 가중치 | 점수 | 신뢰도 | 핵심 근거 |",
        "|---|---:|---:|---:|---|",
    ]
    for key, (label, weight) in quality_weights(project_type).items():
        weight = round(weight * 100)
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
