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
