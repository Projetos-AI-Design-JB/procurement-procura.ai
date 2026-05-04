# tests/test_gemini_client.py
"""
Phase 3 verification: GeminiClient and core utility tests.

Uses httpx mock (respx or unittest.mock) to avoid live API calls.
"""

from __future__ import annotations

import json
import os
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from core.utils import PipelineError, extract_json


# ---------------------------------------------------------------------------
# extract_json tests (no I/O needed)
# ---------------------------------------------------------------------------

class TestExtractJson:
    def test_bare_json(self):
        result = extract_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_json_with_surrounding_text(self):
        result = extract_json('Here is the result: {"score": 0.95} done.')
        assert result == {"score": 0.95}

    def test_markdown_fenced_json(self):
        text = '```json\n{"passed": true, "reason": "OK"}\n```'
        result = extract_json(text)
        assert result["passed"] is True

    def test_nested_json(self):
        data = {"profiles": [{"name": "Acme", "score": 4.2}]}
        text = f"Output: {json.dumps(data)}"
        result = extract_json(text)
        assert result["profiles"][0]["name"] == "Acme"

    def test_no_json_raises_value_error(self):
        with pytest.raises(ValueError, match="No JSON object or list found"):
            extract_json("This response has no JSON at all.")

    def test_empty_string_raises_value_error(self):
        with pytest.raises(ValueError):
            extract_json("")

    def test_invalid_json_raises_decode_error(self):
        with pytest.raises(json.JSONDecodeError):
            extract_json("{invalid json}")


# ---------------------------------------------------------------------------
# PipelineError tests
# ---------------------------------------------------------------------------

class TestPipelineError:
    def test_basic_attributes(self):
        err = PipelineError(
            message="Judge retry budget exhausted",
            request_id="req-001",
            stage="judge",
            details={"attempts": 3, "last_rule_failed": "completeness_below_threshold"},
        )
        assert err.request_id == "req-001"
        assert err.stage == "judge"
        assert err.details["attempts"] == 3

    def test_to_log_dict(self):
        err = PipelineError("Exhausted", "req-002", "researcher")
        log_dict = err.to_log_dict()
        assert log_dict["error"] == "Exhausted"
        assert log_dict["request_id"] == "req-002"
        assert log_dict["stage"] == "researcher"
        assert log_dict["details"] == {}

    def test_is_exception(self):
        err = PipelineError("Test error", "req-003", "judge")
        with pytest.raises(PipelineError):
            raise err

    def test_default_empty_details(self):
        err = PipelineError("msg", "req-004", "synthesizer")
        assert err.details == {}


# ---------------------------------------------------------------------------
# GeminiClient tests (mocked — no live API calls)
# ---------------------------------------------------------------------------

class TestGeminiClient:
    def test_raises_without_api_key(self):
        """GeminiClient must raise EnvironmentError if GEMINI_API_KEY is unset."""
        with patch.dict(os.environ, {}, clear=True), \
             patch("dotenv.load_dotenv"), \
             patch("os.getenv", return_value=""):
            from importlib import reload
            import core.gemini_client as gc_module
            reload(gc_module)
            with pytest.raises(EnvironmentError, match="GEMINI_API_KEY"):
                gc_module.GeminiClient()

    def test_initializes_with_api_key(self):
        """GeminiClient initializes correctly when GEMINI_API_KEY is set."""
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key-abc123"}):
            from importlib import reload
            import core.gemini_client as gc_module
            reload(gc_module)
            client = gc_module.GeminiClient()
            assert client.api_key == "test-key-abc123"
            assert "aiplatform.googleapis.com" in client.base_url

    @pytest.mark.asyncio
    async def test_generate_returns_text(self):
        """generate() extracts text from the first candidate's first part."""
        mock_response_body = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": '{"result": "ok"}'}]
                    }
                }
            ]
        }

        with patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"}):
            from importlib import reload
            import core.gemini_client as gc_module
            import httpx
            reload(gc_module)

            client = gc_module.GeminiClient()

            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200
            mock_response.json.return_value = mock_response_body
            mock_response.raise_for_status = MagicMock()

            with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
                mock_post.return_value = mock_response
                result = await client.generate("system prompt", "user message")

            assert result == '{"result": "ok"}'

    @pytest.mark.asyncio
    async def test_generate_raises_on_http_error(self):
        """generate() propagates httpx.HTTPStatusError on non-2xx responses or PipelineError on exhausted retries."""
        import httpx
        from core.utils import PipelineError

        with patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"}):
            from importlib import reload
            import core.gemini_client as gc_module
            reload(gc_module)

            client = gc_module.GeminiClient()

            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 429
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Rate limit", request=MagicMock(), response=mock_response
            )

            with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, \
                 patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                mock_post.return_value = mock_response
                with pytest.raises(PipelineError, match="temporarily overloaded or rate-limited"):
                    await client.generate("system", "user")


# ---------------------------------------------------------------------------
# BaseAgent abstract enforcement
# ---------------------------------------------------------------------------

class TestBaseAgent:
    def test_cannot_instantiate_directly(self):
        """BaseAgent cannot be instantiated without implementing run()."""
        from agents.base import BaseAgent
        from core.gemini_client import GeminiClient

        with pytest.raises(TypeError):
            # Abstract class — must raise TypeError
            BaseAgent(client=MagicMock(spec=GeminiClient))  # type: ignore

    def test_concrete_subclass_works(self):
        """A concrete subclass with run() implemented can be instantiated."""
        from agents.base import BaseAgent

        class ConcreteAgent(BaseAgent):
            agent_name = "test_agent"

            async def run(self, input_data):
                return {"status": "ok"}

        agent = ConcreteAgent(client=MagicMock())
        assert agent.agent_name == "test_agent"
