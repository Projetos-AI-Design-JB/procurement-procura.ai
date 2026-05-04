# agents/synthesizer.py
"""
@synthesizer — Report Compiler Agent

Compiles all pipeline data into a dual-format final report:
  - output/report_<request_id>.md   (Markdown for stakeholders)
  - output/report_<request_id>.json (validated JSON for integrations)

The JSON is validated against FinalReport before writing to disk.
If Gemini fails to generate the executive summary, a deterministic
fallback is used so the report is always produced.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from agents.base import BaseAgent
from core.gemini_client import GeminiClient
from core.utils import PipelineError, extract_json
from models.procurement import ProcurementDecision, ProcurementRequest
from models.report import CompetitionMatrix, CompetitorEntry, FinalReport
from models.research import ValidatedResearchOutput

_OUTPUT_DIR = Path(__file__).parent.parent / "output"

_SYSTEM_PROMPT = """\
You are a Chief Intelligence Officer writing a procurement intelligence brief.

Given the pipeline data below, produce:
1. executive_summary (3-5 sentences): Market context, key finding, and decision rationale.
   Write for a non-technical procurement director. No jargon.
2. recommended_action (1 sentence): A clear, direct directive.
   Example: "Approve the purchase order for CloudStorage Pro at $280/month."

Return ONLY valid JSON:
{
  "executive_summary": "...",
  "recommended_action": "..."
}
"""


class SynthesizerAgent(BaseAgent):
    """
    Report Compiler Agent.

    Assembles all upstream data into a FinalReport, writes both
    Markdown and JSON artifacts to the output/ directory.
    """

    agent_name = "synthesizer"

    def __init__(self, client: GeminiClient, output_dir: Path = _OUTPUT_DIR) -> None:
        super().__init__(client)
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def run(
        self,
        request: ProcurementRequest,
        research: ValidatedResearchOutput,
        decision: ProcurementDecision,
        pipeline_metadata: dict | None = None,
    ) -> FinalReport:
        """
        Compile and write the final intelligence report.

        Args:
            request:           Original procurement request.
            research:          Validated market research output.
            decision:          Procurement triage decision.
            pipeline_metadata: Audit data (retries, timing, etc.).

        Returns:
            FinalReport Pydantic object (also written to output/).

        Raises:
            PipelineError: If output files cannot be written.
        """
        self.log_start(request.request_id)
        metadata = pipeline_metadata or {}

        # ── 1. Build competition matrix ──────────────────────────────────────
        entries = [
            CompetitorEntry(
                company_name=p.company_name,
                price_range=p.price_range,
                key_features=p.key_features,
                feature_evidence=p.feature_evidence,
                review_score=p.review_score,
                data_confidence=p.data_confidence,
            )
            for p in research.original.profiles
        ]
        matrix = CompetitionMatrix(
            category=request.required_features[0] if request.required_features else "N/A",
            market_average_price=research.original.market_average_price,
            entries=entries,
        )

        # ── 2. Data quality notes ────────────────────────────────────────────
        quality_notes: list[str] = []
        for profile in research.original.profiles:
            if profile.data_confidence == "low":
                quality_notes.append(
                    f"[LOW CONFIDENCE] {profile.company_name}: data may be estimated."
                )
            for err in profile.scraping_errors:
                quality_notes.append(f"[SCRAPING ERROR] {profile.company_name}: {err}")

        # ── 3. Generate narrative via Gemini ─────────────────────────────────
        context = {
            "supplier_name": request.supplier_name,
            "product_category": matrix.category,
            "decision": decision.decision,
            "price_delta_pct": decision.price_delta_pct,
            "price_vs_market": decision.price_vs_market,
            "missing_features": decision.missing_features,
            "recommendation": decision.recommendation,
            "market_average_price": research.original.market_average_price,
            "proposed_price": request.proposed_price,
            "profile_count": len(research.original.profiles),
            "data_completeness": research.original.data_completeness_score,
        }

        try:
            raw = await self.client.generate(
                _SYSTEM_PROMPT,
                json.dumps(context, ensure_ascii=False),
            )
            parsed = extract_json(raw)
            executive_summary = parsed.get("executive_summary", "")
            recommended_action = parsed.get("recommended_action", "")
        except Exception as exc:
            self.log.warning("synthesizer.gemini_fallback", error=str(exc))
            executive_summary = self._fallback_summary(decision, request, research)
            recommended_action = decision.recommendation

        # ── 4. Assemble FinalReport ──────────────────────────────────────────
        report = FinalReport(
            report_id=f"rpt-{uuid.uuid4().hex[:8]}",
            request_id=request.request_id,
            supplier_name=request.supplier_name,
            generated_at=datetime.now(timezone.utc),
            procurement_decision=decision,
            competition_matrix=matrix,
            executive_summary=executive_summary,
            recommended_action=recommended_action,
            data_quality_notes=quality_notes,
            pipeline_metadata=metadata,
        )

        # ── 5. Write output files ────────────────────────────────────────────
        try:
            json_path = self.output_dir / f"report_{request.request_id}.json"
            md_path = self.output_dir / f"report_{request.request_id}.md"

            json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
            md_path.write_text(self._render_markdown(report, request), encoding="utf-8")

            self.log.info(
                "synthesizer.output_written",
                request_id=request.request_id,
                json=str(json_path),
                markdown=str(md_path),
            )
        except OSError as exc:
            raise PipelineError(
                message=f"Failed to write output files: {exc}",
                request_id=request.request_id,
                stage="synthesizer.write",
            ) from exc

        self.log_complete(request.request_id)
        return report

    # ── Markdown rendering ────────────────────────────────────────────────────

    def _render_markdown(self, report: FinalReport, request: ProcurementRequest) -> str:
        d = report.procurement_decision
        m = report.competition_matrix

        decision_icon = {"approved": "[APPROVED]", "rejected": "[REJECTED]", "pending_review": "[PENDING REVIEW]"}
        icon = decision_icon.get(d.decision, d.decision.upper())

        price_line = (
            f"${request.proposed_price:,.2f} vs market avg "
            f"${m.market_average_price:,.2f} ({d.price_delta_pct:+.1f}%)"
            if m.market_average_price
            else f"${request.proposed_price:,.2f} (no market average available)"
        )

        matrix_rows = "\n".join(
            f"| {e.company_name} | "
            f"{f'${e.price_range[0]:,.0f}-${e.price_range[1]:,.0f}' if e.price_range else 'N/A'} | "
            f"{e.review_score or 'N/A'} | "
            f"{e.data_confidence} |"
            for e in m.entries
        )

        evidence_list = []
        for e in m.entries:
            if e.feature_evidence:
                ev_str = f"### {e.company_name} Verification\n"
                for feat, ev in e.feature_evidence.items():
                    ev_str += f"- **{feat}**: {ev}\n"
                evidence_list.append(ev_str)
        
        evidence_section = "\n".join(evidence_list) if evidence_list else "No detailed evidence captured."

        quality_section = (
            "\n".join(f"- {note}" for note in report.data_quality_notes)
            if report.data_quality_notes
            else "- No quality issues detected."
        )

        meta = report.pipeline_metadata
        retries = meta.get("researcher_retries", 0)
        elapsed = meta.get("execution_time_ms", "N/A")

        avg_str = f"${m.market_average_price:,.2f}" if m.market_average_price else "N/A"
        return f"""# Intelligence Brief — {report.request_id}

