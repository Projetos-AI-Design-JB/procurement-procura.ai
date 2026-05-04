# models/procurement.py
"""
Pydantic v2 schemas for the procurement triage chain.

Flow:
  ProcurementRequest + ValidatedResearchOutput → [procurement_analyst] → ProcurementDecision
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ProcurementRequest(BaseModel):
    """
    Internal purchase request submitted by a requester.
    This is the initial human input that drives the entire pipeline.
    """

    request_id: str = Field(description="Unique identifier (UUID) for this procurement request.")
    requester: str = Field(description="Name or ID of the person/department submitting the request.")
    supplier_name: str = Field(description="Name of the proposed supplier/vendor.")
    product_category: str = Field(description="The market category for this supplier (e.g. CRM, Cloud Storage).")
    proposed_price: float = Field(gt=0, description="Price quoted by the supplier (USD).")
    required_features: list[str] = Field(
        min_length=1,
        description="Features the supplier must provide to satisfy this request.",
    )
    budget_ceiling: float = Field(gt=0, description="Maximum approved budget for this purchase (USD).")
    urgency: Literal["low", "medium", "high", "critical"] = Field(
        description="Business urgency level; 'critical' triggers special review flags."
    )


class ProcurementDecision(BaseModel):
    """
    Structured triage decision produced by the @procurement_analyst agent.
    Passed to @synthesizer for final report assembly.
    """

    request_id: str
    decision: Literal["approved", "rejected", "pending_review"] = Field(
        description=(
            "approved = meets all criteria; "
            "rejected = over budget or 3+ missing features; "
            "pending_review = price outlier or 1-2 missing features."
        )
    )
    price_vs_market: Literal["below", "at", "above"] = Field(
        description="Position of proposed_price relative to market average."
    )
    price_delta_pct: float = Field(
        description=(
            "Percentage difference from market average. "
            "Positive = above market, negative = below market."
        )
    )
    missing_features: list[str] = Field(
        default_factory=list,
        description="required_features not found in the supplier's profile.",
    )
    recommendation: str = Field(
        description="1-2 sentence actionable recommendation for the procurement director."
    )
    erp_payload: dict[str, Any] = Field(
        description="Structured payload formatted for ERP/WMS system integration."
    )
    decided_at: datetime
