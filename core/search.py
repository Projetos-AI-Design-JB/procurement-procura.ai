# core/search.py
"""
Search Client — integrates with Tavily for dynamic web research.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict

from tavily import AsyncTavilyClient
from core.logger import get_logger

log = get_logger("search")

class SearchClient:
    """
    Asynchronous search client using Tavily with in-memory caching.
    """

    def __init__(self) -> None:
        self.api_key = os.getenv("TAVILY_API_KEY", "")
        self._cache: Dict[str, dict] = {}  # {query: {"results": list, "expiry": float}}
        self._cache_ttl = 3600  # 1 hour
        
        if not self.api_key:
            log.warning("search.no_api_key", message="TAVILY_API_KEY not set. Search will fail.")
            self._client = None
        else:
            self._client = AsyncTavilyClient(api_key=self.api_key)

    @property
    def is_available(self) -> bool:
        return self._client is not None

    async def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        """
        Perform a web search and return results.
        
        Returns:
            List of dicts: [{"title": str, "url": str, "content": str, "score": float}]
        """
        if not self.is_available:
            log.error("search.unavailable", query=query)
            return []

        # Check cache
        now = time.time()
        if query in self._cache:
            entry = self._cache[query]
            if entry["expiry"] > now:
                log.info("search.cache_hit", query=query)
                return entry["results"]
            else:
                del self._cache[query]

        try:
            log.info("search.request", query=query)
            # Use 'basic' depth for speed
            response = await self._client.search(
                query=query, 
                search_depth="basic", 
                max_results=max_results
            )
            results = response.get("results", [])
            
            # Store in cache
            self._cache[query] = {
                "results": results,
                "expiry": now + self._cache_ttl
            }
            
            log.info("search.success", query=query, results_count=len(results))
            return results
        except Exception as exc:
            log.error("search.failed", query=query, error=str(exc))
            return []
