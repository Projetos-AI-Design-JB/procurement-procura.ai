# PLAN.md — Milestone 1, Phases 1–3

## Foundation: Project Scaffold · Data Contracts · Gemini Client + Base Agent

> **GSD Gate:** `/gsd-plan-phase` | Status: Awaiting approval | Date: 2026-05-03

---

## Phase 1 — Project Scaffold & Python Environment

### Objective

A runnable Python project. Nothing executes yet, but the structure, CLI, and logging exist.

### Plan 1.1 — Python Project Structure

**Files to create:**

```
projeto-sales-agents/
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

**`requirements.txt`:**

```
pydantic>=2.0.0
httpx>=0.27.0
beautifulsoup4>=4.12.0
typer>=0.12.0
structlog>=24.0.0
python-dotenv>=1.0.0
pytest>=8.0.0
pytest-asyncio>=0.23.0
```

**`.env.example`:**

```
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash
GEMINI_API_BASE=https://generativelanguage.googleapis.com/v1beta
```

**`.gitignore` additions:**

```
.env
output/
__pycache__/
*.pyc
.pytest_cache/
```

---

### Plan 1.2 — CLI Entrypoint (`main.py`)

```python
# main.py
import typer
import asyncio
from pathlib import Path
from core.logger import get_logger

app = typer.Typer(name="sales-agents", help="Multi-agent procurement intelligence pipeline")
log = get_logger()

@app.command()
def run(
    request: Path = typer.Option(..., "--request", help="Path to ProcurementRequest JSON file"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate input without executing pipeline")
):
    """Execute the full procurement intelligence pipeline."""
    log.info("pipeline.start", request_file=str(request), dry_run=dry_run)

    if not request.exists():
        typer.echo(f"Error: request file not found: {request}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Pipeline started. Request: {request}")
    # Orchestrator call wired in Phase 7

if __name__ == "__main__":
    app()
```

**Verification:** `python main.py --help` prints help; `python main.py run --request nonexistent.json` exits with code 1.

---

### Plan 1.3 — Structured Logger (`core/logger.py`)

```python
# core/logger.py
import structlog
import logging

def configure_logging(level: str = "INFO") -> None:
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
    )

def get_logger(agent: str = "orchestrator") -> structlog.BoundLogger:
    configure_logging()
    return structlog.get_logger().bind(agent=agent)
```

**Log output format:**

```json
{"agent": "orchestrator", "event": "pipeline.start", "request_file": "sample.json", "level": "info", "timestamp": "2026-05-03T22:18:00Z"}
```

---

### Phase 1 Verification Checklist

- [ ] `python main.py --help` shows CLI help without errors
- [ ] `python main.py run --request missing.json` exits code 1 with error message
- [ ] `python main.py run --request sample.json` logs `pipeline.start` event as JSON to stdout
- [ ] `requirements.txt` installs cleanly via `pip install -r requirements.txt`

---

## Phase 2 — Pydantic Data Contracts

### Objective

All inter-agent schemas defined, tested, and locked before any agent code is written. Schemas are the contract — agents implement to them.

### Plan 2.1 — Research Chain Schemas (`models/research.py`)

```python
# models/research.py
from __future__ import annotations
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, field_validator

class ResearchRequest(BaseModel):
    target_companies: list[str] = Field(min_length=1)
    product_category: str
    procurement_request_id: str
    search_keywords: list[str]
    max_sources_per_company: int = Field(default=5, ge=1, le=20)

class CompetitorProfile(BaseModel):
    company_name: str
    website_url: str
    price_range: tuple[float, float] | None = None
    key_features: list[str] = []
    review_score: float | None = Field(default=None, ge=0.0, le=5.0)
    review_count: int | None = Field(default=None, ge=0)
    seo_traffic_estimate: int | None = None
    data_confidence: Literal["high", "medium", "low"]
    scraping_errors: list[str] = []

    @field_validator("price_range")
    @classmethod
    def validate_price_range(cls, v):
        if v is not None and v[0] > v[1]:
            raise ValueError("price_range[0] must be <= price_range[1]")
        return v

