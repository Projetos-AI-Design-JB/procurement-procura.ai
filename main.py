# main.py
"""CLI entrypoint for the Sales Agents procurement intelligence pipeline."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import typer

from core.logger import get_logger

app = typer.Typer(
    name="sales-agents",
    help="Multi-agent procurement intelligence pipeline.",
    add_completion=False,
)
log = get_logger("orchestrator")


@app.command()
def run(
    request: Path = typer.Option(
        ...,
        "--request",
        "-r",
        help="Path to ProcurementRequest JSON file.",
        show_default=False,
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Validate the request file without executing the pipeline.",
    ),
) -> None:
    """
    Execute the full procurement intelligence pipeline.

    Steps: @researcher → @judge (retry loop) → @procurement_analyst → @synthesizer
    """
    log.info("pipeline.start", request_file=str(request), dry_run=dry_run)

    if not request.exists():
        log.error("pipeline.error", event="request_file_not_found", path=str(request))
        typer.echo(f"[ERROR] Request file not found: {request}", err=True)
        raise typer.Exit(code=1)

    if not request.suffix == ".json":
        log.error("pipeline.error", event="invalid_file_type", path=str(request))
        typer.echo(f"[ERROR] Request file must be a .json file, got: {request.suffix}", err=True)
        raise typer.Exit(code=1)

    if dry_run:
        typer.echo(f"✅ Dry run: request file is valid → {request}")
        log.info("pipeline.dry_run_complete", request_file=str(request))
        return

    typer.echo(f"[START] Pipeline started. Processing: {request.name}")

    try:
        import asyncio
        from core.orchestrator import Orchestrator

        report = asyncio.run(Orchestrator().run(request))
        typer.echo(
            f"[DONE] Pipeline complete.\n"
            f"  Decision : {report.procurement_decision.decision.upper()}\n"
            f"  Report   : output/report_{report.request_id}.md\n"
            f"  JSON     : output/report_{report.request_id}.json"
        )
    except Exception as exc:
        log.error("pipeline.failed", error=str(exc))
        typer.echo(f"[ERROR] Pipeline failed: {exc}", err=True)
        raise typer.Exit(code=1)



@app.command()
def validate(
    request: Path = typer.Argument(..., help="Path to ProcurementRequest JSON file to validate."),
) -> None:
    """Validate a ProcurementRequest JSON file against the Pydantic schema."""
    import json
    from pydantic import ValidationError
    from models.procurement import ProcurementRequest

    if not request.exists():
        typer.echo(f"[ERROR] File not found: {request}", err=True)
        raise typer.Exit(code=1)

    try:
        data = json.loads(request.read_text(encoding="utf-8"))
        req = ProcurementRequest(**data)
        typer.echo(f"[OK] Valid ProcurementRequest: {req.request_id} | Supplier: {req.supplier_name}")
    except (json.JSONDecodeError, ValidationError) as exc:
        typer.echo(f"[ERROR] Validation failed:\n{exc}", err=True)
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
