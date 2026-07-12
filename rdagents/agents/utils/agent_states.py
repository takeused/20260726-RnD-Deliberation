"""R&D 예산 심의 에이전트 상태 정의.

TradingAgents의 AgentState 패턴을 기반으로 6인 분석가 + 찬반 토론 + 재정 검토 구조에 맞게 확장.
"""

from typing import Annotated

from langgraph.graph import MessagesState
from typing_extensions import TypedDict


# 심사위원 패널 vs 사업 발표자 공방 상태
class ReviewDebateState(TypedDict):
    examiner_history: Annotated[str, "심사위원 패널 질의·지적 히스토리"]
    defender_history: Annotated[str, "사업 발표자 방어 히스토리"]
    history: Annotated[str, "전체 토론 히스토리"]
    current_response: Annotated[str, "최근 발언"]
    judge_decision: Annotated[str, "전문위원회 위원장 판정"]
    count: Annotated[int, "토론 발언 횟수"]


# 재정 검토 토론 상태
class AuditDebateState(TypedDict):
    aggressive_history: Annotated[str, "적극 투자 검토관 발언 히스토리"]
    conservative_history: Annotated[str, "재정 건전성 검토관 발언 히스토리"]
    neutral_history: Annotated[str, "균형 재정 조율관 발언 히스토리"]
    history: Annotated[str, "전체 재정 검토 토론 히스토리"]
    latest_speaker: Annotated[str, "마지막 발언자"]
    current_aggressive_response: Annotated[str, "적극 투자 검토관 최근 발언"]
    current_conservative_response: Annotated[str, "재정 건전성 검토관 최근 발언"]
    current_neutral_response: Annotated[str, "균형 재정 조율관 최근 발언"]
    judge_decision: Annotated[str, "최종 심의위원장 판정"]
    count: Annotated[int, "재정 검토 발언 횟수"]


# 전체 에이전트 상태
class ReviewAgentState(MessagesState):
    project_id: Annotated[str, "심의 대상 사업 ID"]
    review_year: Annotated[str, "심의 대상 연도"]
    project_context: Annotated[str, "사업계획서 전체 컨텍스트"]
    sender: Annotated[str, "메시지 발신 에이전트"]

    # 6개 분석가 보고서
    tech_value_report: Annotated[str, "기술 가치 분석 보고서"]
    tech_trend_report: Annotated[str, "기술 트렌드/중복성 분석 보고서"]
    economic_report: Annotated[str, "경제/재무 타당성 보고서"]
    policy_report: Annotated[str, "정책 부합성 보고서"]
    feasibility_report: Annotated[str, "수행체계 분석 보고서"]
    regulatory_report: Annotated[str, "규제/윤리 검토 보고서"]

    # 심사 공방 (패널 공격 vs 발표자 방어)
    review_debate_state: Annotated[ReviewDebateState, "심사 공방 상태"]
    review_plan: Annotated[str, "전문위원회 위원장 종합 의견"]

    # 예산 조정
    budget_coordination_plan: Annotated[str, "예산 조정관 1차 조정안"]

    # 재정 검토 토론
    audit_debate_state: Annotated[AuditDebateState, "재정 검토 토론 상태"]
    final_review_decision: Annotated[str, "최종 심의 결정"]

    # 심의 대비 산출물 (예상 질의 추출기)
    anticipated_questions_md: Annotated[str, "예상 질의응답 마크다운"]
    preparation_report_json: Annotated[str, "예상 질의·보완 권고 구조화 JSON (사후 검증용)"]
    improvement_recommendations_md: Annotated[str, "기획보고서 보완 권고 마크다운"]
    quality_scorecard_md: Annotated[str, "기준별 정량 평가표 마크다운"]
    uncertainty_report_md: Annotated[str, "불확실성·반대 근거 보고서 마크다운"]

    # 이전 심의 이력
    past_context: Annotated[str, "이전 심의 이력 컨텍스트"]
    source_manifest: Annotated[str, "입력 문서 출처 및 검색 인덱스 메타데이터"]
    gate_profile: Annotated[str, "심의 관문 프로파일 (청중·중점 기준·질의 성향)"]
    question_bank: Annotated[str, "기출·전형 질의 참고 코퍼스"]
    rereview_comparison_md: Annotated[str, "재심의 전후 비교 보고서"]
    execution_metrics: Annotated[list[dict], "노드별 실행시간·토큰 관측값"]
    execution_metadata: Annotated[dict, "실행 ID·모델·체크포인트 메타데이터"]