**Report ID:** {report.report_id}  
**Generated:** {report.generated_at.strftime('%Y-%m-%d %H:%M UTC')}  
**Category:** {m.category}  
**Decision:** {icon}

---

## Executive Summary

{report.executive_summary}

---

## Procurement Decision

| Field | Value |
|-------|-------|
| Supplier | {d.erp_payload.get('supplier_name', 'N/A')} |
| Proposed Price | {price_line} |
| Price Position | {d.price_vs_market.upper()} market |
| Missing Features | {', '.join(d.missing_features) if d.missing_features else 'None'} |
| **Verdict** | **{d.decision.upper().replace('_', ' ')}** |

**Recommendation:** {d.recommendation}

---

## Competitive Intelligence Matrix

| Company | Price Range | Review Score | Confidence |
|---------|------------|--------------|------------|
{matrix_rows}

**Market Average Price:** {avg_str} | **Profiles Analyzed:** {len(m.entries)}

---

## Feature Evidence & Verification

{evidence_section}

---

## Data Quality Notes

{quality_section}

---

## Pipeline Metadata

| Metric | Value |
|--------|-------|
| Researcher retries | {retries} |
| Execution time | {elapsed} ms |
| Data completeness | {meta.get('data_completeness_score', 'N/A')} |"""

    @staticmethod
    def _fallback_summary(
        decision: ProcurementDecision,
        request: ProcurementRequest,
        research: ValidatedResearchOutput,
    ) -> str:
        profiles = len(research.original.profiles)
        avg = research.original.market_average_price
        avg_str = f"${avg:,.2f}" if avg else "unavailable"
        delta = f"{decision.price_delta_pct:+.1f}%"
        return (
            f"Market analysis covered {profiles} competitor profile(s) in the "
            f"'{request.required_features[0] if request.required_features else 'requested'}' category. "
            f"The market average price is {avg_str}. "
            f"{request.supplier_name}'s proposed price of ${request.proposed_price:,.2f} "
            f"is {delta} relative to the market average. "
            f"The procurement triage yielded a decision of '{decision.decision}' "
            f"based on price positioning and feature coverage analysis."
        )
