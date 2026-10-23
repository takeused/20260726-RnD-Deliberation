import os

_RDAGENTS_HOME = os.path.join(os.path.expanduser("~"), ".rdagents")
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

_ENV_OVERRIDES = {
    "RDAGENTS_LLM_PROVIDER":         "llm_provider",
    "RDAGENTS_DEEP_THINK_LLM":       "deep_think_llm",
    "RDAGENTS_QUICK_THINK_LLM":      "quick_think_llm",
    "RDAGENTS_LLM_BACKEND_URL":      "backend_url",
    "RDAGENTS_OUTPUT_LANGUAGE":       "output_language",
    "RDAGENTS_MAX_DEBATE_ROUNDS":    "max_debate_rounds",
    "RDAGENTS_MAX_DEBATE_ISSUES":    "max_debate_issues",
    "RDAGENTS_MAX_AUDIT_ROUNDS":     "max_audit_rounds",
    "RDAGENTS_CHECKPOINT_ENABLED":   "checkpoint_enabled",
    "RDAGENTS_REVIEW_GATE":         "review_gate",
    "RDAGENTS_PROJECT_TYPE":        "project_type",
    "RDAGENTS_HUMAN_REVIEW":        "human_review",
    "RDAGENTS_PROMPT_CHAR_BUDGET":  "prompt_char_budget",
    "RDAGENTS_TOOL_RESULT_CHAR_BUDGET": "tool_result_char_budget",
    "RDAGENTS_MAX_ANALYST_TOOL_CALLS": "max_analyst_tool_calls",
    "RDAGENTS_MAX_MEMORY_ENTRIES":  "max_memory_entries",
    "RDAGENTS_MAX_MEMORY_CHARS":    "max_memory_chars",
    "RDAGENTS_MAX_REPORT_BYTES":   "max_report_bytes",
    "RDAGENTS_REPORT_CHUNK_CHARS": "report_chunk_chars",
    "RDAGENTS_REPORT_TOP_K":       "report_retrieval_top_k",
    "RDAGENTS_TEMPERATURE":          "temperature",
    "RDAGENTS_LLM_TIMEOUT":          "llm_timeout",
    "RDAGENTS_GOOGLE_THINKING_LEVEL":   "google_thinking_level",
    "RDAGENTS_OPENAI_REASONING_EFFORT": "openai_reasoning_effort",
    "RDAGENTS_ANTHROPIC_EFFORT":        "anthropic_effort",
}

_BOOL_TRUE = ("true", "1", "yes", "on")
_BOOL_FALSE = ("false", "0", "no", "off")


def _coerce(value: str, reference):
    """환경 변수 문자열을 기존 기본값의 타입으로 변환."""
    if isinstance(reference, bool):
        normalized = value.strip().lower()
        if normalized in _BOOL_TRUE:
            return True
        if normalized in _BOOL_FALSE:
            return False
        raise ValueError(
            f"expected a boolean ({'/'.join(_BOOL_TRUE + _BOOL_FALSE)}), got {value!r}"
        )
    if isinstance(reference, int) and not isinstance(reference, bool):
        return int(value)
    if isinstance(reference, float):
        return float(value)
    return value


def _apply_env_overrides(config: dict) -> dict:
    """RDAGENTS_* 환경 변수를 config 딕셔너리에 적용."""
    for env_var, key in _ENV_OVERRIDES.items():
        raw = os.environ.get(env_var)
        if raw is None or raw == "":
            continue
        try:
            config[key] = _coerce(raw, config.get(key))
        except ValueError as exc:
            raise ValueError(f"Invalid value for {env_var}: {exc}") from exc
    return config


