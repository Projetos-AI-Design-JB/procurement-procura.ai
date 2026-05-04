# core/gemini_client.py
"""
Gemini REST client — calls generativelanguage.googleapis.com via httpx.

Rules (per AGENTS.md):
  - MINIMUM model: Gemini 2.5 Flash. Never use 1.5 or below.
  - NO SDK imports (google.generativeai, @google/generative-ai).
  - GEMINI_API_KEY loaded strictly from environment via os.getenv().
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
from dotenv import load_dotenv

from core.logger import get_logger

try:
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request as GoogleAuthRequest
    HAS_GOOGLE_AUTH = True
except ImportError:
    HAS_GOOGLE_AUTH = False

load_dotenv()

log = get_logger("gemini_client")

_DEFAULT_BASE = "https://us-south1-aiplatform.googleapis.com/v1/projects/projeto-jb-api-gcp/locations/us-south1/publishers/google"
_DEFAULT_MODEL = "gemini-2.5-flash"


class GeminiClient:
    """
    Async Gemini REST client. Supports AI Studio and Vertex AI endpoints.

    Usage:
        client = GeminiClient()
        response_text = await client.generate(
            system_prompt="You are a data analyst...",
            user_message="Analyze this supplier data: ...",
        )
    """

    def __init__(self) -> None:
        self.base_url: str = os.getenv("GEMINI_API_BASE", _DEFAULT_BASE).rstrip("/")
        self.model: str = os.getenv("GEMINI_MODEL", _DEFAULT_MODEL)
        
        # Vertex AI uses a different model endpoint format than AI Studio
        self.is_vertex = "aiplatform.googleapis.com" in self.base_url
        self._credentials = None
        
        if self.is_vertex:
            if not HAS_GOOGLE_AUTH:
                raise EnvironmentError("google-auth is required for Vertex AI. Run `pip install google-auth`.")
            
            cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            if not cred_path or not os.path.exists(cred_path):
                raise EnvironmentError(
                    "GOOGLE_APPLICATION_CREDENTIALS is not set or file doesn't exist. "
                    "Required for Vertex AI authentication."
                )
            
            self._credentials = service_account.Credentials.from_service_account_file(
                cred_path, scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
        else:
            self.api_key: str = os.getenv("GEMINI_API_KEY", "")
            if not self.api_key:
                raise EnvironmentError(
                    "GEMINI_API_KEY is not set. "
                    "Copy .env.example → .env and add your API key."
                )

    def _build_url(self) -> str:
        if self.is_vertex:
            return f"{self.base_url}/models/{self.model}:generateContent"
        return f"{self.base_url}/models/{self.model}:generateContent?key={self.api_key}"

    def _get_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.is_vertex and self._credentials:
            # Refresh token if needed
            if not self._credentials.valid:
                self._credentials.refresh(GoogleAuthRequest())
            headers["Authorization"] = f"Bearer {self._credentials.token}"
        return headers

    def _build_payload(self, system_prompt: str, user_message: str) -> dict[str, Any]:
        return {
            "system_instruction": {
                "parts": [{"text": system_prompt}]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_message}],
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
            },
        }

    async def generate(self, system_prompt: str, user_message: str) -> str:
        """
        Send a generation request to Gemini and return the raw text response.
        Implements automatic exponential backoff for 429 and 503 errors.

        Args:
            system_prompt: The agent's system instruction.
            user_message:  The user-facing input (data + task).

        Returns:
            Raw text from the first candidate's first part.

        Raises:
            httpx.HTTPStatusError: On non-2xx responses.
            KeyError: If the response structure is unexpected.
        """
        url = self._build_url()
        payload = self._build_payload(system_prompt, user_message)
        headers = self._get_headers()

        log.info("gemini.request", model=self.model, is_vertex=self.is_vertex)

        max_retries = 3
        base_delay = 2.0

        async with httpx.AsyncClient(timeout=120.0) as client:
            for attempt in range(max_retries + 1):
                response = await client.post(url, headers=headers, json=payload)
                
                if response.status_code == 200:
                    break
                    
                log.error("gemini.error_details", status_code=response.status_code, attempt=attempt+1, body=response.text)
                
                # Check for temporary server issues
                if response.status_code in (429, 503) and attempt < max_retries:
                    delay = base_delay * (2 ** attempt)
                    log.warning("gemini.retry_backoff", status_code=response.status_code, delay=delay, attempt=attempt+1)
                    await asyncio.sleep(delay)
                    continue
                    
                # If we exhausted retries or got a non-retryable error
                if response.status_code in (429, 503):
                    from core.utils import PipelineError
                    raise PipelineError(
                        message=f"[GEMINI'S FAULT] The AI model is temporarily overloaded or rate-limited (HTTP {response.status_code}) after {max_retries} retries.",
                        request_id="gemini-system",
                        stage="gemini_client"
                    )
                response.raise_for_status()

        data: dict[str, Any] = response.json()
        log.info("gemini.response", status_code=response.status_code, model=self.model)

        text: str = data["candidates"][0]["content"]["parts"][0]["text"]
        return text
