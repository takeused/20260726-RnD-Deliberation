"""에이전트 헬퍼 유틸리티 함수."""

from __future__ import annotations

import os

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


def make_ai_message(content: str, name: str, usage: dict | None = None) -> AIMessage:
    """usage_metadata를 보존한 AIMessage 생성.

    노드가 응답을 재포장할 때 원 응답의 토큰 사용량을 잃지 않아야
    실행 관측성(12_실행관측성.md)의 토큰 집계가 실제 값을 갖는다.
    """
    if usage:
        return AIMessage(content=content, name=name, usage_metadata=usage)
    return AIMessage(content=content, name=name)


def _setting(state: dict, key: str, env_var: str) -> int:
    """상태 값, 없으면 환경변수. 이 설정이 생기기 전에 만든 체크포인트로 이어서 실행해도 적용되도록."""
    value = state.get(key)
    if value is None:
        value = os.environ.get(env_var) or 0
    return int(value or 0)


TOOL_LIMIT_NOTE = (
    "도구 호출 한도에 도달했습니다. 더 이상 도구를 부르지 말고, 지금까지 확보한 자료만으로 "
    "분석 보고서를 완성하세요. 확인하지 못한 항목은 [확인 필요]로 표시하세요."
)


def bind_analyst_tools(llm, tools: list, state: dict):
    """(바인딩된 모델, 보낼 메시지). 도구 호출이 상한에 이르면 도구를 못 부르게 하고 보고서 작성을 지시한다."""
    messages = fit_tool_messages(state["messages"], state)
    cap = _setting(state, "max_analyst_tool_calls", "RDAGENTS_MAX_ANALYST_TOOL_CALLS")
    used = sum(isinstance(m, ToolMessage) for m in state["messages"])
    if cap and used >= cap:
        return llm.bind_tools(tools, tool_choice="none"), [*messages, HumanMessage(content=TOOL_LIMIT_NOTE)]
    return llm.bind_tools(tools), messages


def fit_tool_messages(messages: list, state: dict, min_keep: int = 300) -> list:
    """LLM에 보낼 메시지의 도구 결과 총량을 tool_result_char_budget(0=무제한) 안으로 줄인다.

    최근 도구 결과부터 예산을 배정하고, 예산을 넘는 오래된 결과는 앞부분 min_keep자만 남긴다.
    상태(체크포인트)에 저장된 원본은 바꾸지 않고, 이번 호출에 보내는 사본만 줄인다.
    NDMI 보고서 실행에서 분석가가 도구를 4번 부르자 요청이 Groq 분당 한도(8,000토큰)를 넘었다(413).
    """
    budget = _setting(state, "tool_result_char_budget", "RDAGENTS_TOOL_RESULT_CHAR_BUDGET")
    if budget <= 0:
        return messages
    out, used = list(messages), 0
    for i in range(len(out) - 1, -1, -1):
        m = out[i]
        if not isinstance(m, ToolMessage):
            continue
        text = m.content if isinstance(m.content, str) else str(m.content)
        if used + len(text) <= budget:
            used += len(text)
            continue
        keep = max(budget - used, min_keep)
        clipped = text[:keep] + f"\n…(앞선 도구 결과 {len(text) - keep:,}자 생략: 요청 크기 예산)"
        out[i] = m.model_copy(update={"content": clipped})
        used += len(clipped)
    return out


def clip_text(text: str, state: dict, fraction: float = 1.0) -> str:
    """상태의 prompt_char_budget(0=무제한)에 맞춰 긴 입력을 앞뒤 보존하며 중략.

    Groq 무료 등급(분당 8,000토큰)이나 로컬 소형 모델처럼 컨텍스트가 작은 백엔드에서
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
