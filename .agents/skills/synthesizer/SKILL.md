---
name: synthesizer
description: Report Compiler Agent — assembles all pipeline data into a FinalReport, generates executive narrative via Gemini, and writes both report_*.md and report_*.json to the output/ directory.
---

# @synthesizer — Report Compiler Agent

## Purpose

The final stage of the pipeline. Assembles all upstream data into a `FinalReport` Pydantic object, calls Gemini to generate the executive narrative, and writes two output files:

- `output/report_<request_id>.md` — Markdown brief for stakeholders
- `output/report_<request_id>.json` — Validated JSON for system integrations

---

## Execution Flow

```
ProcurementRequest + ValidatedResearchOutput + ProcurementDecision + pipeline_metadata
  → Build CompetitionMatrix from research profiles
  → Collect data quality notes (low confidence, scraping errors)
  → GeminiClient.generate() → executive_summary + recommended_action
      ↓ (if Gemini fails → deterministic fallback summary built from pipeline data)
  → Assemble FinalReport (Pydantic-validated)
  → Write output/report_<id>.json
  → Write output/report_<id>.md
  → Return FinalReport
```

---

## Input Schemas

```python
# All required:
request:           ProcurementRequest
research:          ValidatedResearchOutput
decision:          ProcurementDecision
pipeline_metadata: dict  # {"researcher_retries": int, "execution_time_ms": int, ...}
```

---

## Output Schema

```python
class FinalReport(BaseModel):
    report_id: str                      # "rpt-<hex8>"
    request_id: str
    generated_at: datetime
    procurement_decision: ProcurementDecision
    competition_matrix: CompetitionMatrix
    executive_summary: str              # 3-5 sentences for stakeholders
    recommended_action: str             # 1 clear directive
    data_quality_notes: list[str]       # warnings about low-confidence or scraping errors
    pipeline_metadata: dict             # audit trail
```

---

## Gemini Call (Narrative Generation Only)

Gemini receives a JSON context and returns:

```json
{
  "executive_summary": "3–5 sentence market context and decision rationale.",
  "recommended_action": "One clear directive for the procurement director."
}
```

**Fallback:** If Gemini fails, `_fallback_summary()` builds a deterministic summary from `price_delta_pct`, `market_average_price`, `supplier_name`, and `data_completeness_score`. Output is always written — never halted by Gemini unavailability.

---

## Markdown Report Structure

```markdown
# Intelligence Brief — <request_id>

**Report ID:** rpt-<hex8>
**Generated:** YYYY-MM-DD HH:MM UTC
**Category:** <product_category>
**Decision:** [APPROVED] | [REJECTED] | [PENDING REVIEW]

## Executive Summary
## Procurement Decision       ← price, supplier, missing features, verdict
## Competitive Intelligence Matrix  ← table of all CompetitorProfiles
## Data Quality Notes         ← low-confidence and scraping error warnings
## Pipeline Metadata          ← retries, execution time, completeness score
```

---

## Data Quality Notes

Automatically generated when:
- Any `CompetitorProfile.data_confidence == "low"` → `"[LOW CONFIDENCE] <company>: data may be estimated."`
- Any `CompetitorProfile.scraping_errors` non-empty → `"[SCRAPING ERROR] <company>: <error>"`

---

## CompetitionMatrix Schema

```python
class CompetitorEntry(BaseModel):
    company_name: str
    price_range: tuple[float, float] | None
    key_features: list[str]
    review_score: float | None
    data_confidence: str

class CompetitionMatrix(BaseModel):
    category: str
    market_average_price: float | None
    entries: list[CompetitorEntry]
```

---

## Operational Constraints

1. **Always writes output** — Gemini narrative failure triggers fallback, not pipeline abort.
2. **Dual format** — Both `.md` and `.json` always written together.
3. **Report ID** — `"rpt-" + uuid4().hex[:8]` — unique per run, not per request.
4. **JSON round-trip** — Written JSON passes `FinalReport.model_validate_json()` — verified in `test_e2e.py`.
5. **Output directory** — Configurable via `SynthesizerAgent(output_dir=Path(...))` — defaults to `./output/`.

---

## Usage

```python
from agents.synthesizer import SynthesizerAgent
from pathlib import Path

agent = SynthesizerAgent(client=GeminiClient(), output_dir=Path("output"))
report = await agent.run(
    request=procurement_req,
    research=validated_research,
    decision=procurement_decision,
    pipeline_metadata={"researcher_retries": 0, "execution_time_ms": 4200},
)
# report.report_id → "rpt-a1b2c3d4"
# output/report_req-001.md written
# output/report_req-001.json written
```

---

## Files

| File | Role |
|------|------|
| `agents/synthesizer.py` | Agent implementation + Markdown renderer + fallback |
| `models/report.py` | `FinalReport`, `CompetitionMatrix`, `CompetitorEntry` schemas |
| `tests/test_e2e.py` | 5 e2e tests — both files written, JSON round-trip, Markdown sections, retry exhaustion |
