# core/orchestrator.py
"""
Pipeline Orchestrator — wires all 4 agents into the sequential execution chain.

Flow:
  researcher → judge (retry loop, max 3) → procurement_analyst → synthesizer

All inter-agent data is passed as validated Pydantic objects.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from agents.judge import JudgeAgent
from agents.procurement import ProcurementAgent
from agents.researcher import ResearcherAgent
from agents.synthesizer import SynthesizerAgent
from core.database import DatabaseClient
from core.gemini_client import GeminiClient
from core.search import SearchClient
from core.logger import get_logger
from core.utils import PipelineError
from models.procurement import ProcurementRequest
from models.report import FinalReport
from models.research import ResearchRequest, ValidatedResearchOutput

log = get_logger("orchestrator")

_MAX_RESEARCHER_RETRIES = 3


class Orchestrator:
    """
    Sequential pipeline controller.

    Instantiates all agents and runs them in order,
    passing typed Pydantic objects between each stage.

    Usage:
        report = await Orchestrator().run(Path("sample_request.json"))
    """

    def __init__(self, output_dir: Path = Path("output")) -> None:
        self._client = GeminiClient()
        self._db = DatabaseClient()
        self._search = SearchClient()
        self._researcher = ResearcherAgent(client=self._client, search=self._search)
        self._judge = JudgeAgent(client=self._client)
        self._procurement = ProcurementAgent(client=self._client)
        self._synthesizer = SynthesizerAgent(client=self._client, output_dir=output_dir)

    # ── Stage 1-2: Researcher → Judge retry loop ─────────────────────────────

    async def run_research(self, request: ResearchRequest) -> ValidatedResearchOutput:
        """
        Execute the researcher → judge retry loop.

        Args:
            request: Validated ResearchRequest.

        Returns:
            ValidatedResearchOutput with verdict.passed=True.

        Raises:
            PipelineError: After _MAX_RESEARCHER_RETRIES failed judge verdicts.
        """
        request_id = request.procurement_request_id
        log.info("orchestrator.research_start", request_id=request_id)

        last_research = None
        last_validated = None

        for attempt in range(1, _MAX_RESEARCHER_RETRIES + 1):
            log.info(
                "orchestrator.researcher_attempt",
                request_id=request_id,
                attempt=attempt,
                max=_MAX_RESEARCHER_RETRIES,
            )

            last_research = await self._researcher.run(request)
            last_validated = self._judge.evaluate(last_research, attempt=attempt)

            if last_validated.verdict.passed:
                log.info(
                    "orchestrator.research_approved",
                    request_id=request_id,
                    attempt=attempt,
                )
                return last_validated

            log.warning(
                "orchestrator.research_rejected",
                request_id=request_id,
                attempt=attempt,
                failed_rules=last_validated.verdict.failed_rules,
                retry=last_validated.verdict.retry_researcher,
            )

            if not last_validated.verdict.retry_researcher:
                break

        raise PipelineError(
            message=(
                f"@researcher output rejected by @judge after "
                f"{_MAX_RESEARCHER_RETRIES} attempts."
            ),
            request_id=request_id,
            stage="judge.retry_exhausted",
            details={
                "max_retries": _MAX_RESEARCHER_RETRIES,
                "last_failed_rules": last_validated.verdict.failed_rules if last_validated else [],
                "last_completeness": last_research.data_completeness_score if last_research else 0.0,
                "last_profile_count": len(last_research.profiles) if last_research else 0,
            },
        )

    # ── Full pipeline ─────────────────────────────────────────────────────────

    async def run(self, request_file: Path) -> FinalReport:
        """
        Execute the complete 4-agent pipeline from a ProcurementRequest JSON file.

        Stages:
          1. Load & validate ProcurementRequest from JSON
          2. @researcher → @judge (retry loop)
          3. @procurement_analyst
          4. @synthesizer → writes output/*.md and output/*.json

        Args:
            request_file: Path to a ProcurementRequest JSON file.

        Returns:
            FinalReport — also written to output/ directory.

        Raises:
            PipelineError: On unrecoverable agent failures.
            pydantic.ValidationError: If the request file is malformed.
        """
        t_start = time.monotonic()
        log.info("orchestrator.pipeline_start", request_file=str(request_file))

        try:
            # ── 1. Load procurement request ───────────────────────────────────────
            raw = json.loads(request_file.read_text(encoding="utf-8"))
            procurement_req = ProcurementRequest(**raw)
            
            # Persist request to database
            await self._db.save_request({**procurement_req.model_dump(), "status": "researching"})
            
            log.info(
                "orchestrator.request_loaded",
                request_id=procurement_req.request_id,
                supplier=procurement_req.supplier_name,
            )

            # ── 2. Build research request from procurement request ────────────────
            research_req = ResearchRequest(
                target_companies=[procurement_req.supplier_name],
                product_category=procurement_req.product_category,
                procurement_request_id=procurement_req.request_id,
                search_keywords=procurement_req.required_features,
            )

            # ── 3. Researcher → Judge ─────────────────────────────────────────────
            researcher_attempts = 0
            validated_research = None
            last_error: PipelineError | None = None

            for attempt in range(1, _MAX_RESEARCHER_RETRIES + 1):
                researcher_attempts = attempt
                log.info(
                    "orchestrator.researcher_attempt",
                    request_id=procurement_req.request_id,
                    attempt=attempt,
                )
                research_output = await self._researcher.run(research_req)
                validated = self._judge.evaluate(research_output, attempt=attempt)

                if validated.verdict.passed:
                    validated_research = validated
                    break

                log.warning(
                    "orchestrator.research_rejected",
                    request_id=procurement_req.request_id,
                    attempt=attempt,
                    failed_rules=validated.verdict.failed_rules,
                )

                if not validated.verdict.retry_researcher:
                    last_error = PipelineError(
                        message=f"@judge rejected research after {attempt} attempts.",
                        request_id=procurement_req.request_id,
                        stage="judge.retry_exhausted",
                        details={"failed_rules": validated.verdict.failed_rules},
                    )
                    break

            if validated_research is None:
                raise last_error or PipelineError(
                    message="Research validation failed.",
                    request_id=procurement_req.request_id,
                    stage="judge",
                )

            log.info(
                "orchestrator.stage_complete",
                stage="researcher+judge",
                request_id=procurement_req.request_id,
                profiles=len(validated_research.original.profiles),
                attempts=researcher_attempts,
            )

            # ── 4. Procurement triage ─────────────────────────────────────────────
            log.info("orchestrator.procurement_start", request_id=procurement_req.request_id)
            procurement_decision = await self._procurement.run(
                request=procurement_req,
                research=validated_research,
            )
            log.info(
                "orchestrator.stage_complete",
                stage="procurement_analyst",
                request_id=procurement_req.request_id,
                decision=procurement_decision.decision,
            )

            # ── 5. Synthesizer → write reports ────────────────────────────────────
            t_elapsed_ms = int((time.monotonic() - t_start) * 1000)
            pipeline_metadata = {
                "researcher_retries": researcher_attempts - 1,
                "execution_time_ms": t_elapsed_ms,
                "data_completeness_score": validated_research.original.data_completeness_score,
                "judge_rules_checked": 4,
            }

            log.info("orchestrator.synthesizer_start", request_id=procurement_req.request_id)
            report = await self._synthesizer.run(
                request=procurement_req,
                research=validated_research,
                decision=procurement_decision,
                pipeline_metadata=pipeline_metadata,
            )

            # Persist report and update request status
            await self._db.save_report(report.model_dump())
            await self._db.update_request_status(procurement_req.request_id, "decided")

            log.info(
                "orchestrator.pipeline_complete",
                request_id=procurement_req.request_id,
                report_id=report.report_id,
                decision=procurement_decision.decision,
                execution_time_ms=t_elapsed_ms,
            )

            return report

        except Exception as exc:
            # Update status in DB if request was already loaded
            try:
                if 'procurement_req' in locals():
                    await self._db.update_request_status(procurement_req.request_id, "error")
            except:
                pass
            raise
