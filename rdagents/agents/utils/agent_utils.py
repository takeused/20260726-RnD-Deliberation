"""에이전트 헬퍼 유틸리티 함수."""

from __future__ import annotations

from langchain_core.messages import AIMessage


def make_ai_message(content: str, name: str, usage: dict | None = None) -> AIMessage:
    """usage_metadata를 보존한 AIMessage 생성.

    노드가 응답을 재포장할 때 원 응답의 토큰 사용량을 잃지 않아야
    실행 관측성(12_실행관측성.md)의 토큰 집계가 실제 값을 갖는다.
    """
    if usage:
        return AIMessage(content=content, name=name, usage_metadata=usage)
    return AIMessage(content=content, name=name)


def clip_text(text: str, state: dict, fraction: float = 1.0) -> str:
    """상태의 prompt_char_budget(0=무제한)에 맞춰 긴 입력을 앞뒤 보존하며 중략.

    Cerebras 무료 티어(8K 토큰)나 로컬 소형 모델처럼 컨텍스트가 작은 백엔드에서
    긴 심의 이력이 컨텍스트 초과로 실행을 중단시키는 것을 막는다.
    fraction: 입력 섹션이 많은 노드는 섹션당 예산을 줄이기 위해 1 미만을 지정.
    """
    budget = int((state.get("prompt_char_budget") or 0) * fraction)
    if budget <= 0 or len(text) <= budget:
        return text
    head = int(budget * 0.6)
    tail = budget - head
    return text[:head] + "\n…(분량 제한으로 중략)…\n" + text[-tail:]


def get_language_instruction(language: str = "Korean") -> str:
    """출력 언어와 모든 에이전트에 공통인 근거 규칙을 반환."""
    grounding = (
        "\n\n## 근거 사용 원칙\n"
        "- 도구 결과, 입력 보고서, 외부근거, 앞 단계 심의 산출물에 실제로 포함된 정보만 사실로 단정하세요.\n"
        "- 제공되지 않은 통계·시장규모·투자액·기관명·문서명·인용문·날짜·협약·사례를 만들어내지 마세요.\n"
        "- 사업보고서의 주장은 '사업보고서 주장', 독립 외부자료로 확인된 내용은 '외부근거 확인'으로 구분하세요.\n"
        "- 필요한 근거가 없으면 추정값으로 채우지 말고 '[확인 필요: 필요한 자료]'라고 표시하세요.\n"
        "- '[확인 필요]' 앞에 근거 없는 수치·기관·기업·협약·해외사례를 사실처럼 쓰지 마세요. "
        "그 경우에는 '제출자료로 확인하지 못했습니다'라고만 쓰고 필요한 증빙을 명시하세요.\n"
        "- 사실형 문장에는 가능한 한 입력에 있는 정확한 [출처: 파일명 L시작-L끝]을 붙이고, 줄번호를 생략·축약하지 마세요.\n"
        "- 미래 제출일·과거 실적·정책 시행일은 입력 근거가 있을 때만 구체적인 날짜로 쓰세요."
    )
    if language.lower() == "korean":
        return grounding + "\n\n**중요: 모든 분석 보고서와 의견은 반드시 한국어로 작성해 주세요.**"
    return grounding


def get_project_context_from_state(state: dict) -> str:
    """에이전트 state에서 사업계획서 컨텍스트를 추출."""
    return state.get("project_context", "")
