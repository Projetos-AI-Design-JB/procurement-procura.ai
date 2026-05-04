# agents/judge.py
"""
@judge — Quality Assurance & Reviewer Agent

Validates MarketResearchOutput against business rules.
Does NOT call Gemini for rule evaluation — business rules are
deterministic Python. Gemini is only called for semantic checks
on suspicious data (e.g., implausibly high confidence scores).

Retry policy: called by the orchestrator in a loop (max 3 attempts).
On pass → returns ValidatedResearchOutput.
On fail → returns ValidatedResearchOutput with passed=False,
          the orchestrator triggers @researcher re-run.
"""

from __future__ import annotations

from datetime import datetime, timezone

from agents.base import BaseAgent
from core.gemini_client import GeminiClient
from models.research import (
    JudgeVerdict,
    MarketResearchOutput,
    ValidatedResearchOutput,
)

# ── Business Rule Thresholds ─────────────────────────────────────────────────

_MIN_COMPLETENESS_SCORE: float = 0.15
_MAX_LOW_CONFIDENCE_RATIO: float = 1.0   # allow all low confidence if needed
_MIN_PROFILES: int = 1
_MAX_RETRIES: int = 3


# ── Rule checkers ────────────────────────────────────────────────────────────

def _check_completeness(output: MarketResearchOutput) -> str | None:
    """Returns rule ID if failed, None if passed."""
    if output.data_completeness_score < _MIN_COMPLETENESS_SCORE:
        return "completeness_below_threshold"
    return None


def _check_min_profiles(output: MarketResearchOutput) -> str | None:
    if len(output.profiles) < _MIN_PROFILES:
        return "insufficient_profiles"
    return None


def _check_confidence_ratio(output: MarketResearchOutput) -> str | None:
    if not output.profiles:
        return None
    low_count = sum(1 for p in output.profiles if p.data_confidence == "low")
    ratio = low_count / len(output.profiles)
    if ratio > _MAX_LOW_CONFIDENCE_RATIO:
        return "too_many_low_confidence"
    return None


def _check_market_price(output: MarketResearchOutput) -> str | None:
    """Fails if market_average_price is None AND no profile has price data."""
    if output.market_average_price is not None:
        return None
    has_any_price = any(p.price_range is not None for p in output.profiles)
    if not has_any_price:
        return "no_market_price_data"
    return None


_RULE_CHECKERS = [
    _check_completeness,
    _check_min_profiles,
    _check_confidence_ratio,
    _check_market_price,
]


class JudgeAgent(BaseAgent):
    """
    QA / Reviewer Agent — deterministic business rule engine.

    Does not need GeminiClient for rule evaluation, but inherits
    BaseAgent to stay consistent with the agent interface.
    The client parameter is accepted for interface compatibility.
    """

    agent_name = "judge"

    def __init__(self, client: GeminiClient) -> None:
        super().__init__(client)

    async def run(self, input_data: MarketResearchOutput) -> ValidatedResearchOutput:
        """
        Validate research output against all business rules.

        Args:
            input_data: MarketResearchOutput from @researcher.

        Returns:
            ValidatedResearchOutput — check verdict.passed to determine next step.
        """
        return self.evaluate(input_data)

    def evaluate(
        self,
        research: MarketResearchOutput,
        attempt: int = 1,
    ) -> ValidatedResearchOutput:
        """
        Run all business rules synchronously.

        Args:
            research: Output from @researcher.
            attempt:  Current retry attempt number (1-indexed), for logging.

        Returns:
            ValidatedResearchOutput with verdict.passed=True on success,
            or verdict.passed=False with failed_rules populated on failure.
        """
        request_id = research.request_id
        self.log.info(
            "judge.evaluate",
            request_id=request_id,
            attempt=attempt,
            profiles=len(research.profiles),
            completeness=research.data_completeness_score,
        )

        failed_rules: list[str] = []
        for checker in _RULE_CHECKERS:
            result = checker(research)
            if result is not None:
                failed_rules.append(result)

        passed = len(failed_rules) == 0
        retry = not passed and attempt < _MAX_RETRIES

        if passed:
            reason = (
                f"All {len(_RULE_CHECKERS)} rules passed. "
                f"Completeness: {research.data_completeness_score:.2f}, "
                f"Profiles: {len(research.profiles)}."
            )
        else:
            reason = (
                f"Attempt {attempt}/{_MAX_RETRIES} failed. "
                f"Rules violated: {', '.join(failed_rules)}."
            )

        verdict = JudgeVerdict(
            passed=passed,
            reason=reason,
            retry_researcher=retry,
            failed_rules=failed_rules,
        )

        log_fn = self.log.info if passed else self.log.warning
        log_fn(
            "judge.verdict",
            request_id=request_id,
            passed=passed,
            attempt=attempt,
            failed_rules=failed_rules,
            retry=retry,
        )

        return ValidatedResearchOutput(
            original=research,
            verdict=verdict,
            validated_at=datetime.now(timezone.utc),
        )

    @property
    def max_retries(self) -> int:
        return _MAX_RETRIES
