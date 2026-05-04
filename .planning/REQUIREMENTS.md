# REQUIREMENTS.md

> Source: SPEC.md v1.0.0 | Status: Active

## Functional Requirements

### FR-01 — Pipeline Execution
The orchestrator must execute the full agent chain (researcher → judge → procurement_analyst → synthesizer) without human intervention given a valid `ProcurementRequest` JSON file.

**Acceptance:** `python main.py run --request sample.json` completes and writes `output/report_<id>.md` and `output/report_<id>.json`.

### FR-02 — Pydantic Contract Enforcement
All inter-agent data transfers must be validated against Pydantic v2 models. Raw `dict` passing between agents is prohibited.

**Acceptance:** Passing malformed data raises `pydantic.ValidationError`; pipeline catches it and logs structured error.

### FR-03 — Judge Retry Loop
The `@judge` agent must block invalid researcher output and trigger `@researcher` re-run. Max 3 retries before raising `PipelineError`.

**Acceptance:** Injecting `data_completeness_score = 0.3` causes 3 retries then a structured `PipelineError` log.

### FR-04 — Graceful Scraping Degradation
When a supplier site blocks scraping, the system must log the error per supplier, mark `data_confidence = "low"`, and continue processing remaining suppliers.

**Acceptance:** Blocking one URL in tests still produces a partial `MarketResearchOutput` with `scraping_errors` populated.

### FR-05 — Dual-Format Final Report
The `@synthesizer` must produce both `report_<id>.md` (Markdown) and `report_<id>.json` (validated by `FinalReport` Pydantic model).

**Acceptance:** `pydantic.TypeAdapter(FinalReport).validate_json(report_json)` passes without error.

### FR-06 — SKILL.md Documentation
Each of the 4 agents must have a `.agents/skills/<name>/SKILL.md` documenting: purpose, input schema, output schema, system prompt template, and operational constraints.

**Acceptance:** All 4 SKILL.md files exist and contain all required sections.

---

## Non-Functional Requirements

### NFR-01 — Python 3.10+ Compatibility
All code must run on Python 3.10 and above. Use `match/case`, `X | Y` union types where appropriate.

### NFR-02 — Environment Variable Security
`GEMINI_API_KEY` must never be hardcoded. Always loaded via `os.getenv()` from `.env`. `.env` must be in `.gitignore`.

### NFR-03 — Structured Logging
All agent activity must emit JSON-structured logs via `structlog` with fields: `agent`, `event`, `request_id`, `timestamp`, `level`.

### NFR-04 — Gemini REST Only (No SDK)
Gemini calls must use `httpx` against `generativelanguage.googleapis.com/v1beta` directly. Do not import `google.generativeai` or `@google/generative-ai`.

---

## Out of Scope (v1)

- Web UI / dashboard
- Real-time streaming scraping
- Database persistence (filesystem artifacts only)
- Authentication / multi-user support
- Deployment / containerization
