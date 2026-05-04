# tests/test_e2e.py
"""
Phase 7 — End-to-end pipeline integration tests.

Uses the full Orchestrator with all Gemini calls mocked.
Validates:
  - Full pipeline runs start to finish without error
  - Both output files are written (report_*.md and report_*.json)
  - JSON output validates against FinalReport Pydantic model
  - PipelineError raised correctly when judge exhausts retries
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import TypeAdapter

from core.orchestrator import Orchestrator
from core.utils import PipelineError
from models.report import FinalReport
from models.research import CompetitorProfile, MarketResearchOutput


# ── Mock Gemini response factory ─────────────────────────────────────────────

def _mock_research_response(request_id: str, completeness: float = 0.85) -> str:
    """Build a valid MarketResearchOutput JSON string as Gemini would return it."""
    data = {
        "request_id": request_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "profiles": [
            {
                "company_name": "CloudStorage Pro",
                "website_url": "https://cloudstoragepro.com",
                "price_range": [240.0, 360.0],
                "key_features": [
                    "S3-compatible API",
                    "99.9% SLA uptime",
                    "Encryption at rest",
                    "Multi-region replication",
                    "Pay-as-you-go pricing",
                ],
                "review_score": 4.3,
                "review_count": 120,
                "seo_traffic_estimate": 45000,
                "data_confidence": "high",
                "scraping_errors": [],
            },
            {
                "company_name": "DataVault Inc",
                "website_url": "https://datavaultinc.com",
                "price_range": [300.0, 420.0],
                "key_features": ["S3-compatible API", "99.9% SLA uptime", "basic backup"],
                "review_score": 3.8,
                "review_count": 45,
                "seo_traffic_estimate": 18000,
                "data_confidence": "medium",
                "scraping_errors": [],
            },
        ],
        "market_average_price": 300.0,
        "data_completeness_score": completeness,
    }
    return json.dumps(data)


def _mock_recommendation_response() -> str:
    return json.dumps({"recommendation": "Approve: CloudStorage Pro meets all requirements at a competitive price."})


def _mock_synthesis_response() -> str:
    return json.dumps({
        "executive_summary": (
            "Market analysis identified 2 suppliers in the cloud storage category. "
            "CloudStorage Pro is priced 6.7% below the market average of $300/month. "
            "All 5 required features are present in the supplier profile. "
            "The procurement triage system approved the purchase request."
        ),
        "recommended_action": "Approve the purchase order for CloudStorage Pro at $280/month.",
    })


# ── Helpers ──────────────────────────────────────────────────────────────────

def _sample_request_json(request_id: str = "req-e2e-001") -> dict:
    return {
        "request_id": request_id,
        "requester": "Julia",
        "supplier_name": "CloudStorage Pro",
        "product_category": "cloud_storage",
        "proposed_price": 280.0,
        "required_features": [
            "S3-compatible API",
            "99.9% SLA uptime",
            "Encryption at rest",
            "Multi-region replication",
            "Pay-as-you-go pricing",
        ],
        "budget_ceiling": 500.0,
        "urgency": "medium",
    }


def _make_orchestrator(
    output_dir: Path,
    gemini_responses: list[str],
) -> Orchestrator:
    """Create an Orchestrator with a mocked GeminiClient."""
    mock_client = MagicMock()
    mock_client.generate = AsyncMock(side_effect=gemini_responses)
    
    mock_search_client = MagicMock()
    mock_search_client.search = AsyncMock(return_value=[])

    mock_db = MagicMock()
    mock_db.save_request = AsyncMock()
    mock_db.save_report = AsyncMock()
    mock_db.update_request_status = AsyncMock()

    orch = Orchestrator.__new__(Orchestrator)
    from agents.judge import JudgeAgent
    from agents.procurement import ProcurementAgent
    from agents.researcher import ResearcherAgent
    from agents.synthesizer import SynthesizerAgent

    orch._client = mock_client
    orch._db = mock_db
    orch._researcher = ResearcherAgent(client=mock_client, search=mock_search_client)
    orch._judge = JudgeAgent(client=mock_client)
    orch._procurement = ProcurementAgent(client=mock_client)
    orch._synthesizer = SynthesizerAgent(client=mock_client, output_dir=output_dir)

    # Mock scraper so researcher doesn't make real HTTP calls
    async def _noop_scraper(urls, **kwargs):
        from core.scraper import ScrapingResult
        return [ScrapingResult(url=u, success=False, error="mocked") for u in urls]

    import core.scraper
    orch._researcher._scrape = _noop_scraper

    return orch


# ── E2E: Happy path ───────────────────────────────────────────────────────────

class TestE2EHappyPath:
    @pytest.mark.asyncio
    async def test_full_pipeline_writes_both_output_files(self):
        """Full pipeline run produces report_*.md and report_*.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            request_id = "req-e2e-001"
            request_data = _sample_request_json(request_id)

            # Write request JSON to temp file
            req_file = output_dir / "request.json"
            req_file.write_text(json.dumps(request_data), encoding="utf-8")

            # Gemini is called 3 times: researcher, procurement, synthesizer
            responses = [
                _mock_research_response(request_id),
                _mock_recommendation_response(),
                _mock_synthesis_response(),
            ]

            with patch("core.scraper.fetch_pages", new_callable=AsyncMock) as mock_scrape:
                from core.scraper import ScrapingResult
                mock_scrape.return_value = [
                    ScrapingResult(url="https://cloudstoragepro.com", success=False, error="mocked")
                ]

                orch = _make_orchestrator(output_dir, responses)
                report = await orch.run(req_file)

            # Both output files must exist
            md_path = output_dir / f"report_{request_id}.md"
            json_path = output_dir / f"report_{request_id}.json"

            assert md_path.exists(), f"Markdown report not found: {md_path}"
            assert json_path.exists(), f"JSON report not found: {json_path}"

    @pytest.mark.asyncio
    async def test_json_output_validates_against_final_report_model(self):
        """The JSON output must pass FinalReport Pydantic validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            request_id = "req-e2e-002"
            request_data = _sample_request_json(request_id)

            req_file = output_dir / "request.json"
            req_file.write_text(json.dumps(request_data), encoding="utf-8")

            responses = [
                _mock_research_response(request_id),
                _mock_recommendation_response(),
                _mock_synthesis_response(),
            ]

            with patch("core.scraper.fetch_pages", new_callable=AsyncMock) as mock_scrape:
                from core.scraper import ScrapingResult
                mock_scrape.return_value = [
                    ScrapingResult(url="https://cloudstoragepro.com", success=False, error="mocked")
                ]
                orch = _make_orchestrator(output_dir, responses)
                await orch.run(req_file)

            json_path = output_dir / f"report_{request_id}.json"
            json_content = json_path.read_text(encoding="utf-8")

            ta = TypeAdapter(FinalReport)
            restored = ta.validate_json(json_content)
            assert restored.request_id == request_id
            assert restored.procurement_decision.decision in ("approved", "rejected", "pending_review")

    @pytest.mark.asyncio
    async def test_pipeline_returns_final_report_object(self):
        """Orchestrator.run() returns a FinalReport Pydantic object."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            request_id = "req-e2e-003"
            req_file = output_dir / "request.json"
            req_file.write_text(json.dumps(_sample_request_json(request_id)), encoding="utf-8")

            responses = [
                _mock_research_response(request_id),
                _mock_recommendation_response(),
                _mock_synthesis_response(),
            ]

            with patch("core.scraper.fetch_pages", new_callable=AsyncMock) as mock_scrape:
                from core.scraper import ScrapingResult
                mock_scrape.return_value = [
                    ScrapingResult(url="https://cloudstoragepro.com", success=False, error="mocked")
                ]
                orch = _make_orchestrator(output_dir, responses)
                report = await orch.run(req_file)

            assert isinstance(report, FinalReport)
            assert report.request_id == request_id
            assert report.report_id.startswith("rpt-")

    @pytest.mark.asyncio
    async def test_markdown_report_contains_key_sections(self):
        """Markdown report has all required sections."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            request_id = "req-e2e-004"
            req_file = output_dir / "request.json"
            req_file.write_text(json.dumps(_sample_request_json(request_id)), encoding="utf-8")

            responses = [
                _mock_research_response(request_id),
                _mock_recommendation_response(),
                _mock_synthesis_response(),
            ]

            with patch("core.scraper.fetch_pages", new_callable=AsyncMock) as mock_scrape:
                from core.scraper import ScrapingResult
                mock_scrape.return_value = [
                    ScrapingResult(url="https://x.com", success=False, error="mocked")
                ]
                orch = _make_orchestrator(output_dir, responses)
                await orch.run(req_file)

            md_content = (output_dir / f"report_{request_id}.md").read_text(encoding="utf-8")
            assert "## Executive Summary" in md_content
            assert "## Procurement Decision" in md_content
            assert "## Competitive Intelligence Matrix" in md_content
            assert "## Pipeline Metadata" in md_content


# ── E2E: Retry exhaustion ─────────────────────────────────────────────────────

class TestE2ERetryExhaustion:
    @pytest.mark.asyncio
    async def test_pipeline_error_raised_after_max_retries(self):
        """PipelineError is raised when researcher always returns bad data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            request_id = "req-fail-001"
            req_file = output_dir / "request.json"
            req_file.write_text(json.dumps(_sample_request_json(request_id)), encoding="utf-8")

            # Always return incomplete research (completeness=0.3 → judge fails)
            bad_response = _mock_research_response(request_id, completeness=0.3)
            # Return bad data for all 3 retry attempts
            responses = [bad_response, bad_response, bad_response]

            with patch("core.scraper.fetch_pages", new_callable=AsyncMock) as mock_scrape:
                from core.scraper import ScrapingResult
                mock_scrape.return_value = [
                    ScrapingResult(url="https://x.com", success=False, error="mocked")
                ]
                orch = _make_orchestrator(output_dir, responses)

                with pytest.raises(PipelineError) as exc_info:
                    await orch.run(req_file)

            assert "judge" in exc_info.value.stage
            assert exc_info.value.request_id == request_id
