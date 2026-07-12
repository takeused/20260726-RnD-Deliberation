import os

_RDAGENTS_HOME = os.path.join(os.path.expanduser("~"), ".rdagents")

_ENV_OVERRIDES = {
    "RDAGENTS_LLM_PROVIDER":         "llm_provider",
    "RDAGENTS_DEEP_THINK_LLM":       "deep_think_llm",
    "RDAGENTS_QUICK_THINK_LLM":      "quick_think_llm",
    "RDAGENTS_LLM_BACKEND_URL":      "backend_url",
    "RDAGENTS_OUTPUT_LANGUAGE":       "output_language",
    "RDAGENTS_MAX_DEBATE_ROUNDS":    "max_debate_rounds",
    "RDAGENTS_MAX_AUDIT_ROUNDS":     "max_audit_rounds",
    "RDAGENTS_CHECKPOINT_ENABLED":   "checkpoint_enabled",
    "RDAGENTS_MAX_MEMORY_ENTRIES":  "max_memory_entries",
    "RDAGENTS_MAX_MEMORY_CHARS":    "max_memory_chars",
    "RDAGENTS_MAX_REPORT_BYTES":   "max_report_bytes",
    "RDAGENTS_REPORT_CHUNK_CHARS": "report_chunk_chars",
    "RDAGENTS_REPORT_TOP_K":       "report_retrieval_top_k",
    "RDAGENTS_TEMPERATURE":          "temperature",
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
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": os.getenv(
        "RDAGENTS_RESULTS_DIR",
        os.path.join(_RDAGENTS_HOME, "logs"),
    ),
    "data_cache_dir": os.getenv(
        "RDAGENTS_CACHE_DIR",
        os.path.join(_RDAGENTS_HOME, "cache"),
    ),
    "memory_log_path": os.getenv(
        "RDAGENTS_MEMORY_LOG_PATH",
        os.path.join(_RDAGENTS_HOME, "memory", "review_memory.md"),
    ),
    "checkpoint_path": os.getenv(
        "RDAGENTS_CHECKPOINT_PATH",
        os.path.join(_RDAGENTS_HOME, "checkpoints", "reviews.sqlite"),
    ),
    "sample_data_dir": os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "sample_data"),
    ),
    # LLM 설정
    "llm_provider": "google",
    "deep_think_llm": "gemini-3.1-pro-preview",
    "quick_think_llm": "gemini-3.5-flash",
    "backend_url": None,
    # 프로바이더별 사고 수준 설정
    "google_thinking_level": None,
    "openai_reasoning_effort": None,
    "anthropic_effort": None,
    "temperature": None,
    # 체크포인트
    "checkpoint_enabled": False,
    "max_memory_entries": 5,
    "max_memory_chars": 12000,
    "max_report_bytes": 5_000_000,
    "report_chunk_chars": 4000,
    "report_retrieval_top_k": 4,
    # 출력 언어
    "output_language": "Korean",
    # 토론 및 심의 설정
    "max_debate_rounds": 2,    # 찬반 토론 라운드 수
    "max_audit_rounds": 1,     # 재정 검토 토론 라운드 수
    "max_recur_limit": 150,    # LangGraph 재귀 한도 (6인 분석가이므로 여유 확보)
    # 선택할 분석가 목록
    "selected_analysts": (
        "tech_value", "tech_trend", "economic",
        "policy", "feasibility", "regulatory",
    ),
})
