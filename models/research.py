# models/research.py
"""
Pydantic v2 schemas for the researcher ↔ judge chain.

Flow:
  ResearchRequest → [researcher] → MarketResearchOutput
                 → [judge]       → ValidatedResearchOutput
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class ResearchRequest(BaseModel):
    """Input contract for the @researcher agent."""

    target_companies: list[str] = Field(min_length=1, description="Companies/suppliers to research.")
    product_category: str = Field(description="Product or service category (e.g. 'cloud storage').")
    procurement_request_id: str = Field(description="UUID linking this research to the purchase request.")
    search_keywords: list[str] = Field(description="Keywords to guide research focus.")
    max_sources_per_company: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum number of web sources to consult per company.",
    )


class CompetitorProfile(BaseModel):
    """Data profile for a single competitor or supplier."""

    company_name: str
    website_url: str | None = Field(default=None, description="Company website URL.")
    price_range: tuple[float, float] | None = Field(
        default=None,
        description="(min_price, max_price) in USD. Null if not found.",
    )
    key_features: list[str] = Field(default_factory=list)
    feature_evidence: dict[str, str] = Field(
        default_factory=dict,
        description="Maps feature names to the evidence found (url or text snippet)."
    )
    review_score: float | None = Field(default=None, ge=0.0, le=5.0)
    review_count: int | None = Field(default=None, ge=0)
    seo_traffic_estimate: int | None = Field(
        default=None,
        description="Estimated monthly web visits.",
    )
    data_confidence: Literal["high", "medium", "low"] = Field(
        description=(
            "high = official page / verified platform; "
            "medium = third-party aggregator; "
            "low = estimated / inferred."
        )
    )
    scraping_errors: list[str] = Field(
        default_factory=list,
        description="Error messages for any failed data retrieval attempts.",
    )

    @field_validator("price_range", mode="before")
    @classmethod
    def validate_price_range(cls, v: object) -> object:
        if v is not None and isinstance(v, (list, tuple)) and len(v) == 2:
            lo, hi = v
            # Gemini might return [10, null] if there's only one price. Fix it:
            if lo is not None and hi is None:
                hi = lo
            elif lo is None and hi is not None:
                lo = hi
            elif lo is None and hi is None:
                return None
                
            if lo is not None and hi is not None:
                try:
                    if float(lo) > float(hi):
                        raise ValueError(f"price_range min ({lo}) must be <= max ({hi}).")
                except (ValueError, TypeError):
                    pass # Let Pydantic's native type validation catch non-floats
            return (lo, hi)
        return v


class MarketResearchOutput(BaseModel):
    """Output contract of the @researcher agent — input to @judge."""

    request_id: str
    timestamp: datetime
    profiles: list[CompetitorProfile] = Field(default_factory=list)
    market_average_price: float | None = Field(
        default=None,
        description="Mean price across all profiles that have price data.",
    )
    data_completeness_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Fraction of expected fields that contain non-null data (0.0–1.0).",
    )


class JudgeVerdict(BaseModel):
    """Quality gate verdict produced by the @judge agent."""

    passed: bool
    reason: str = Field(description="Human-readable explanation of the verdict.")
    retry_researcher: bool = Field(
        description="True if @researcher should be re-run; False if passed or terminal failure."
    )
    failed_rules: list[str] = Field(
        default_factory=list,
        description="IDs of business rules that failed (empty if passed).",
    )


class ValidatedResearchOutput(BaseModel):
    """Sealed output from @judge — safe to pass to @procurement_analyst."""

    original: MarketResearchOutput
    verdict: JudgeVerdict
    validated_at: datetime
