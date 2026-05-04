# tests/test_models.py
"""
Phase 2 verification: Pydantic schema validation tests.

Covers:
  - ResearchRequest validation
  - CompetitorProfile constraints (price_range, review_score)
  - MarketResearchOutput completeness_score bounds
  - ProcurementRequest constraints (price, features, budget)
  - FinalReport round-trip serialization
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from models.procurement import ProcurementDecision, ProcurementRequest
from models.report import CompetitionMatrix, CompetitorEntry, FinalReport
from models.research import (
    CompetitorProfile,
    JudgeVerdict,
    MarketResearchOutput,
    ResearchRequest,
    ValidatedResearchOutput,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _valid_profile(**overrides) -> CompetitorProfile:
    defaults = dict(
        company_name="Acme Corp",
        website_url="https://acme.example.com",
        price_range=(100.0, 500.0),
        key_features=["feature_a", "feature_b"],
        review_score=4.2,
        review_count=120,
        data_confidence="high",
    )
    defaults.update(overrides)
    return CompetitorProfile(**defaults)


def _valid_research_output(**overrides) -> MarketResearchOutput:
    defaults = dict(
        request_id="req-001",
        timestamp=_now(),
        profiles=[_valid_profile()],
        market_average_price=300.0,
        data_completeness_score=0.85,
    )
    defaults.update(overrides)
    return MarketResearchOutput(**defaults)


def _valid_procurement_request(**overrides) -> ProcurementRequest:
    defaults = dict(
        request_id="req-001",
        requester="Julia",
        supplier_name="TechSupplier Inc",
        product_category="cloud_storage",
        proposed_price=280.0,
        required_features=["feature_a", "feature_b"],
        budget_ceiling=500.0,
        urgency="medium",
    )
    defaults.update(overrides)
    return ProcurementRequest(**defaults)


# ---------------------------------------------------------------------------
# ResearchRequest
# ---------------------------------------------------------------------------

class TestResearchRequest:
    def test_valid(self):
        req = ResearchRequest(
            target_companies=["Acme Corp"],
            product_category="cloud storage",
            procurement_request_id="req-001",
            search_keywords=["S3", "object storage"],
        )
        assert req.max_sources_per_company == 5

    def test_default_max_sources(self):
        req = ResearchRequest(
            target_companies=["X"],
            product_category="saas",
            procurement_request_id="req-002",
            search_keywords=["saas"],
        )
        assert req.max_sources_per_company == 5

    def test_empty_target_companies_rejected(self):
        with pytest.raises(ValidationError):
            ResearchRequest(
                target_companies=[],  # min_length=1
                product_category="saas",
                procurement_request_id="req-003",
                search_keywords=["saas"],
            )

    def test_max_sources_too_high(self):
        with pytest.raises(ValidationError):
            ResearchRequest(
                target_companies=["X"],
                product_category="saas",
                procurement_request_id="req-004",
                search_keywords=["saas"],
                max_sources_per_company=25,  # le=20
            )


# ---------------------------------------------------------------------------
# CompetitorProfile
# ---------------------------------------------------------------------------

class TestCompetitorProfile:
    def test_valid_minimal(self):
        p = CompetitorProfile(
            company_name="Minimal Corp",
            website_url="https://minimal.com",
            data_confidence="low",
        )
        assert p.price_range is None
        assert p.scraping_errors == []

    def test_valid_full(self):
        p = _valid_profile()
        assert p.review_score == 4.2

    def test_invalid_price_range_min_gt_max(self):
        with pytest.raises(ValidationError, match="price_range min"):
            CompetitorProfile(
                company_name="Bad Corp",
                website_url="https://bad.com",
                price_range=(500.0, 100.0),  # min > max
                data_confidence="high",
            )

    def test_review_score_out_of_bounds(self):
        with pytest.raises(ValidationError):
            CompetitorProfile(
                company_name="Over Corp",
                website_url="https://over.com",
                review_score=5.5,  # le=5.0
                data_confidence="medium",
            )

    def test_negative_review_count(self):
        with pytest.raises(ValidationError):
            CompetitorProfile(
                company_name="Neg Corp",
                website_url="https://neg.com",
                review_count=-1,  # ge=0
                data_confidence="medium",
            )


# ---------------------------------------------------------------------------
# MarketResearchOutput
# ---------------------------------------------------------------------------

class TestMarketResearchOutput:
    def test_valid(self):
        out = _valid_research_output()
        assert out.data_completeness_score == 0.85

    def test_completeness_score_above_1(self):
        with pytest.raises(ValidationError):
            _valid_research_output(data_completeness_score=1.5)  # le=1.0

    def test_completeness_score_below_0(self):
        with pytest.raises(ValidationError):
            _valid_research_output(data_completeness_score=-0.1)  # ge=0.0

    def test_empty_profiles_allowed(self):
        # Researcher may return 0 profiles (judge will reject later)
        out = _valid_research_output(profiles=[], data_completeness_score=0.0)
        assert out.profiles == []


# ---------------------------------------------------------------------------
# JudgeVerdict + ValidatedResearchOutput
# ---------------------------------------------------------------------------

class TestJudgeVerdict:
    def test_passed_verdict(self):
        v = JudgeVerdict(
            passed=True,
            reason="All rules satisfied.",
            retry_researcher=False,
        )
        assert v.failed_rules == []

    def test_failed_verdict(self):
        v = JudgeVerdict(
            passed=False,
            reason="Completeness score below threshold.",
            retry_researcher=True,
            failed_rules=["completeness_below_threshold"],
        )
        assert v.retry_researcher is True

    def test_validated_research_output(self):
        research = _valid_research_output()
        verdict = JudgeVerdict(passed=True, reason="OK", retry_researcher=False)
        vro = ValidatedResearchOutput(
            original=research,
            verdict=verdict,
            validated_at=_now(),
        )
        assert vro.verdict.passed is True


# ---------------------------------------------------------------------------
# ProcurementRequest
# ---------------------------------------------------------------------------

class TestProcurementRequest:
    def test_valid(self):
        req = _valid_procurement_request()
        assert req.urgency == "medium"

    def test_zero_price_rejected(self):
        with pytest.raises(ValidationError):
            _valid_procurement_request(proposed_price=0)  # gt=0

    def test_negative_budget_rejected(self):
        with pytest.raises(ValidationError):
            _valid_procurement_request(budget_ceiling=-100)  # gt=0

    def test_empty_features_rejected(self):
        with pytest.raises(ValidationError):
            _valid_procurement_request(required_features=[])  # min_length=1

    def test_invalid_urgency(self):
        with pytest.raises(ValidationError):
            _valid_procurement_request(urgency="extreme")  # not in Literal


# ---------------------------------------------------------------------------
# ProcurementDecision
# ---------------------------------------------------------------------------

class TestProcurementDecision:
    def test_valid_approved(self):
        decision = ProcurementDecision(
            request_id="req-001",
            decision="approved",
            price_vs_market="below",
            price_delta_pct=-8.5,
            missing_features=[],
            recommendation="Approve: price is 8.5% below market and all features present.",
            erp_payload={"request_id": "req-001", "decision": "approved"},
            decided_at=_now(),
        )
        assert decision.decision == "approved"

    def test_invalid_decision_value(self):
        with pytest.raises(ValidationError):
            ProcurementDecision(
                request_id="req-001",
                decision="maybe",  # not in Literal
                price_vs_market="at",
                price_delta_pct=0.0,
                recommendation="...",
                erp_payload={},
                decided_at=_now(),
            )


# ---------------------------------------------------------------------------
# FinalReport round-trip
# ---------------------------------------------------------------------------

class TestFinalReport:
    def _build_report(self) -> FinalReport:
        decision = ProcurementDecision(
            request_id="req-001",
            decision="approved",
            price_vs_market="below",
            price_delta_pct=-8.5,
            recommendation="Approve.",
            erp_payload={"request_id": "req-001"},
            decided_at=_now(),
        )
        matrix = CompetitionMatrix(
            category="cloud storage",
            market_average_price=300.0,
            entries=[
                CompetitorEntry(
                    company_name="Acme Corp",
                    price_range=(200.0, 400.0),
                    key_features=["feature_a"],
                    review_score=4.1,
                    data_confidence="high",
                )
            ],
        )
        return FinalReport(
            report_id="rpt-001",
            request_id="req-001",
            generated_at=_now(),
            procurement_decision=decision,
            competition_matrix=matrix,
            executive_summary="Market analysis shows TechSupplier is competitively priced.",
            recommended_action="Approve the purchase order for TechSupplier Inc.",
        )

    def test_build_and_serialize(self):
        report = self._build_report()
        json_str = report.model_dump_json()
        assert "req-001" in json_str

    def test_round_trip_validation(self):
        from pydantic import TypeAdapter

        report = self._build_report()
        json_str = report.model_dump_json()
        ta = TypeAdapter(FinalReport)
        restored = ta.validate_json(json_str)
        assert restored.report_id == report.report_id
        assert restored.procurement_decision.decision == "approved"
