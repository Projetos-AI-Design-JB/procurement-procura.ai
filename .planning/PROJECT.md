# PROJECT.md — Sistema Multiagentes: Análise de Concorrentes & Triagem de Compras

## What This Is

A Python-based autonomous multi-agent system that delivers two interlinked intelligence services:

1. **Competitive Intelligence** — Automated market monitoring of competitors, pricing, features, SEO positioning, and supplier reviews.
2. **Procurement Triage** — Cross-referencing internal purchase requests against live market data to validate scope, compare prices, and generate structured purchase orders.

The system is orchestrated via a GSD-compliant pipeline where specialized agents communicate through typed Pydantic contracts, ensuring structured JSON hand-offs between each stage.

---

## Context

- **Stack:** Python 3.10+ · Pydantic v2 · Google Gemini API (REST, Gemini 2.5 Flash minimum) · Shell/filesystem tools
- **Orchestration runtime:** Gemini CLI with `@agent` delegation syntax (`@researcher`, `@procurement_analyst`, `@judge`, `@synthesizer`)
- **Agent skill storage:** `.agents/skills/<agent-name>/SKILL.md` per agent
- **Methodology:** Spec-Driven Development (SDD) + GSD cycle (Plan → Execute → Verify)
- **Isolation:** Sequential context flow — research completes before triage begins; no context bleed between agents

---

## Agents (Subagents)

| ID | Agent Name | Role |
|----|-----------|------|
| A | `@researcher` | Market Analyst — scrapes prices, features, SEO, reviews |
| B | `@procurement_analyst` | Procurement Triage — validates requests against market data |
| C | `@judge` | QA / Reviewer — blocks on hallucinations or incomplete data, forces re-run |
| D | `@synthesizer` | Report compiler — produces Markdown/JSON intelligence brief |

---

## Requirements

### Validated
*(None yet — ship to validate)*

### Active

- [ ] Orchestrator delegates task to `@researcher` without human intervention
- [ ] `@researcher` output passes Pydantic validation before entering triage stage
- [ ] `@procurement_analyst` compares request against researcher data and returns a typed decision object
- [ ] `@judge` rejects incomplete supplier data and forces `@researcher` re-run (max 3 retries)
- [ ] `@synthesizer` generates a final report in both Markdown and structured JSON
- [ ] System fails gracefully with descriptive logs when a supplier site blocks scraping
- [ ] Each agent's behavior, system prompt, and constraints documented in `.agents/skills/<name>/SKILL.md`
- [ ] All inter-agent messages validated with Pydantic models (no raw dicts in the chain)

### Out of Scope

- UI/frontend dashboard — output is CLI + file artifacts only (v1)
- Real-time streaming scraping — batch-mode per run
- Database persistence — filesystem JSON artifacts for v1

---

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Pydantic v2 for all inter-agent contracts | Prevents silent type errors in the multi-agent chain; enforces schema at each boundary | Adopted |
| Sequential (not parallel) agent execution | Avoids context collision; judge can block and retry researcher before triage begins | Adopted |
| SKILL.md per agent in `.agents/skills/` | Follows GSD agent-skill convention; versionable, auto-discoverable by orchestrator | Adopted |
| Gemini 2.5 Flash via REST (no SDK) | Avoids SDK versioning conflicts; aligns with project AGENTS.md rule | Adopted |
| Graceful degradation with retry cap | Judge forces max 3 researcher re-runs; exits with structured error log on exhaustion | Adopted |

---

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition:**
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions

**After each milestone:**
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?

---
*Last updated: 2026-05-03 — Initialization (gsd-new-project)*
