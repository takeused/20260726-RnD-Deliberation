"""하루 사용량 한도 초과 판별.

분당 한도(429, TPM/RPM)는 몇 초 기다리면 풀리므로 재시도하지만, 하루 한도(TPD/RPD)는 수 분~수 시간
뒤에야 풀린다. 이때 몇 초 간격으로 재시도하면 시간만 쓰고, 구조화 출력 재시도·자유 텍스트 폴백까지
거치며 같은 오류를 여러 번 낸다. 하루 한도는 즉시 멈추고, 체크포인트로 이어서 실행하도록 안내한다.

예) Groq: "Rate limit reached ... on tokens per day (TPD): Limit 200000, Used 194723, Requested 6678.
          Please try again in 10m5.232s."
"""

from __future__ import annotations

import re

_DAILY_RE = re.compile(r"per\s+day|\((?:TPD|RPD)\)", re.I)
_WAIT_RE = re.compile(r"try again in\s+((?:\d+(?:\.\d+)?[hms])+)", re.I)  # "10m5.232s" (끝의 마침표 제외)


class DailyQuotaExceeded(RuntimeError):
    """LLM 공급자의 하루 사용량 한도 초과. 재시도하지 않고 위로 올린다."""

    def __init__(self, message: str, retry_after: str | None = None):
        super().__init__(message)
        self.retry_after = retry_after


def as_daily_quota(exc: BaseException) -> DailyQuotaExceeded | None:
    """예외가 하루 한도 초과면 DailyQuotaExceeded로, 아니면 None."""
    if isinstance(exc, DailyQuotaExceeded):
        return exc
    text = str(exc)
    if "429" not in text and "rate limit" not in text.lower():
        return None
    if not _DAILY_RE.search(text):
        return None
    wait = _WAIT_RE.search(text)
    return DailyQuotaExceeded(text[:300], wait.group(1) if wait else None)


class RequestTooLarge(RuntimeError):
    """요청 하나가 공급자의 분당 토큰 한도보다 큼 (예: Groq 413). 기다려도 같은 결과라 재시도하지 않는다."""


def as_request_too_large(exc: BaseException) -> RequestTooLarge | None:
    if isinstance(exc, RequestTooLarge):
        return exc
    text = str(exc)
    if re.search(r"Error code:\s*413|request too large", text, re.I):
        return RequestTooLarge(text[:300])
    return None


def suggested_wait_seconds(exc: BaseException) -> float | None:
    """'try again in 1m2.5s' / '577ms' 같은 공급자 안내를 초로 바꾼다 (없으면 None)."""
    m = re.search(r"try again in\s+((?:\d+(?:\.\d+)?(?:ms|h|m|s))+)", str(exc), re.I)
    if not m:
        return None
    total = 0.0
    for value, unit in re.findall(r"(\d+(?:\.\d+)?)(ms|h|m|s)", m.group(1)):
        total += float(value) * {"ms": 0.001, "s": 1, "m": 60, "h": 3600}[unit]
    return total
