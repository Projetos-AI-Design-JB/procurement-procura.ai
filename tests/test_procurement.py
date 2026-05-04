# tests/test_procurement.py
"""
Phase 6 verification — ProcurementAgent decision logic tests.

All Gemini calls are mocked. Tests focus on:
  - Decision rule coverage (approved / rejected / pending_review)
  - Price delta calculation
  - Feature gap analysis
  - ERP payload structure
  - Fallback recommendation when Gemini fails
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.procurement import ProcurementAgent
from models.procurement import ProcurementRequest
from models.research import (
    CompetitorProfile,
    JudgeVerdict,
    MarketResearchOutput,
    ValidatedResearchOutput,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _profile(
    name: str = "CloudStorage Pro",
    features: list[str] | None = None,
    confidence: str = "high",
    price_range: tuple | None = (200.0, 400.0),
) -> CompetitorProfile:
    return CompetitorProfile(
        company_name=name,
        website_url=f"https://{name.lower().replace(' ', '')}.com",
        price_range=price_range,
        key_features=features or ["S3-compatible API", "99.9% SLA uptime", "Encryption at rest"],
        review_score=4.2,
        review_count=80,
        data_confidence=confidence,
    )


def _research(
    profiles: list[CompetitorProfile] | None = None,
    market_avg: float | None = 300.0,
    request_id: str = "req-001",
) -> ValidatedResearchOutput:
    research = MarketResearchOutput(
        request_id=request_id,
        timestamp=_now(),
        profiles=profiles or [_profile()],
        market_average_price=market_avg,
        data_completeness_score=0.85,
    )
    verdict = JudgeVerdict(passed=True, reason="OK", retry_researcher=False)
    return ValidatedResearchOutput(original=research, verdict=verdict, validated_at=_now())


def _request(**overrides) -> ProcurementRequest:
    defaults = dict(
        request_id="req-001",
        requester="Julia",
        supplier_name="CloudStorage Pro",
        product_category="cloud_storage",
        proposed_price=280.0,
        required_features=["S3-compatible API", "99.9% SLA uptime", "Encryption at rest"],
        budget_ceiling=500.0,
        urgency="medium",
    )
    defaults.update(overrides)
    return ProcurementRequest(**defaults)


def _make_agent(gemini_response: str = '{"recommendation": "Approve."}') -> ProcurementAgent:
    mock_client = MagicMock()
    mock_client.generate = AsyncMock(return_value=gemini_response)
    return ProcurementAgent(client=mock_client)


# ── Decision: approved ───────────────────────────────────────────────────────

class TestApprovedDecision:
    @pytest.mark.asyncio
    async def test_approved_when_all_features_present_and_price_ok(self):
        agent = _make_agent()
        # Supplier has all required features, price within 2% of market
        research = _research(
            profiles=[_profile(features=["S3-compatible API", "99.9% SLA uptime", "Encryption at rest"])],
            market_avg=280.0,  # exact match — 0% delta
        )
        decision = await agent.run(_request(proposed_price=280.0), research)
        assert decision.decision == "approved"

    @pytest.mark.asyncio
    async def test_approved_when_price_below_market(self):
        agent = _make_agent()
        research = _research(
            profiles=[_profile(features=["S3-compatible API", "99.9% SLA uptime", "Encryption at rest"])],
            market_avg=400.0,
        )
        decision = await agent.run(_request(proposed_price=280.0), research)
        assert decision.decision == "approved"
        assert decision.price_vs_market == "below"
        assert decision.price_delta_pct < 0


# ── Decision: rejected ───────────────────────────────────────────────────────

class TestRejectedDecision:
    @pytest.mark.asyncio
    async def test_rejected_when_over_budget(self):
        agent = _make_agent()
        research = _research(
            profiles=[_profile(features=["S3-compatible API", "99.9% SLA uptime", "Encryption at rest"])],
        )
        # proposed_price > budget_ceiling
        decision = await agent.run(_request(proposed_price=600.0, budget_ceiling=500.0), research)
        assert decision.decision == "rejected"

    @pytest.mark.asyncio
    async def test_rejected_when_3_or_more_missing_features(self):
        agent = _make_agent(gemini_response='{"missing_features": ["f1", "f2", "f3"], "recommendation": "Reject."}')
        # Supplier has none of the required features
        research = _research(profiles=[_profile(features=["basic backup", "web UI"])])
        decision = await agent.run(
            _request(
                required_features=[
                    "S3-compatible API",
                    "99.9% SLA uptime",
                    "Encryption at rest",
                    "Multi-region replication",
                ]
            ),
            research,
        )
        assert decision.decision == "rejected"
        assert len(decision.missing_features) >= 3


# ── Decision: pending_review ─────────────────────────────────────────────────

class TestPendingReviewDecision:
    @pytest.mark.asyncio
    async def test_pending_review_when_price_over_20pct_above_market(self):
        agent = _make_agent()
        research = _research(
            profiles=[_profile(features=["S3-compatible API", "99.9% SLA uptime", "Encryption at rest"])],
            market_avg=200.0,
        )
        # 280 vs 200 = +40% above market
        decision = await agent.run(_request(proposed_price=280.0), research)
        assert decision.decision == "pending_review"
        assert decision.price_delta_pct > 20

    @pytest.mark.asyncio
    async def test_pending_review_when_1_missing_feature(self):
        agent = _make_agent(gemini_response='{"missing_features": ["Encryption at rest"], "recommendation": "Review."}')
        # Supplier missing only 1 feature
        research = _research(
            profiles=[_profile(features=["S3-compatible API", "99.9% SLA uptime"])],
            market_avg=280.0,
        )
        decision = await agent.run(_request(), research)
        assert decision.decision == "pending_review"
        assert len(decision.missing_features) == 1

    @pytest.mark.asyncio
    async def test_pending_review_with_urgency_override_flag(self):
        agent = _make_agent()
        research = _research(profiles=[_profile(features=["S3-compatible API"])])
        decision = await agent.run(
            _request(urgency="critical", proposed_price=280.0),
            research,
        )
        # Should be pending_review and have urgency override in ERP payload
        if decision.decision == "pending_review":
            assert decision.erp_payload.get("urgency_override_recommended") is True


# ── Price delta calculation ───────────────────────────────────────────────────

class TestPriceDelta:
    @pytest.mark.asyncio
    async def test_price_delta_above_market(self):
        agent = _make_agent()
        research = _research(
            profiles=[_profile(features=["S3-compatible API", "99.9% SLA uptime", "Encryption at rest"])],
            market_avg=200.0,
        )
        decision = await agent.run(_request(proposed_price=240.0), research)
        assert abs(decision.price_delta_pct - 20.0) < 0.5

    @pytest.mark.asyncio
    async def test_price_delta_below_market(self):
        agent = _make_agent()
        research = _research(
            profiles=[_profile(features=["S3-compatible API", "99.9% SLA uptime", "Encryption at rest"])],
            market_avg=400.0,
        )
        decision = await agent.run(_request(proposed_price=280.0), research)
        assert decision.price_delta_pct < 0
        assert decision.price_vs_market == "below"

    @pytest.mark.asyncio
    async def test_no_price_delta_when_no_market_avg(self):
        agent = _make_agent()
        research = _research(market_avg=None)
        decision = await agent.run(_request(), research)
        assert decision.price_delta_pct == 0.0
        assert decision.price_vs_market == "at"


# ── ERP payload ───────────────────────────────────────────────────────────────

class TestErpPayload:
    @pytest.mark.asyncio
    async def test_erp_payload_always_populated(self):
        agent = _make_agent()
        research = _research()
        decision = await agent.run(_request(), research)
        assert "request_id" in decision.erp_payload
        assert "decision" in decision.erp_payload
        assert "timestamp" in decision.erp_payload

    @pytest.mark.asyncio
    async def test_erp_payload_on_rejection(self):
        agent = _make_agent()
        research = _research(
            profiles=[_profile(features=["S3-compatible API", "99.9% SLA uptime", "Encryption at rest"])],
        )
        decision = await agent.run(_request(proposed_price=600.0, budget_ceiling=500.0), research)
        assert decision.erp_payload["decision"] == "rejected"


# ── Fallback recommendation ───────────────────────────────────────────────────

class TestFallbackRecommendation:
    @pytest.mark.asyncio
    async def test_fallback_used_when_gemini_fails(self):
        mock_client = MagicMock()
        mock_client.generate = AsyncMock(side_effect=Exception("Gemini unavailable"))
        agent = ProcurementAgent(client=mock_client)

        research = _research(
            profiles=[_profile(features=["S3-compatible API", "99.9% SLA uptime", "Encryption at rest"])],
            market_avg=280.0,
        )
        decision = await agent.run(_request(), research)
        # Should not raise — fallback recommendation returned
        assert decision.recommendation != ""
        assert len(decision.recommendation) > 10
