"""Shared helpers for invoking an agent with structured output and a graceful fallback.

The Portfolio Manager, Trader, and Research Manager all follow the same
canonical pattern:

1. At agent creation, wrap the LLM with ``with_structured_output(Schema)``
   so the model returns a typed Pydantic instance. If the provider does
   not support structured output (rare; mostly older Ollama models), the
   wrap is skipped and the agent uses free-text generation instead.
2. At invocation, run the structured call and render the result back to
   markdown. If the structured call itself fails for any reason
   (malformed JSON from a weak model, transient provider issue), fall
   back to a plain ``llm.invoke`` so the pipeline never blocks.

Centralising the pattern here keeps the agent factories small and ensures
all three agents log the same warnings when fallback fires.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from langchain_core.messages import HumanMessage
from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def bind_structured(llm: Any, schema: type[T], agent_name: str) -> Any | None:
    """Return ``llm.with_structured_output(schema)`` or ``None`` if unsupported.

    Logs a warning when the binding fails so the user understands the agent
    will use free-text generation for every call instead of one-shot fallback.
    """
    try:
        return llm.with_structured_output(schema)
    except (NotImplementedError, AttributeError) as exc:
        logger.warning(
            "%s: provider does not support with_structured_output (%s); "
            "falling back to free-text generation",
            agent_name, exc,
        )
        return None


@dataclass
class StructuredCallResult:
    """구조화 호출 결과: 파싱된 모델과 원 응답의 토큰 사용량."""

    model: Any | None
    usage: dict | None = None


def _to_messages(prompt_val: Any) -> list:
    """PromptValue/문자열/메시지 리스트를 메시지 리스트로 정규화."""
    if hasattr(prompt_val, "to_messages"):
        return list(prompt_val.to_messages())
    if isinstance(prompt_val, list):
        return list(prompt_val)
    return [HumanMessage(content=str(prompt_val))]


def _parse_attempt(result: Any, schema: type[T]) -> tuple[T | None, dict | None, str]:
    """한 번의 호출 결과에서 (모델, usage, 오류 설명)을 추출."""
    usage = None
    if isinstance(result, dict) and "parsed" in result:
        # include_raw=True 경로: {"raw": AIMessage, "parsed": model|None, "parsing_error": ...}
        raw = result.get("raw")
        usage = getattr(raw, "usage_metadata", None)
        parsed = result.get("parsed")
        if isinstance(parsed, schema):
            return parsed, usage, ""
        return None, usage, str(result.get("parsing_error") or "파싱 결과 없음")
    if isinstance(result, schema):
        return result, usage, ""
    if hasattr(result, "tool_calls") and result.tool_calls:
        usage = getattr(result, "usage_metadata", None)
        try:
            return schema(**result.tool_calls[0]["args"]), usage, ""
        except Exception as exc:
            return None, usage, str(exc)
    return None, usage, "구조화 출력이 반환되지 않음"


def invoke_structured_model(
    llm: Any,
    schema: type[T],
    prompt_val: Any,
    agent_name: str,
    max_attempts: int = 2,
) -> StructuredCallResult:
    """구조화 출력을 호출해 스키마 인스턴스와 토큰 사용량을 반환한다.

    검증(Pydantic model_validator 포함) 실패 시 오류 내용을 피드백 메시지로
    덧붙여 최대 max_attempts회 재시도한다. 전부 실패하면 model=None을
    반환하며, 호출자는 자유 텍스트로 폴백해야 한다.
    """
    try:
        structured_llm = llm.with_structured_output(schema, include_raw=True)
    except TypeError:
        # include_raw 미지원 프로바이더는 파싱 결과만 받는 경로로 진행
        structured_llm = bind_structured(llm, schema, agent_name)
    except (NotImplementedError, AttributeError) as exc:
        logger.warning(
            "%s: provider does not support with_structured_output (%s)", agent_name, exc
        )
        return StructuredCallResult(None)
    if structured_llm is None:
        return StructuredCallResult(None)

    base_messages = _to_messages(prompt_val)
    messages = base_messages
    last_usage = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = structured_llm.invoke(messages)
        except Exception as exc:
            # include_raw=True는 파싱 오류를 dict로 돌려주므로 여기 오는 것은
            # 주로 전송/프로바이더 예외다. 검증 예외(non-raw 경로)도 포함.
            error_text = str(exc)
            logger.warning(
                "%s: structured attempt %d/%d failed (%s)",
                agent_name, attempt, max_attempts, error_text,
            )
        else:
            model, usage, error_text = _parse_attempt(result, schema)
            last_usage = usage or last_usage
            if model is not None:
                return StructuredCallResult(model, last_usage)
            logger.warning(
                "%s: structured attempt %d/%d parse/validation failed (%s)",
                agent_name, attempt, max_attempts, error_text,
            )
        if attempt < max_attempts:
            messages = base_messages + [
                HumanMessage(
                    content=(
                        "직전 출력이 스키마 검증에 실패했습니다. 오류:\n"
                        f"{error_text}\n"
                        "위 오류를 해결하여 모든 필드 제약을 지킨 구조화 출력을 다시 생성하세요."
                    )
                )
            ]
    return StructuredCallResult(None, last_usage)


def invoke_structured_or_freetext(
    structured_llm: Any | None,
    plain_llm: Any,
    prompt: Any,
    render: Callable[[T], str],
    agent_name: str,
) -> str:
    """Run the structured call and render to markdown; fall back to free-text on any failure.

    ``prompt`` is whatever the underlying LLM accepts (a string for chat
    invocations, a list of message dicts for chat models that take that
    shape). The same value is forwarded to the free-text path so the
    fallback sees the same input the structured call did.
    """
    if structured_llm is not None:
        try:
            result = structured_llm.invoke(prompt)
            if result is None:
                # A thinking model can answer in plain text instead of calling
                # the tool, leaving the parser with nothing to return. Treat it
                # as a structured miss and fall back, with a clear reason.
                raise ValueError("structured output returned no parsed result")
            return render(result)
        except Exception as exc:
            logger.warning(
                "%s: structured-output invocation failed (%s); retrying once as free text",
                agent_name, exc,
            )

    response = plain_llm.invoke(prompt)
    return response.content
