# agents/base.py
"""
Abstract base class for all agents in the pipeline.

Every agent (@researcher, @judge, @procurement_analyst, @synthesizer)
inherits from BaseAgent and implements the run() method.

Design decisions:
  - Injects GeminiClient at construction time (testable via mock injection)
  - Binds a structlog logger with the agent name pre-set
  - Provides log_start / log_complete / log_error helpers for consistent event names
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from core.gemini_client import GeminiClient
from core.logger import get_logger


class BaseAgent(ABC):
    """
    Abstract base for all pipeline agents.

    Subclasses must define:
      - agent_name (class attribute): used for structured logging
      - run(input_data): the agent's core execution logic

    Example:
        class ResearcherAgent(BaseAgent):
            agent_name = "researcher"

            async def run(self, input_data: ResearchRequest) -> MarketResearchOutput:
                self.log_start(input_data.procurement_request_id)
                ...
                self.log_complete(input_data.procurement_request_id)
                return output
    """

    agent_name: str = "base"

    def __init__(self, client: GeminiClient) -> None:
        self.client = client
        self.log = get_logger(self.agent_name)

    @abstractmethod
    async def run(self, input_data: Any) -> Any:
        """Execute this agent's core task and return a typed output."""
        ...

    # ------------------------------------------------------------------
    # Structured logging helpers
    # ------------------------------------------------------------------

    def log_start(self, request_id: str) -> None:
        """Log that this agent has started processing a request."""
        self.log.info("agent.start", request_id=request_id)

    def log_complete(self, request_id: str) -> None:
        """Log that this agent has successfully completed processing."""
        self.log.info("agent.complete", request_id=request_id)

    def log_error(self, request_id: str, error: str) -> None:
        """Log an error encountered during agent processing."""
        self.log.error("agent.error", request_id=request_id, error=error)

    def log_retry(self, request_id: str, attempt: int, reason: str) -> None:
        """Log a retry event (used by the judge → researcher loop)."""
        self.log.warning(
            "agent.retry",
            request_id=request_id,
            attempt=attempt,
            reason=reason,
        )
