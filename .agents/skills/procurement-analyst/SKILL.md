---
name: procurement-analyst
description: Procurement Triage Agent — applies deterministic decision rules (price delta, feature gaps, budget) and calls Gemini only to generate the human-readable recommendation text.
---

# @procurement_analyst — Procurement Triage Agent

## Purpose

Cross-references a `ProcurementRequest` with `ValidatedResearchOutput` and produces a typed `ProcurementDecision` with:
- A deterministic triage decision (`approved` / `rejected` / `pending_review`)
- Price delta vs market average
- Feature gap analysis (required vs supplier's offered features)
- ERP-ready payload
- Human-readable recommendation (Gemini-generated, with deterministic fallback)

---

## Execution Flow

```
ProcurementRequest + ValidatedResearchOutput
  → Locate supplier profile in research output
  → Feature gap analysis (string comparison)
  → Price delta calculation vs market_average_price
  → Apply decision rules (pure Python, deterministic)
  → GeminiClient.generate() → recommendation text
      ↓ (if Gemini fails → fallback recommendation built from rule outputs)
  → Build ERP payload dict
  → Return ProcurementDecision
```

---

## Input Schemas

```python
class ProcurementRequest(BaseModel):
    request_id: str
    requester: str
    supplier_name: str
    proposed_price: float               # must be > 0
    required_features: list[str]        # min 1 feature
    budget_ceiling: float               # must be >= proposed_price (not enforced by schema — rule logic)
    urgency: Literal["low", "medium", "high", "critical"]
```

---

## Output Schema

```python
class ProcurementDecision(BaseModel):
    request_id: str
    decision: Literal["approved", "rejected", "pending_review"]
    price_vs_market: Literal["below", "at", "above"]
    price_delta_pct: float              # positive = above market, negative = below
    missing_features: list[str]
    recommendation: str                 # Gemini-generated or fallback
    erp_payload: dict                   # ERP-ready dict for downstream integration
    decided_at: datetime
```

---

## Decision Logic (Deterministic — Evaluated in Order)

| Priority | Condition | Decision |
|----------|-----------|----------|
| 1 (highest) | `proposed_price > budget_ceiling` | `rejected` |
| 2 | `len(missing_features) >= 3` | `rejected` |
| 3 | `price_delta_pct > 20.0` | `pending_review` |
| 4 | `1 <= len(missing_features) <= 2` | `pending_review` |
| 5 (default) | None of the above | `approved` |

**Urgency Override:** If `urgency == "critical"` and `decision == "pending_review"`, the ERP payload includes `urgency_override_recommended: True`.

---

## Price Delta Formula

```python
price_delta_pct = ((proposed_price - market_avg) / market_avg) * 100

# Rounding: 2 decimal places
# price_vs_market:
#   delta > +2%  → "above"
#   delta < -2%  → "below"
#   else         → "at"
```

If `market_average_price is None` → `price_delta_pct = 0.0`, `price_vs_market = "at"`.

---

## Gemini Call (Recommendation Text Only)

Gemini receives a JSON context with the decision, price delta, and missing features.  
It returns:

```json
{ "recommendation": "one-sentence actionable recommendation" }
```

**Fallback:** If Gemini fails, `_fallback_recommendation()` builds a deterministic string from the rule outputs. The pipeline never halts due to Gemini unavailability.

---

## ERP Payload Structure

```json
{
  "request_id": "req-001",
  "requester": "Julia",
  "supplier_name": "CloudStorage Pro",
  "proposed_price": 280.0,
  "decision": "approved",
  "price_delta_pct": -6.67,
  "missing_features": [],
  "timestamp": "2026-05-04T03:15:00Z",
  "urgency_override_recommended": true   // only on critical+pending
}
```

---

## Usage

```python
from agents.procurement import ProcurementAgent

agent = ProcurementAgent(client=GeminiClient())
decision = await agent.run(
    request=procurement_request,
    research=validated_research_output,
)
# decision.decision → "approved" | "rejected" | "pending_review"
# decision.erp_payload → dict ready for ERP system
```

---

## Files

| File | Role |
|------|------|
| `agents/procurement.py` | Agent implementation + fallback recommendation |
| `models/procurement.py` | `ProcurementRequest`, `ProcurementDecision` schemas |
| `tests/test_procurement.py` | 13 tests — all decision paths, price delta, ERP, fallback |
