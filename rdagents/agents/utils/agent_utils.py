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


def get_language_instruction(language: str = "Korean") -> str:
    """출력 언어 지시문 반환."""
    if language.lower() == "korean":
        return "\n\n**중요: 모든 분석 보고서와 의견은 반드시 한국어로 작성해 주세요.**"
    return ""


def get_project_context_from_state(state: dict) -> str:
    """에이전트 state에서 사업계획서 컨텍스트를 추출."""
    return state.get("project_context", "")
