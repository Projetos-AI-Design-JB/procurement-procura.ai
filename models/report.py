# models/report.py
"""
Pydantic v2 schemas for the final synthesizer report.

Flow:
  ValidatedResearchOutput + ProcurementDecision → [synthesizer] → FinalReport
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from models.procurement import ProcurementDecision


class CompetitorEntry(BaseModel):
    """Condensed competitor row for the competition matrix in the final report."""

    company_name: str
    price_range: tuple[float, float] | None = None
    key_features: list[str] = Field(default_factory=list)
    feature_evidence: dict[str, str] = Field(default_factory=dict)
    review_score: float | None = Field(default=None, ge=0.0, le=5.0)
    data_confidence: Literal["high", "medium", "low"]


class CompetitionMatrix(BaseModel):
    """Competitive intelligence matrix included in the final report."""

    category: str
    market_average_price: float | None = None
    entries: list[CompetitorEntry] = Field(default_factory=list)


class FinalReport(BaseModel):
    """
    Complete pipeline output produced by @synthesizer.

    Written to:
      output/report_<request_id>.md   (Markdown for stakeholders)
      output/report_<request_id>.json (validated JSON for integrations)
    """

    report_id: str = Field(description="Unique ID for this report artifact.")
    request_id: str = Field(description="Links back to the originating ProcurementRequest.")
    supplier_name: str | None = Field(default=None, description="The name of the supplier being evaluated.")
    generated_at: datetime
    procurement_decision: ProcurementDecision
    competition_matrix: CompetitionMatrix
    executive_summary: str = Field(
        description="3-5 sentences summarizing market context and decision rationale."
    )
    recommended_action: str = Field(
        description="Single clear directive for the procurement director."
    )
    data_quality_notes: list[str] = Field(
        default_factory=list,
        description="Warnings about low-confidence data or scraping errors.",
    )
    pipeline_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Audit metadata: retry count, timing, agent versions.",
    )
