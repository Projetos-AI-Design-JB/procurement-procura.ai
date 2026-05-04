# core/scraper.py
"""
Async web scraper with Graceful degradation.

Rules:
  - A blocked or failed URL returns a ScrapingResult with error set — never raises.
  - Adds a 1-second delay between requests to the same domain.
  - Returns raw text content for the AI to extract structured data from.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from core.logger import get_logger

log = get_logger("scraper")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_TIMEOUT = httpx.Timeout(30.0, connect=10.0, read=20.0)


@dataclass
class ScrapingResult:
    """Result from a single page fetch attempt."""

    url: str
    success: bool
    content: str = ""         # Cleaned text content (empty on failure)
    status_code: int | None = None
    error: str = ""           # Error message (empty on success)


async def fetch_page(url: str) -> ScrapingResult:
    """
    Fetch a single URL and return cleaned text content.

    Never raises — all errors are captured in ScrapingResult.error.

    Args:
        url: The page URL to fetch.

    Returns:
        ScrapingResult with success=True and content on success,
        or success=False and error on failure.
    """
    log.info("scraper.fetch", url=url)

    try:
        async with httpx.AsyncClient(
            headers=_HEADERS,
            timeout=_TIMEOUT,
            follow_redirects=True,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        # Remove script/style noise
        for tag in soup(["script", "style", "nav", "footer", "iframe"]):
            tag.decompose()

        text = soup.get_text(separator=" ", strip=True)
        # Collapse whitespace
        text = " ".join(text.split())

        log.info("scraper.success", url=url, status_code=response.status_code, chars=len(text))
        return ScrapingResult(
            url=url,
            success=True,
            content=text[:8000],  # cap at 8k chars for prompt safety
            status_code=response.status_code,
        )

    except httpx.HTTPStatusError as exc:
        error = f"HTTP {exc.response.status_code}: {url}"
        log.warning("scraper.http_error", url=url, status_code=exc.response.status_code)
        return ScrapingResult(
            url=url,
            success=False,
            status_code=exc.response.status_code,
            error=error,
        )

    except httpx.TimeoutException:
        error = f"Timeout fetching: {url}"
        log.warning("scraper.timeout", url=url)
        return ScrapingResult(url=url, success=False, error=error)

    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        log.warning("scraper.error", url=url, error=error)
        return ScrapingResult(url=url, success=False, error=error)


async def fetch_pages(urls: list[str], delay_seconds: float = 1.0) -> list[ScrapingResult]:
    """
    Fetch multiple pages in parallel across different domains.
    Respects a delay between same-domain requests.

    Args:
        urls:          List of URLs to fetch.
        delay_seconds: Delay between requests to the same domain.

    Returns:
        List of ScrapingResult objects (one per URL, in order).
    """
    # Group URLs by domain to respect rate limits
    domain_to_urls: dict[str, list[str]] = {}
    url_to_index = {url: i for i, url in enumerate(urls)}
    
    for url in urls:
        domain = urlparse(url).netloc
        if domain not in domain_to_urls:
            domain_to_urls[domain] = []
        domain_to_urls[domain].append(url)

    async def fetch_domain_group(domain_urls: list[str]) -> list[ScrapingResult]:
        domain_results = []
        for i, url in enumerate(domain_urls):
            if i > 0:
                await asyncio.sleep(delay_seconds)
            res = await fetch_page(url)
            domain_results.append(res)
        return domain_results

    # Run domain groups in parallel
    tasks = [fetch_domain_group(group) for group in domain_to_urls.values()]
    all_grouped_results = await asyncio.gather(*tasks)
    
    # Flatten and sort back to original order
    flat_results = [res for group in all_grouped_results for res in group]
    results_in_order = [None] * len(urls)
    for res in flat_results:
        results_in_order[url_to_index[res.url]] = res
        
    return results_in_order  # type: ignore
