# Sales Agents — Multi-Agent Procurement Intelligence System

A Python-based autonomous AI multi-agent system for competitive intelligence and procurement triage.

## Architecture

```
Orchestrator
  └─ @researcher  → MarketResearchOutput (Pydantic)
  └─ @judge       → ValidatedResearchOutput (blocks + retries)
  └─ @procurement_analyst → ProcurementDecision
  └─ @synthesizer → FinalReport (.md + .json)
```

## Setup

```bash
# 1. Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY

# 4. Run the pipeline
python main.py run --request sample_request.json
```

## Project Structure

```
projeto-sales-agents/
├── agents/          # Agent implementations
├── core/            # Gemini client, orchestrator, utilities
├── models/          # Pydantic schemas (inter-agent contracts)
├── tests/           # pytest test suite
├── output/          # Generated reports (gitignored)
├── .agents/skills/  # SKILL.md per agent
└── .planning/       # GSD planning documents
```

## Agent Skills

Each agent is documented in `.agents/skills/<name>/SKILL.md`:

- `researcher` — Market & Competitor Analyst
- `judge` — QA / Reviewer (retry gate)
- `procurement-analyst` — Procurement Triage
- `synthesizer` — Report Compiler

## Running Tests

```bash
pytest tests/ -v
```

## Stack

- **Python 3.10+** with strong typing
- **Pydantic v2** for all inter-agent data contracts
- **Gemini 2.5 Flash** via REST API (no SDK)
- **structlog** for JSON-structured logging
- **typer** for CLI interface
- **httpx** for async HTTP / scraping
