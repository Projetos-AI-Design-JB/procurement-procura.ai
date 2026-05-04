# tests/test_judge.py
"""
Phase 5 verification — JudgeAgent business rule engine tests.

Covers all 4 rules:
  - completeness_below_threshold
  - insufficient_profiles
  - too_many_low_confidence
  - no_market_price_data

Also covers the retry flag logic and orchestrator retry loop.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.judge import JudgeAgent, _MAX_RETRIES
from core.utils import PipelineError
from models.research import (
    CompetitorProfile,
    JudgeVerdict,
    MarketResearchOutput,
    ResearchRequest,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _profile(confidence: str = "high", price_range=(100.0, 500.0)) -> CompetitorProfile:
    return CompetitorProfile(
        company_name="TestCo",
        website_url="https://test.com",
        price_range=price_range,
        key_features=["feat_a", "feat_b"],
        review_score=4.0,
        review_count=50,
        data_confidence=confidence,
    )


def _research(
    profiles=None,
    completeness: float = 0.85,
    avg_price: float | None = 300.0,
    request_id: str = "req-001",
) -> MarketResearchOutput:
    if profiles is None:
        profiles = [_profile(), _profile()]
    return MarketResearchOutput(
        request_id=request_id,
        timestamp=_now(),
        profiles=profiles,
        market_average_price=avg_price,
        data_completeness_score=completeness,
    )


def _make_judge() -> JudgeAgent:
    return JudgeAgent(client=MagicMock())


# ── Rule: completeness_below_threshold ───────────────────────────────────────

class TestCompletenessRule:
    def test_passes_at_threshold(self):
        judge = _make_judge()
        result = judge.evaluate(_research(completeness=0.70))
        assert "completeness_below_threshold" not in result.verdict.failed_rules

    def test_passes_above_threshold(self):
        judge = _make_judge()
        result = judge.evaluate(_research(completeness=0.95))
        assert result.verdict.passed is True

    def test_fails_below_threshold(self):
        judge = _make_judge()
        result = judge.evaluate(_research(completeness=0.69))
        assert "completeness_below_threshold" in result.verdict.failed_rules
        assert result.verdict.passed is False

    def test_fails_at_zero(self):
        judge = _make_judge()
        result = judge.evaluate(_research(completeness=0.0))
        assert "completeness_below_threshold" in result.verdict.failed_rules


# ── Rule: insufficient_profiles ──────────────────────────────────────────────

class TestInsufficientProfilesRule:
    def test_passes_with_two_profiles(self):
        judge = _make_judge()
        result = judge.evaluate(_research(profiles=[_profile(), _profile()]))
        assert "insufficient_profiles" not in result.verdict.failed_rules

    def test_fails_with_one_profile(self):
        judge = _make_judge()
        result = judge.evaluate(_research(profiles=[_profile()]))
        assert "insufficient_profiles" in result.verdict.failed_rules

    def test_fails_with_zero_profiles(self):
        judge = _make_judge()
        result = judge.evaluate(_research(profiles=[]))
        assert "insufficient_profiles" in result.verdict.failed_rules


# ── Rule: too_many_low_confidence ────────────────────────────────────────────

class TestLowConfidenceRule:
    def test_passes_when_all_high(self):
        judge = _make_judge()
        profiles = [_profile("high"), _profile("high"), _profile("medium")]
        result = judge.evaluate(_research(profiles=profiles))
        assert "too_many_low_confidence" not in result.verdict.failed_rules

    def test_passes_at_50_percent_low(self):
        judge = _make_judge()
        profiles = [_profile("high"), _profile("low")]  # 50% low = exactly at limit
        result = judge.evaluate(_research(profiles=profiles))
        assert "too_many_low_confidence" not in result.verdict.failed_rules

    def test_fails_when_majority_low(self):
        judge = _make_judge()
        profiles = [_profile("low"), _profile("low"), _profile("high")]  # 66% low
        result = judge.evaluate(_research(profiles=profiles))
        assert "too_many_low_confidence" in result.verdict.failed_rules

    def test_fails_when_all_low(self):
        judge = _make_judge()
        profiles = [_profile("low"), _profile("low")]
        result = judge.evaluate(_research(profiles=profiles))
        assert "too_many_low_confidence" in result.verdict.failed_rules


# ── Rule: no_market_price_data ───────────────────────────────────────────────

class TestMarketPriceRule:
    def test_passes_when_market_avg_set(self):
        judge = _make_judge()
        result = judge.evaluate(_research(avg_price=250.0))
        assert "no_market_price_data" not in result.verdict.failed_rules

    def test_passes_when_profiles_have_prices(self):
        judge = _make_judge()
        result = judge.evaluate(_research(avg_price=None, profiles=[_profile("high", (100.0, 300.0)), _profile("high")]))
        assert "no_market_price_data" not in result.verdict.failed_rules

    def test_fails_when_no_prices_anywhere(self):
        judge = _make_judge()
        # No market avg + all profiles have null price_range
        profiles = [
            CompetitorProfile(company_name="X", website_url="https://x.com", data_confidence="high"),
            CompetitorProfile(company_name="Y", website_url="https://y.com", data_confidence="high"),
        ]
        result = judge.evaluate(_research(avg_price=None, profiles=profiles))
        assert "no_market_price_data" in result.verdict.failed_rules


# ── Retry flag logic ─────────────────────────────────────────────────────────

class TestRetryLogic:
    def test_retry_true_on_first_failure(self):
        judge = _make_judge()
        result = judge.evaluate(_research(completeness=0.3), attempt=1)
        assert result.verdict.retry_researcher is True

    def test_retry_true_on_second_failure(self):
        judge = _make_judge()
        result = judge.evaluate(_research(completeness=0.3), attempt=2)
        assert result.verdict.retry_researcher is True

    def test_retry_false_on_max_attempt_failure(self):
        judge = _make_judge()
        result = judge.evaluate(_research(completeness=0.3), attempt=_MAX_RETRIES)
        assert result.verdict.retry_researcher is False

    def test_retry_false_when_passed(self):
        judge = _make_judge()
        result = judge.evaluate(_research(completeness=0.95), attempt=1)
        assert result.verdict.passed is True
        assert result.verdict.retry_researcher is False


# ── ValidatedResearchOutput structure ────────────────────────────────────────

class TestValidatedOutput:
    def test_passed_output_structure(self):
        judge = _make_judge()
        research = _research()
        vro = judge.evaluate(research)
        assert vro.original is research
        assert vro.verdict.passed is True
        assert vro.validated_at is not None

    def test_failed_output_has_failed_rules(self):
        judge = _make_judge()
        research = _research(completeness=0.1, profiles=[_profile()])
        vro = judge.evaluate(research)
        assert vro.verdict.passed is False
        assert len(vro.verdict.failed_rules) >= 1


# ── Orchestrator retry loop ──────────────────────────────────────────────────

class TestOrchestratorRetryLoop:
    """
    Tests the researcher → judge retry loop in the orchestrator.
    Mocks @researcher to return bad data N times, then good data.
    """

    @pytest.mark.asyncio
    async def test_passes_on_first_attempt(self):
        from core.orchestrator import Orchestrator

        good_research = _research(completeness=0.85)

        orchestrator = Orchestrator.__new__(Orchestrator)
        orchestrator._client = MagicMock()
        orchestrator._researcher = MagicMock()
        orchestrator._researcher.run = AsyncMock(return_value=good_research)
        orchestrator._judge = JudgeAgent(client=MagicMock())

        request = ResearchRequest(
            target_companies=["Acme"],
            product_category="cloud",
            procurement_request_id="req-001",
            search_keywords=["cloud"],
        )

        result = await orchestrator.run_research(request)
        assert result.verdict.passed is True
        assert orchestrator._researcher.run.call_count == 1

    @pytest.mark.asyncio
    async def test_succeeds_on_second_attempt(self):
        from core.orchestrator import Orchestrator

        bad_research = _research(completeness=0.3)
        good_research = _research(completeness=0.85)

        orchestrator = Orchestrator.__new__(Orchestrator)
        orchestrator._client = MagicMock()
        orchestrator._researcher = MagicMock()
        orchestrator._researcher.run = AsyncMock(side_effect=[bad_research, good_research])
        orchestrator._judge = JudgeAgent(client=MagicMock())

        request = ResearchRequest(
            target_companies=["Acme"],
            product_category="cloud",
            procurement_request_id="req-002",
            search_keywords=["cloud"],
        )

        result = await orchestrator.run_research(request)
        assert result.verdict.passed is True
        assert orchestrator._researcher.run.call_count == 2

    @pytest.mark.asyncio
    async def test_raises_pipeline_error_after_max_retries(self):
        from core.orchestrator import Orchestrator

        bad_research = _research(completeness=0.1)  # always fails

        orchestrator = Orchestrator.__new__(Orchestrator)
        orchestrator._client = MagicMock()
        orchestrator._researcher = MagicMock()
        orchestrator._researcher.run = AsyncMock(return_value=bad_research)
        orchestrator._judge = JudgeAgent(client=MagicMock())

        request = ResearchRequest(
            target_companies=["Acme"],
            product_category="cloud",
            procurement_request_id="req-003",
            search_keywords=["cloud"],
        )

        with pytest.raises(PipelineError) as exc_info:
            await orchestrator.run_research(request)

        assert exc_info.value.stage == "judge.retry_exhausted"
        assert exc_info.value.request_id == "req-003"
        assert orchestrator._researcher.run.call_count == _MAX_RETRIES
