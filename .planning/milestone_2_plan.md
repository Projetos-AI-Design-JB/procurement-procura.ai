# Implementation Plan: Milestone 2 — Production Scaling & Persistence

## Goal
Transform the local CLI tool into a persistent, multi-tenant capable system with real-world search capabilities.

---

## Phase 8 — Supabase Persistence
**Objective:** Replace local `output/` dependency with a cloud database.

- [ ] **Schema Migration:** Create `requests` and `reports` tables in Supabase with RLS enabled.
- [ ] **Database Client:** Implement `core/database.py` using `supabase-py`.
- [ ] **Integration:** Update `Orchestrator` to persist initial requests and final `FinalReport` JSON.

## Phase 9 — Real-World Search (Tavily Integration)
**Objective:** Move beyond knowing the supplier URL upfront.

- [ ] **Search Utility:** Implement `core/search.py` using Tavily API to find competitor URLs and pricing pages dynamically.
- [ ] **Researcher Upgrade:** Update `@researcher` to use Search + Scraping instead of just Scraping.

## Phase 10 — Monitoring Dashboard (FastAPI)
**Objective:** Provide a UI for procurement officers to review reports.

- [ ] **API Layer:** Create `api/main.py` with FastAPI to serve reports from Supabase.
- [ ] **Frontend:** Simple Next.js or Streamlit dashboard to visualize the `CompetitionMatrix`.

---

## Verification Criteria
1. `python main.py run` saves record to Supabase.
2. Researcher finds competitors without explicit URLs in the request.
3. Dashboard displays the latest report with one-click approval.