DEFAULT_CONFIG = _apply_env_overrides({
    "project_dir": _PROJECT_ROOT,
    "results_dir": os.getenv(
        "RDAGENTS_RESULTS_DIR",
        os.path.join(_PROJECT_ROOT, "results"),
    ),
    "data_cache_dir": os.getenv(
        "RDAGENTS_CACHE_DIR",
        os.path.join(_RDAGENTS_HOME, "cache"),
    ),
    "memory_log_path": os.getenv(
        "RDAGENTS_MEMORY_LOG_PATH",
        os.path.join(_RDAGENTS_HOME, "memory", "review_memory.md"),
    ),
    "verification_history_path": os.getenv(
        "RDAGENTS_VERIFICATION_HISTORY",
        os.path.join(_RDAGENTS_HOME, "verification", "history.jsonl"),
    ),
    "checkpoint_path": os.getenv(
        "RDAGENTS_CHECKPOINT_PATH",
        os.path.join(_RDAGENTS_HOME, "checkpoints", "reviews.sqlite"),
    ),
    "question_bank_dir": os.getenv(
        "RDAGENTS_QUESTION_BANK_DIR",
        os.path.join(_RDAGENTS_HOME, "question_bank"),
    ),
    "question_bank_seed_dir": os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "question_bank_seed"),
    ),
    "sample_data_dir": os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "sample_data"),
    ),
    # LLM 설정
    "llm_provider": "groq",
    "deep_think_llm": "openai/gpt-oss-120b",
    "quick_think_llm": "openai/gpt-oss-120b",
    "backend_url": None,
    # 프로바이더별 사고 수준 설정
    "google_thinking_level": None,
    "openai_reasoning_effort": None,
    "anthropic_effort": None,
    "temperature": None,
    # Prevent a single unavailable provider request from stalling the whole
    # deliberation graph indefinitely.  Providers may override this with
    # RDAGENTS_LLM_TIMEOUT (seconds).
    "llm_timeout": 120,
    # 체크포인트
    "checkpoint_enabled": False,
    "max_memory_entries": 5,
    "max_memory_chars": 12000,
    "max_report_bytes": 5_000_000,
    "report_chunk_chars": 4000,
    "report_retrieval_top_k": 4,
    # 심의 관문 (부처심의 / 예타 / 예산조정 / 국회)
    "review_gate": "부처심의",
    # 사업 유형: auto면 원문 키워드로 판별 (dataflows/project_type.py), 산업형·공공임무형·혼합형이면 그대로 사용
    "project_type": "auto",
    # 노드별 긴 입력 절단 예산 (문자 수, 0 = 무제한). 소형 컨텍스트 백엔드용
    "prompt_char_budget": 0,
    # 분석가가 LLM에 보내는 도구 결과의 총 문자 수 상한 (0=무제한). 도구를 부를수록 결과가 쌓여
    # 분당 토큰 한도가 작은 공급자(Groq 무료 8,000)에서 요청 하나가 한도를 넘는 것을 막는다
    "tool_result_char_budget": 0,
    # 분석가 1명이 부를 수 있는 도구 횟수 (0=무제한). 도구를 부를 때마다 LLM 요청이 한 번 더 나가므로
    # 하루 토큰 한도가 작은 공급자에서 비용을 크게 줄인다 (NDMI 실행: 분석가 3명에 약 9만 토큰)
    "max_analyst_tool_calls": 0,
    # 출력 언어
    "output_language": "Korean",
    # 토론 및 심의 설정
    "max_debate_rounds": 2,    # (쟁점별 공방 이전 방식의 라운드 수. 지금은 max_debate_issues가 공방 길이를 정함)
    # 공방에 올릴 쟁점 수 상한 (쟁점 하나 = 패널 질의 + 발표자 방어). 반드시 올릴 쟁점이 많으면 2개까지 늘어남
    "max_debate_issues": 6,
    # 공방 전에 정책 판단이 필요한 '상' 쟁점을 사람에게 묻는다 (LangGraph interrupt, 체크포인트 필요)
    "human_review": False,
    "max_audit_rounds": 1,     # 재정 검토 토론 라운드 수
    "max_recur_limit": 200,    # LangGraph 재귀 한도 (분석가 노드 7개·쟁점별 공방이므로 여유 확보)
    # 선택할 분석가 목록: 분야 기술전문가 3명(노드 하나) + 기능별 분석가 6명
    "selected_analysts": (
        "domain_experts", "tech_value", "tech_trend", "economic",
        "policy", "feasibility", "regulatory",
    ),
})
