---
name: judge
description: QA / Reviewer Agent — applies 4 deterministic Python business rules to MarketResearchOutput. No Gemini calls. Controls the researcher retry loop (max 3 attempts).
---

# @judge — Quality Assurance & Reviewer Agent

## Purpose

Acts as the **quality gate** between `@researcher` and `@procurement_analyst`.

Enforces 4 deterministic business rules written in Python — **no Gemini is used for rule evaluation**. Returns a `ValidatedResearchOutput` with a pass/fail verdict and retry flag.

---

## Execution Flow

```
MarketResearchOutput
  → Run 4 rule checkers (pure Python, synchronous)
  → Build JudgeVerdict (passed, failed_rules, retry_researcher)
  → Return ValidatedResearchOutput
```

If `verdict.passed=False` and `attempt < 3` → orchestrator re-runs `@researcher`.  
If `attempt == 3` and still failing → `PipelineError(stage="judge.retry_exhausted")`.

---

## Input Schema

```python
class MarketResearchOutput(BaseModel):
    request_id: str
    timestamp: datetime
    profiles: list[CompetitorProfile]
    market_average_price: float | None
    data_completeness_score: float      # 0.0–1.0
```

---

## Output Schema

```python
class JudgeVerdict(BaseModel):
    passed: bool
    reason: str                         # human-readable, actionable
    retry_researcher: bool              # True if attempt < MAX_RETRIES and failed
    failed_rules: list[str]            # empty on pass

class ValidatedResearchOutput(BaseModel):
    original: MarketResearchOutput
    verdict: JudgeVerdict
    validated_at: datetime
```

---

## Business Rules

| Rule ID | Check | Threshold | Implementation |
|---------|-------|-----------|----------------|
| `completeness_below_threshold` | `data_completeness_score` | Must be `>= 0.70` | `_check_completeness()` |
| `insufficient_profiles` | Profile count | Minimum **2** profiles | `_check_min_profiles()` |
| `too_many_low_confidence` | `data_confidence == "low"` ratio | Max **50%** of profiles | `_check_confidence_ratio()` |
| `no_market_price_data` | `market_average_price is None` AND all `price_range is None` | At least one price source | `_check_market_price()` |

All 4 rules run on every call. Multiple rules can fail simultaneously.

---

## Retry Logic

```python
# In agents/judge.py
_MAX_RETRIES = 3

verdict = JudgeVerdict(
    retry_researcher = not passed and attempt < _MAX_RETRIES
)
```

| Attempt | Failed | `retry_researcher` |
|---------|--------|--------------------|
| 1 | Yes | `True` |
| 2 | Yes | `True` |
| 3 | Yes | `False` — orchestrator raises `PipelineError` |
| Any | No (passed) | `False` |

---

## Operational Constraints

1. **Pure Python rules** — no AI inference, no Gemini call, fully deterministic.
2. **All rules run every time** — no short-circuit. Multiple failures reported together.
3. **Transparent rejection** — `reason` always includes attempt number and failed rule IDs.
4. **Strict budget** — 3 retries max; after exhaustion, the pipeline fails loudly via `PipelineError`.

---

## Usage

```python
from agents.judge import JudgeAgent

judge = JudgeAgent(client=gemini_client)  # client unused but required by BaseAgent

# Called directly (synchronous):
validated = judge.evaluate(research_output, attempt=1)
if not validated.verdict.passed:
    print(validated.verdict.failed_rules)

# Called via run() (async wrapper):
validated = await judge.run(research_output)
```

---

## Files

| File | Role |
|------|------|
| `agents/judge.py` | Rule checkers + `evaluate()` / `run()` |
| `models/research.py` | `JudgeVerdict`, `ValidatedResearchOutput` schemas |
| `tests/test_judge.py` | 21 tests — all 4 rules, retry flags, orchestrator loop |
