from __future__ import annotations

import hashlib

AI_ANALYSIS_STAGE_TRADE = "TRADE_ANALYSIS"
AI_ANALYSIS_STAGE_BUY_PRECHECK = "BUY_PRECHECK"
AI_ANALYSIS_STAGE_LEGACY = "LEGACY_UNKNOWN"

AI_ANALYSIS_LEGACY_UNKNOWN = "LEGACY_UNKNOWN"
AI_ANALYSIS_SYSTEM_PROVIDER = "SYSTEM"
AI_ANALYSIS_DETERMINISTIC_HOLD_MODEL = "DETERMINISTIC_HOLD"

TRADE_ANALYSIS_PROMPT_VERSION = "trade_analysis.v1"
BUY_PRECHECK_PROMPT_VERSION = "buy_precheck.v2"


def hash_analysis_context(user_prompt: str) -> str:
    """provider에 전달한 불변 user prompt의 UTF-8 SHA-256을 반환합니다."""

    return hashlib.sha256(user_prompt.encode("utf-8")).hexdigest()
