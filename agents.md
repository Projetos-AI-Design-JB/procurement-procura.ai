# PROCURA.AI Agents Database

This document records the architecture, behavior, and recent optimizations for the multi-agent procurement pipeline.

## 🤖 Agent Profiles

### 1. @researcher (Market Analyst)
- **Role:** Scrapes market data (pricing, features, reviews) using Tavily Search + Scraper.
- **Optimization (May 2026):**
  - Implemented **Parallel Execution** using `asyncio.gather`.
  - Concurrently searches for Competitors, Target Company Pricing, and Feature Specs.
  - Reduced latency from ~90s down to **< 30s**.
  - Capped at 7 unique high-quality sources to prevent context window bloat.

### 2. @judge (Quality Assurance)
- **Role:** Deterministic business rule engine. Validates researcher output before synthesis.
- **Rules Checked:**
  - `completeness_below_threshold`: Ensures Gemini found enough data.
  - `insufficient_profiles`: Minimum 1 profile required.
  - `no_market_price_data`: Ensures pricing comparison is possible.
- **Optimization (May 2026):**
  - Lowered `_MIN_COMPLETENESS_SCORE` to **0.15** to handle niche product discovery.
  - Retry logic: Max 3 attempts before raising a `PipelineError`.

### 3. @procurement_analyst (Decision Maker)
- **Role:** Logic-based agent that compares the user's `Proposed Price` against the `Market Average`.
- **Logic:**
  - **APPROVED:** Price is <= Market Average OR within 10% tolerance.
  - **REJECTED:** Price is significantly above market without justification.
  - **FLAGGED:** Missing features or major negative reviews found.

### 4. @synthesizer (Executive Summary)
- **Role:** Compiles the final Markdown report and structured JSON.
- **Recent Fixes:**
  - Added `supplier_name` mapping to ensure UI dashboard displays correctly.
  - Implemented `ensure_ascii=False` for proper UTF-8 character rendering in reports.

## 🛠️ System Reliability (Offline Mode)

When Supabase persistence is unavailable, the following fallbacks are active:
- **Request Storage:** Saved as `request_req-dyn-xxx.json` in the root directory.
- **Error Tracking:** If an agent fails, a `{request_id}.error` file is created containing the failure reason.
- **UI Refresh:** The frontend uses timestamp-based cache busting (`?_t=timestamp`) to ensure the dashboard always reflects the latest filesystem state.

---
*Status: All Agents Online & Optimized.*
