# tests/test_database.py
"""
Tests for Supabase DatabaseClient persistence.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest
from core.database import DatabaseClient

class TestDatabaseClient:
    def test_init_without_env_vars(self):
        """Client should be unavailable if env vars are missing."""
        with patch.dict("os.environ", {}, clear=True):
            db = DatabaseClient()
            assert not db.is_available

    def test_init_with_env_vars(self):
        """Client should attempt to create a supabase client if vars exist."""
        with patch.dict("os.environ", {"SUPABASE_URL": "https://test.supabase.co", "SUPABASE_KEY": "test-key"}):
            with patch("core.database.create_client") as mock_create:
                db = DatabaseClient()
                assert db.is_available
                mock_create.assert_called_once_with("https://test.supabase.co", "test-key")

    @pytest.mark.asyncio
    async def test_save_request_calls_upsert(self):
        """save_request should call upsert on the correct table."""
        mock_client = MagicMock()
        with patch.dict("os.environ", {"SUPABASE_URL": "https://test.supabase.co", "SUPABASE_KEY": "test-key"}):
            with patch("core.database.create_client", return_value=mock_client):
                db = DatabaseClient()
                test_data = {"request_id": "req-123", "requester": "Alice"}
                
                await db.save_request(test_data)
                
                mock_client.table.assert_called_with("procurement_requests")
                mock_client.table().upsert.assert_called_with(test_data)

    @pytest.mark.asyncio
    async def test_save_report_calls_upsert(self):
        """save_report should call upsert on the correct table."""
        mock_client = MagicMock()
        with patch.dict("os.environ", {"SUPABASE_URL": "https://test.supabase.co", "SUPABASE_KEY": "test-key"}):
            with patch("core.database.create_client", return_value=mock_client):
                db = DatabaseClient()
                test_data = {"report_id": "rpt-123", "request_id": "req-123"}
                
                await db.save_report(test_data)
                
                mock_client.table.assert_called_with("procurement_reports")
                mock_client.table().upsert.assert_called_with(test_data)

    @pytest.mark.asyncio
    async def test_update_status_calls_update(self):
        """update_request_status should call update with filter."""
        mock_client = MagicMock()
        with patch.dict("os.environ", {"SUPABASE_URL": "https://test.supabase.co", "SUPABASE_KEY": "test-key"}):
            with patch("core.database.create_client", return_value=mock_client):
                db = DatabaseClient()
                
                await db.update_request_status("req-123", "decided")
                
                mock_client.table.assert_called_with("procurement_requests")
                mock_client.table().update.assert_called_with({"status": "decided"})
                mock_client.table().update().eq.assert_called_with("request_id", "req-123")
