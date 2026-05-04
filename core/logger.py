# core/logger.py
"""Structured JSON logging via structlog. All agents use get_logger()."""

import logging
import structlog


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog with JSON rendering and ISO timestamps."""
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )


def get_logger(agent: str = "orchestrator") -> structlog.types.FilteringBoundLogger:
    """
    Return a pre-bound logger with the agent name attached.

    Example output:
        {"agent": "researcher", "event": "agent.start", "request_id": "req-001",
         "level": "info", "timestamp": "2026-05-03T22:18:00Z"}
    """
    configure_logging()
    return structlog.get_logger().bind(agent=agent)
