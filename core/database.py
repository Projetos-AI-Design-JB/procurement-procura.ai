# core/database.py
"""
Supabase Database Client — handles persistence for requests and reports.
Milestone 2: Production Scaling & Persistence.
"""

from __future__ import annotations

import os
from typing import Any

from postgrest import APIResponse
from supabase import create_client, Client
from core.logger import get_logger
from core.utils import PipelineError

log = get_logger("database")

class DatabaseClient:
    """
    Supabase client wrapper for procurement data.
    
    Usage:
        db = DatabaseClient()
        await db.save_request(procurement_request)
    """

    def __init__(self) -> None:
        self.url = os.getenv("SUPABASE_URL", "")
        self.key = os.getenv("SUPABASE_KEY", "")
        
        if not self.url or not self.key:
            log.warning("database.not_configured", message="Supabase URL or Key missing. Persistence disabled.")
            self._client = None
        else:
            try:
                self._client: Client = create_client(self.url, self.key)
                log.info("database.connected")
            except Exception as exc:
                log.error("database.connection_failed", error=str(exc))
                self._client = None

    @property
    def is_available(self) -> bool:
        return self._client is not None

    async def save_request(self, request_data: dict[str, Any]) -> None:
        """Upsert a procurement request into public.procurement_requests."""
        if not self.is_available:
            return

        try:
            # Flatten or map data if necessary, but schema matches models/procurement.py
            response: APIResponse = self._client.table("procurement_requests").upsert(request_data).execute()
            log.info("database.request_saved", request_id=request_data.get("request_id"))
        except Exception as exc:
            log.error("database.save_request_failed", error=str(exc))
            # We don't raise here to avoid breaking the pipeline if DB is down
            # but in a real production app we might want to retry or queue.

    async def save_report(self, report_data: dict[str, Any]) -> None:
        """Upsert a final report into public.procurement_reports."""
        if not self.is_available:
            return

        try:
            response: APIResponse = self._client.table("procurement_reports").upsert(report_data).execute()
            log.info("database.report_saved", report_id=report_data.get("report_id"))
        except Exception as exc:
            log.error("database.save_report_failed", error=str(exc))

    async def update_request_status(self, request_id: str, status: str) -> None:
        """Update the status of a request (pending, researching, decided, error)."""
        if not self.is_available:
            # Fallback for local dev: create an .error file to notify the UI
            if status == "error":
                try:
                    from pathlib import Path
                    # Write to the current directory where api/main.py expects it
                    error_file = Path(f"{request_id}.error")
                    error_file.write_text(f"Pipeline failed: Agent rejected the output.", encoding="utf-8")
                except:
                    pass
            return

        try:
            self._client.table("procurement_requests")\
                .update({"status": status})\
                .eq("request_id", request_id)\
                .execute()
            log.info("database.status_updated", request_id=request_id, status=status)
        except Exception as exc:
            log.error("database.status_update_failed", error=str(exc))