class MarketResearchOutput(BaseModel):
    request_id: str
    timestamp: datetime
    profiles: list[CompetitorProfile] = Field(min_length=0)
    market_average_price: float | None = None
    data_completeness_score: float = Field(ge=0.0, le=1.0)

class JudgeVerdict(BaseModel):
    passed: bool
    reason: str
    retry_researcher: bool
    failed_rules: list[str] = []

class ValidatedResearchOutput(BaseModel):
    original: MarketResearchOutput
    verdict: JudgeVerdict
    validated_at: datetime
```

---

### Plan 2.2 — Procurement Chain Schemas (`models/procurement.py`)

```python
# models/procurement.py
from __future__ import annotations
from datetime import datetime
from typing import Literal, Any
from pydantic import BaseModel, Field

class ProcurementRequest(BaseModel):
    request_id: str
    requester: str
    supplier_name: str
    proposed_price: float = Field(gt=0)
    required_features: list[str] = Field(min_length=1)
    budget_ceiling: float = Field(gt=0)
    urgency: Literal["low", "medium", "high", "critical"]

class ProcurementDecision(BaseModel):
    request_id: str
    decision: Literal["approved", "rejected", "pending_review"]
    price_vs_market: Literal["below", "at", "above"]
    price_delta_pct: float
    missing_features: list[str] = []
    recommendation: str
    erp_payload: dict[str, Any]
    decided_at: datetime
```

---

### Plan 2.3 — Final Report Schema (`models/report.py`)

```python
# models/report.py
from __future__ import annotations
from datetime import datetime
from typing import Literal, Any
from pydantic import BaseModel
from models.research import CompetitorProfile
from models.procurement import ProcurementDecision

class CompetitorEntry(BaseModel):
    company_name: str
    price_range: tuple[float, float] | None = None
    key_features: list[str] = []
    review_score: float | None = None
    data_confidence: Literal["high", "medium", "low"]

class CompetitionMatrix(BaseModel):
    category: str
    market_average_price: float | None = None
    entries: list[CompetitorEntry]

class FinalReport(BaseModel):
    report_id: str
    request_id: str
    generated_at: datetime
    procurement_decision: ProcurementDecision
    competition_matrix: CompetitionMatrix
    executive_summary: str
    recommended_action: str
    data_quality_notes: list[str] = []
    pipeline_metadata: dict[str, Any] = {}
```

---

### Plan 2.4 — Schema Tests (`tests/test_models.py`)

```python
# tests/test_models.py
import pytest
from datetime import datetime, timezone
from pydantic import ValidationError
from models.research import ResearchRequest, MarketResearchOutput, CompetitorProfile
from models.procurement import ProcurementRequest, ProcurementDecision
from models.report import FinalReport, CompetitionMatrix

def test_research_request_valid():
    req = ResearchRequest(
        target_companies=["Acme Corp"],
        product_category="cloud storage",
        procurement_request_id="req-001",
        search_keywords=["S3", "object storage"]
    )
    assert req.max_sources_per_company == 5

def test_competitor_profile_invalid_price_range():
    with pytest.raises(ValidationError):
        CompetitorProfile(
            company_name="Bad Corp",
            website_url="https://example.com",
            price_range=(500.0, 100.0),  # invalid: min > max
            data_confidence="high"
        )

def test_market_research_completeness_bounds():
    with pytest.raises(ValidationError):
        MarketResearchOutput(
            request_id="req-001",
            timestamp=datetime.now(timezone.utc),
            profiles=[],
            data_completeness_score=1.5  # invalid: > 1.0
        )

def test_procurement_request_zero_price():
    with pytest.raises(ValidationError):
        ProcurementRequest(
            request_id="req-001",
            requester="Julia",
            supplier_name="TechCorp",
            proposed_price=0,  # invalid: must be > 0
            required_features=["feature_a"],
            budget_ceiling=10000,
            urgency="low"
        )
