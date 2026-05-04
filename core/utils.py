# core/utils.py
"""
Shared utilities for the agent pipeline.

Includes:
  - extract_json(): strips AI markdown wrappers and parses JSON
  - PipelineError: structured exception for unrecoverable pipeline failures
"""

from __future__ import annotations

import json
from typing import Any


def extract_json(text: str) -> Any:
    """
    Extract the first valid JSON object or list from an AI response string.

    Handles common AI output patterns:
      - Bare JSON:         '{"key": "value"}'
      - Markdown fenced:   '```json\\n{...}\\n```'
      - Mixed text:        'Here is the data: {...} end'

    Strategy: find the outermost { ... } or [ ... ] block by scanning for
    the first '{' or '[' and the last '}' or ']', then parse that substring.

    Args:
        text: Raw string returned by the Gemini API.

    Returns:
        Parsed dict or list.

    Raises:
        ValueError: If no JSON object or list is found in the text.
        json.JSONDecodeError: If the extracted substring is invalid JSON.
    """
    # Find start of object or array
    start_curly = text.find("{")
    start_square = text.find("[")
    
    if start_curly == -1 and start_square == -1:
        raise ValueError(f"No JSON object or list found. Preview: {text[:100]!r}")
    
    # Determine which one starts first
    if start_curly != -1 and (start_square == -1 or start_curly < start_square):
        start = start_curly
        end = text.rfind("}") + 1
    else:
        start = start_square
        end = text.rfind("]") + 1

    if start == -1 or end <= start:
        raise ValueError(f"Incomplete JSON structure. Preview: {text[:100]!r}")

    json_str = text[start:end]
    return json.loads(json_str)


class PipelineError(Exception):
    """
    Raised when the pipeline encounters an unrecoverable error.

    Common causes:
      - @judge retry budget exhausted (max 3 attempts)
      - Gemini API failure after retries
      - Output file write failure

    Attributes:
        request_id: The procurement request ID being processed.
        stage:      The pipeline stage where the error occurred.
        details:    Additional structured context for logging.
    """

    def __init__(
        self,
        message: str,
        request_id: str,
        stage: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.request_id = request_id
        self.stage = stage
        self.details = details or {}

    def to_log_dict(self) -> dict[str, Any]:
        """Return a structured dict for JSON logging."""
        return {
            "error": str(self),
            "request_id": self.request_id,
            "stage": self.stage,
            "details": self.details,
        }
