# ROADMAP.md — Sales Agents Multi-Agent System

> Methodology: SDD + GSD | Granularity: Standard | Execution: Sequential

---

## Milestone 1 — Foundation & Core Infrastructure ✅
**Goal:** All infrastructure, schemas, and base classes in place. The pipeline can run end-to-end with mock/live agents.

**Status:** Completed 2026-05-04

---

## Milestone 2 — Production Scaling & Persistence ✅
**Goal:** Transform the local CLI tool into a persistent, multi-tenant capable system with real-world search capabilities.

---

### Phase 8 — Supabase Persistence
**Status:** ✅ Completed 2026-05-04  
**Goal:** Replace local `output/` dependency with a cloud database.

#### Plans
| # | Plan | Deliverable |
|---|------|-------------|
| 8.1 | Supabase Schema | `sql/schema.sql` — `requests` and `reports` tables with RLS |
| 8.2 | Database Client | `core/database.py` — implementation using `supabase-py` |
| 8.3 | Orchestrator Integration | Update `core/orchestrator.py` to persist data on start/finish |

**Verification:** `python main.py run` creates record in Supabase dashboard.

---

### Phase 9 — Real-World Search (Tavily Integration)
**Status:** ✅ Completed 2026-05-04  
**Goal:** Move beyond knowing the supplier URL upfront.

#### Plans
| # | Plan | Deliverable |
|---|------|-------------|
| 9.1 | Search Utility | `core/search.py` — Tavily API wrapper |
| 9.2 | Researcher Upgrade | Update `agents/researcher.py` to search for competitors dynamically |

**Verification:** Run pipeline without `website_url` in request → researcher finds valid sources.

---

### Phase 10 — Monitoring Dashboard (FastAPI)
**Status:** ✅ Completed 2026-05-04  
**Goal:** Provide a UI for procurement officers to review reports.

#### Plans
| # | Plan | Deliverable |
|---|------|-------------|
| 10.1 | FastAPI Layer | `api/main.py` — JSON endpoints for reports |
| 10.2 | Dashboard UI | `dashboard/` — Simple Next.js visualization of reports |

**Verification:** Open browser at `localhost:3000` → view latest matrix.

---

## Backlog (Post-v2)
- `999.3` — Real-time scraping scheduler (APScheduler)
- `999.4` — Docker containerization
- `999.5` — Slack/email notification on procurement decisions
