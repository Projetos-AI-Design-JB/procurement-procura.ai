# agents/procurement.py
"""
@procurement_analyst — Procurement Triage Agent

Cross-references a ProcurementRequest with ValidatedResearchOutput
and produces a typed ProcurementDecision.

Decision logic (deterministic — Gemini used only for recommendation text):
  - proposed_price > budget_ceiling       → "rejected"
  - missing_features >= 3                → "rejected"
  - price_delta_pct > 20%                → "pending_review"
  - missing_features in [1, 2]           → "pending_review"
  - all checks pass                      → "approved"
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Literal

from agents.base import BaseAgent
from core.gemini_client import GeminiClient
from core.utils import PipelineError, extract_json
from models.procurement import ProcurementDecision, ProcurementRequest
from models.research import ValidatedResearchOutput

_SYSTEM_PROMPT = """\
You are a Senior Procurement Analyst and Technical Auditor. Given a procurement context,
perform TWO tasks in one response:

TASK 1 — Technical Gap Analysis:
- Compare 'required_features' against 'found_features'.
- Apply NUMERIC LOGIC: "RAM >=16GB" is SATISFIED by "32GB RAM". "Battery >=8h" is SATISFIED by "10 hours".
- Apply SEMANTIC MAPPING: "SSO" satisfies "SAML integration". "Thunderbolt 4" satisfies "USB-C high-speed".
- List ONLY features that are genuinely NOT satisfied.

TASK 2 — Recommendation (1-2 sentences):
- State decision clearly: "Approve", "Reject", or "Send for review".
- Include the most important quantitative reason.
- Be direct. No filler phrases.

Return ONLY valid JSON:
{
  "missing_features": ["Feature A", "Feature B"],
  "recommendation": "Your concise recommendation here."
}
If all features are met, return "missing_features": [].
"""


class ProcurementAgent(BaseAgent):
    """
    Procurement Triage Agent.

    Applies deterministic decision rules first, then calls Gemini
    only to generate the human-readable recommendation text.
    """

    agent_name = "procurement_analyst"

    def __init__(self, client: GeminiClient) -> None:
        super().__init__(client)

    async def run(
        self,
        request: ProcurementRequest,
        research: ValidatedResearchOutput,
    ) -> ProcurementDecision:
        """
        Triage a procurement request against validated market intelligence.

        Args:
            request:  The internal purchase request.
            research: Validated output from @researcher (approved by @judge).

        Returns:
            Typed ProcurementDecision with ERP payload.

        Raises:
            PipelineError: If Gemini recommendation generation fails.
        """
        self.log_start(request.request_id)

        market = research.original
        supplier_profile = next(
            (p for p in market.profiles if p.company_name.lower() == request.supplier_name.lower()),
            market.profiles[0] if market.profiles else None,
        )

        # ── 1. Combined Gemini call: feature audit + recommendation ────────────
        self.log.info("procurement.combined_audit", request_id=request.request_id)
        
        context_for_gemini = {
            "supplier_name": request.supplier_name,
            "required_features": request.required_features,
            "found_features": supplier_profile.key_features if supplier_profile else [],
            "proposed_price": request.proposed_price,
            "market_average_price": market.market_average_price,
            "budget_ceiling": request.budget_ceiling,
            "urgency": request.urgency,
        }
        
        missing_features: list[str] = []
        recommendation: str = ""
        
        try:
            raw = await self.client.generate(
                _SYSTEM_PROMPT,
                json.dumps(context_for_gemini, ensure_ascii=False),
            )
            parsed = extract_json(raw)
            missing_features = parsed.get("missing_features", [])
            if not isinstance(missing_features, list):
                missing_features = []
            recommendation = parsed.get("recommendation", "")
        except Exception as exc:
            self.log.error("procurement.combined_audit_failed", error=str(exc))
            # Fallback: naive match for features
            supplier_features = [f.lower() for f in supplier_profile.key_features] if supplier_profile else []
            missing_features = [feat for feat in request.required_features if feat.lower() not in supplier_features]

        # ── 2. Price comparison ──────────────────────────────────────────────

        market_avg = market.market_average_price
        price_delta_pct: float = 0.0
        price_vs_market: Literal["below", "at", "above"] = "at"

        if market_avg and market_avg > 0:
            price_delta_pct = ((request.proposed_price - market_avg) / market_avg) * 100
            if price_delta_pct > 2.0:
                price_vs_market = "above"
            elif price_delta_pct < -2.0:
                price_vs_market = "below"
            else:
                price_vs_market = "at"

        # ── 3. Deterministic decision logic ──────────────────────────────────
        decision: Literal["approved", "rejected", "pending_review"]

        if request.proposed_price > request.budget_ceiling:
            decision = "rejected"
        elif len(missing_features) >= 3:
            decision = "rejected"
        elif price_delta_pct > 20.0:
            decision = "pending_review"
        elif 1 <= len(missing_features) <= 2:
            decision = "pending_review"
        else:
            decision = "approved"

        # Add urgency override flag for critical pending reviews
        urgency_override = (
            request.urgency == "critical" and decision == "pending_review"
        )

        self.log.info(
            "procurement.decision",
            request_id=request.request_id,
            decision=decision,
            price_delta_pct=round(price_delta_pct, 2),
            missing_features_count=len(missing_features),
            urgency_override=urgency_override,
        )

        # If combined call didn't produce a recommendation, use deterministic fallback
        if not recommendation:
            recommendation = self._fallback_recommendation(
                decision, price_delta_pct, missing_features, request
            )

        # ── 5. Build ERP payload ─────────────────────────────────────────────
        erp_payload: dict = {
            "request_id": request.request_id,
            "requester": request.requester,
            "supplier_name": request.supplier_name,
            "proposed_price": request.proposed_price,
            "decision": decision,
            "price_delta_pct": round(price_delta_pct, 2),
            "missing_features": missing_features,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if urgency_override:
            erp_payload["urgency_override_recommended"] = True

        result = ProcurementDecision(
            request_id=request.request_id,
            decision=decision,
            price_vs_market=price_vs_market,
            price_delta_pct=round(price_delta_pct, 2),
            missing_features=missing_features,
            recommendation=recommendation,
            erp_payload=erp_payload,
            decided_at=datetime.now(timezone.utc),
        )

        self.log_complete(request.request_id)
        return result

    @staticmethod
    def _fallback_recommendation(
        decision: str,
        price_delta_pct: float,
        missing_features: list[str],
        request: ProcurementRequest,
    ) -> str:
        """Deterministic fallback when Gemini call fails."""
        if decision == "approved":
            return (
                f"Approve: {request.supplier_name} meets all requirements "
                f"and is priced {abs(price_delta_pct):.1f}% "
                f"{'above' if price_delta_pct > 0 else 'below'} market average."
            )
        elif decision == "rejected":
            if request.proposed_price > request.budget_ceiling:
                over = request.proposed_price - request.budget_ceiling
                return f"Reject: Proposed price exceeds budget ceiling by ${over:.2f}."
            return (
                f"Reject: {len(missing_features)} required feature(s) absent: "
                f"{', '.join(missing_features[:3])}."
            )
        else:
            return (
                f"Send for review: Price is {price_delta_pct:.1f}% above market "
                f"and/or {len(missing_features)} feature(s) missing."
            )
