---
name: researcher
description: Market & Competitor Analyst Agent — scrapes target company websites, calls Gemini 2.5 Flash to extract structured competitive intelligence, and returns a validated MarketResearchOutput.
---

# @researcher — Market & Competitor Analyst

## Purpose

Autonomously researches a list of target companies, collecting:
- Price ranges (min/max in USD)
- Key product/service features (up to 8)
- Public review scores and volume
- Estimated monthly SEO traffic
- Raw scraping errors (graceful degradation — never halts the pipeline)

Output is validated by `@judge` before entering the procurement stage.

---

## Execution Flow

```
ResearchRequest
  → core/scraper.py: fetch_pages() [async, 1s inter-domain delay]
      ↓ ScrapingResult[] (success or error, never raises)
  → Build JSON context payload
  → GeminiClient.generate(system_prompt, context_json)
      ↓ raw text response
  → core/utils.py: extract_json()
      ↓ parsed dict
  → Pydantic: MarketResearchOutput(**parsed)
      ↓ validated output
  → @judge
```

---

## Input Schema

```python
class ResearchRequest(BaseModel):
    target_companies: list[str]         # min 1 company
    product_category: str
    procurement_request_id: str         # links to ProcurementRequest
    search_keywords: list[str]          # used in Gemini prompt context
    max_sources_per_company: int = 5    # max 10 (Pydantic enforced)
```

---

## Output Schema

```python
class CompetitorProfile(BaseModel):
    company_name: str
    website_url: str
    price_range: tuple[float, float] | None    # (min, max) USD; min < max enforced
    key_features: list[str]                    # max 8 items
    review_score: float | None                 # 0.0–5.0 enforced
    review_count: int | None                   # >= 0 enforced
    seo_traffic_estimate: int | None
    data_confidence: Literal["high", "medium", "low"]
    scraping_errors: list[str] = []

class MarketResearchOutput(BaseModel):
    request_id: str
    timestamp: datetime
    profiles: list[CompetitorProfile]
    market_average_price: float | None
    data_completeness_score: float      # 0.0–1.0; must be >= 0.70 to pass @judge
```

---

## Gemini System Prompt (abbreviated)

```
You are a Senior Market Intelligence Analyst. Extract structured competitive
intelligence from raw web page content provided below.

CRITICAL RULES:
- Return ONLY valid JSON. No markdown, no explanation.
- If a field cannot be found, set it to null. NEVER fabricate numbers.
- Calculate data_completeness_score = non-null field count / expected fields.
```

---

## Graceful Degradation Rules

| Scenario | Behaviour |
|----------|-----------|
| URL returns 4xx/5xx | `ScrapingResult.success=False`, error logged, pipeline continues |
| Timeout (>20s) | Same as above — `error="Timeout fetching: <url>"` |
| Domain rate limit | 1-second delay between same-domain requests via `fetch_pages()` |
| Gemini call fails | `PipelineError` raised with `stage="researcher"` — orchestrator catches |
| Output parse fails | `PipelineError` raised with `stage="researcher.parse"` + raw preview |

---

## Operational Constraints

1. **No fabrication:** `null` > guess. Gemini is explicitly instructed.
2. **Content cap:** Page text truncated at 8,000 chars before being sent to Gemini.
3. **Rate limiting:** `fetch_pages()` enforces 1s delay per domain.
4. **Output validation:** `MarketResearchOutput` is Pydantic-validated before returning.
5. **Retry aware:** Orchestrator calls `run()` up to 3 times if `@judge` rejects.

---

## Usage

```python
from agents.researcher import ResearcherAgent
from core.gemini_client import GeminiClient
from models.research import ResearchRequest

agent = ResearcherAgent(client=GeminiClient())
output = await agent.run(ResearchRequest(
    target_companies=["CloudStorage Pro"],
    product_category="cloud storage",
    procurement_request_id="req-001",
    search_keywords=["S3-compatible", "enterprise storage"],
))
# output: MarketResearchOutput
```

---

## Files

| File | Role |
|------|------|
| `agents/researcher.py` | Agent implementation |
| `core/scraper.py` | `fetch_page()` / `fetch_pages()` — async HTTP with graceful error capture |
| `models/research.py` | `ResearchRequest`, `CompetitorProfile`, `MarketResearchOutput` schemas |
| `tests/test_scraper.py` | 9 scraper tests (all mocked) |