```

---

### Phase 2 Verification Checklist

- [ ] `pytest tests/test_models.py -v` — all tests pass
- [ ] Invalid `price_range` raises `ValidationError`
- [ ] `data_completeness_score > 1.0` raises `ValidationError`
- [ ] `proposed_price = 0` raises `ValidationError`

---

## Phase 3 — Gemini REST Client & Base Agent

### Objective

The shared infrastructure all agents build on. No business logic yet — just the Gemini REST wrapper, the abstract base, and the JSON extraction utility.

### Plan 3.1 — Gemini REST Client (`core/gemini_client.py`)

```python
# core/gemini_client.py
import os
import httpx
from typing import Any
from dotenv import load_dotenv
from core.logger import get_logger

load_dotenv()
log = get_logger("gemini_client")

GEMINI_API_BASE = os.getenv("GEMINI_API_BASE", "https://generativelanguage.googleapis.com/v1beta")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-latest")

class GeminiClient:
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise EnvironmentError("GEMINI_API_KEY is not set in environment variables")
        self.base_url = GEMINI_API_BASE
        self.model = GEMINI_MODEL

    async def generate(self, system_prompt: str, user_message: str) -> str:
        url = f"{self.base_url}/models/{self.model}:generateContent?key={self.api_key}"
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"parts": [{"text": user_message}]}],
            "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"}
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            log.info("gemini.request", model=self.model)
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            log.info("gemini.response", status=response.status_code)
            return data["candidates"][0]["content"]["parts"][0]["text"]
```

---

### Plan 3.2 — BaseAgent ABC (`agents/base.py`)

```python
# agents/base.py
from abc import ABC, abstractmethod
from typing import Any
from core.gemini_client import GeminiClient
from core.logger import get_logger

class BaseAgent(ABC):
    agent_name: str = "base"

    def __init__(self, client: GeminiClient):
        self.client = client
        self.log = get_logger(self.agent_name)

    @abstractmethod
    async def run(self, input_data: Any) -> Any:
        """Execute the agent's core task."""
        ...

    def log_start(self, request_id: str) -> None:
        self.log.info("agent.start", request_id=request_id)

    def log_complete(self, request_id: str) -> None:
        self.log.info("agent.complete", request_id=request_id)

    def log_error(self, request_id: str, error: str) -> None:
        self.log.error("agent.error", request_id=request_id, error=error)
```

---

### Plan 3.3 — JSON Extraction Utility (`core/utils.py`)

```python
# core/utils.py
import json
from typing import Any

def extract_json(text: str) -> dict[str, Any]:
    """
    Strip AI markdown/chat wrapper and extract the first valid JSON object.
    Finds the outermost { ... } block and parses it.
    """
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError(f"No JSON object found in AI response. Response: {text[:200]}")
    json_str = text[start:end]
    return json.loads(json_str)


class PipelineError(Exception):
    """Raised when the pipeline exhausts retries or encounters unrecoverable errors."""

    def __init__(self, message: str, request_id: str, stage: str, details: dict = None):
        super().__init__(message)
        self.request_id = request_id
        self.stage = stage
        self.details = details or {}

    def to_log_dict(self) -> dict:
        return {
            "error": str(self),
            "request_id": self.request_id,
            "stage": self.stage,
            "details": self.details
        }
```

---

### Phase 3 Verification Checklist

- [ ] `GeminiClient()` raises `EnvironmentError` when `GEMINI_API_KEY` is not set
- [ ] `pytest tests/test_gemini_client.py` with mocked `httpx` passes
- [ ] `extract_json('Some text {"key": "value"} more text')` returns `{"key": "value"}`
- [ ] `extract_json('no json here')` raises `ValueError`
- [ ] `BaseAgent` cannot be instantiated directly (abstract method enforcement)

---

## Summary

| Phase | Deliverables | Est. Complexity |
|-------|-------------|-----------------|
| 1 | Scaffold, CLI, Logger | Low |
| 2 | 5 Pydantic schemas + tests | Medium |
| 3 | Gemini client, BaseAgent, utils | Medium |

**Total new files:** ~12 Python files + 4 test files + config files

**Next after approval:** Execute Phase 1 → 2 → 3 sequentially, then plan Phases 4–5 (@researcher + @judge).

---
*Awaiting user approval to begin execution.*
