# CHANGELOG.md

All notable changes to this project are documented here.  
Format: [Date] — Phase — Description

---

## [2026-05-04] — Milestone 1 Complete: Foundation & Core Pipeline

### Phase 7 — @synthesizer & End-to-End Pipeline
- `agents/synthesizer.py` — report compiler with Gemini narrative + deterministic fallback
- `core/orchestrator.py` — full 4-agent sequential wiring with timing and retry tracking
- `main.py` — CLI `run` command wired to `Orchestrator().run()`
- `tests/test_e2e.py` — 5 end-to-end tests (both output files, JSON round-trip, Markdown sections, retry exhaustion)
- **Test result:** 92/92 passed

### Phase 6 — @procurement_analyst Agent
- `agents/procurement.py` — deterministic decision engine (rejected/pending_review/approved)
- Price delta calculation vs market average (with 2% deadband)
- Feature gap analysis (string comparison against required features)
- ERP payload builder with urgency override flag
- Gemini call for recommendation text only — deterministic fallback if Gemini unavailable
- `tests/test_procurement.py` — 13 tests covering all decision paths

### Phase 5 — @judge & Retry Loop
- `agents/judge.py` — 4 deterministic business rule checkers (no Gemini)
- `core/orchestrator.py` — `researcher → judge` retry loop (max 3 attempts)
- `PipelineError` raised on retry budget exhaustion with full structured log
- `tests/test_judge.py` — 21 tests covering all rules, retry flags, orchestrator loop

### Phase 4 — @researcher Agent
- `core/scraper.py` — async scraper with graceful degradation (errors → `ScrapingResult`, never raises)
- `agents/researcher.py` — `ResearcherAgent` with Gemini-powered competitive intelligence extraction
- 1-second inter-domain delay; 8,000 char content cap
- `tests/test_scraper.py` — 9 tests (success, 403, timeout, generic error, content cap, mixed batch)

### Phase 3 — Gemini REST Client & Base Agent
- `core/gemini_client.py` — pure REST client (no SDK), httpx, Gemini 2.5 Flash
- `agents/base.py` — `BaseAgent` ABC with structured logging helpers
- `core/utils.py` — `extract_json()` + `PipelineError`
- `tests/test_gemini_client.py` — 17 tests (mocked httpx, env validation, ABC enforcement)

### Phase 2 — Pydantic Data Contracts
- `models/research.py` — 5 schemas: `ResearchRequest`, `CompetitorProfile`, `MarketResearchOutput`, `JudgeVerdict`, `ValidatedResearchOutput`
- `models/procurement.py` — 2 schemas: `ProcurementRequest`, `ProcurementDecision`
- `models/report.py` — 3 schemas: `FinalReport`, `CompetitionMatrix`, `CompetitorEntry`
- `tests/test_models.py` — 25 schema tests

### Phase 1 — Project Scaffold
- Project structure: `main.py`, `requirements.txt`, `.env.example`, `.gitignore`, `README.md`
- CLI entrypoint with `typer` (`run` + `validate` commands)
- `core/logger.py` — structlog JSON logging (agent, event, timestamp, level)

---

## Summary

| Metric | Value |
|--------|-------|
| Total phases | 7 |
| Total tests | 92 |
| Test pass rate | 100% |
| Python version | 3.14.3 |
| Key dependencies | pydantic v2, httpx, typer, structlog, beautifulsoup4, pytest-asyncio |
| AI model | Gemini 2.5 Flash (REST, no SDK) |
| Design pattern | 4-agent sequential pipeline with judge retry loop |
