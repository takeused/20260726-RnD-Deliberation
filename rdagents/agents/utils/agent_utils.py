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
    """출력 언어 지시문 반환."""
    if language.lower() == "korean":
        return "\n\n**중요: 모든 분석 보고서와 의견은 반드시 한국어로 작성해 주세요.**"
    return ""


def get_project_context_from_state(state: dict) -> str:
    """에이전트 state에서 사업계획서 컨텍스트를 추출."""
    return state.get("project_context", "")
