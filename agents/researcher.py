# agents/researcher.py
"""
@researcher — Market & Competitor Analyst Agent

Accepts a ResearchRequest, scrapes target company websites,
sends the collected data to Gemini, and returns a validated
MarketResearchOutput.

Graceful degradation: blocked/failed URLs populate
CompetitorProfile.scraping_errors and set data_confidence="low".
The pipeline continues with the remaining profiles.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from agents.base import BaseAgent
from core.gemini_client import GeminiClient
from core.scraper import fetch_pages
from core.search import SearchClient
from core.utils import PipelineError, extract_json
from models.research import (
    CompetitorProfile,
    MarketResearchOutput,
    ResearchRequest,
)

_SYSTEM_PROMPT = """\
You are a Lead Market Intelligence Researcher. Your task is to extract HIGH-PRECISION data about suppliers from the provided web content.

STRICT RULES:
1. PRICING: Extract ONLY if found in the text. DO NOT GUESS. If not found, return null for price_range. Look for "starting at", "$X per month", or price tables.
2. FEATURES: For every feature you list in 'key_features', you MUST provide evidence in 'feature_evidence' as a dictionary mapping the feature name to the evidence found (e.g. {"SAML integration": "Found on vendor pricing page: Support for SAML 2.0"}).
3. CONFIDENCE: Set data_confidence to 'low' if you are making inferences from blog posts, and 'high' only if data comes from the official company domain.
4. SYNONYMS: If the user asks for "Email integration" and you find "Outlook Sync", map it correctly but cite the original text in evidence.
5. MARKET COMPARISON: If 'competitor_intelligence' is provided, use it to extract data for at least 1-2 competitors to provide a balanced market view.

Return ONLY valid JSON for a list of CompetitorProfile objects.

For each company, extract:
- price_range: (min_price, max_price) tuple in USD, or null if not found
- key_features: list of up to 8 distinct product/service features
- feature_evidence: dictionary mapping feature names to evidence strings justifying its existence
- review_score: numeric score 0.0-5.0, or null if not found
- review_count: integer number of reviews, or null if not found
- seo_traffic_estimate: estimated monthly web visitors as integer, or null
- data_confidence: "high" (official page/verified platform), "medium" (aggregator), or "low" (estimated)

CRITICAL RULES:
- Return ONLY valid JSON. No markdown, no explanation, no extra text.
- If a field cannot be found, set it to null. NEVER fabricate numbers.
- Assign data_confidence based on content quality, not your training data.
- Calculate market_average_price as the mean of all non-null price_range midpoints.
- Calculate data_completeness_score = (non-null field count) / (total expected fields) across all profiles.
  Expected fields per profile: price_range, key_features, review_score, review_count, seo_traffic_estimate.

Output schema (strict JSON):
{
  "request_id": "string",
  "timestamp": "ISO 8601 datetime",
  "profiles": [
    {
      "company_name": "string",
      "website_url": "string",
      "price_range": [min, max] or null,
      "key_features": ["feature1", ...],
      "review_score": float or null,
      "review_count": int or null,
      "seo_traffic_estimate": int or null,
      "data_confidence": "high"|"medium"|"low",
      "scraping_errors": ["error string", ...]
    }
  ],
  "market_average_price": float or null,
  "data_completeness_score": float
}
"""


class ResearcherAgent(BaseAgent):
    """
    Market & Competitor Analyst.

    Fetches web pages for each target company, passes the raw content
    to Gemini, and returns a typed MarketResearchOutput.
    """

    agent_name = "researcher"

    def __init__(self, client: GeminiClient, search: SearchClient) -> None:
        super().__init__(client)
        self.search = search

    async def run(self, input_data: ResearchRequest) -> MarketResearchOutput:
        """
        Execute competitive research for a list of target companies.

        Args:
            input_data: Validated ResearchRequest with target_companies and keywords.

        Returns:
            MarketResearchOutput with competitor profiles and completeness score.

        Raises:
            PipelineError: If Gemini call fails or output cannot be parsed.
        """
        request_id = input_data.procurement_request_id
        self.log_start(request_id)

        # ── 1. Search for intelligence (dynamic discovery) ────────────────────
        target_companies = list(input_data.target_companies)
        competitor_context = ""
        
        async def fetch_competitor_context():
            nonlocal competitor_context
            if len(target_companies) == 1:
                comp_query = f"top 3 competitors and alternatives to {target_companies[0]} {input_data.product_category}"
                try:
                    comp_results = await self.search.search(comp_query, max_results=3)
                    for res in comp_results:
                        competitor_context += f"COMPETITOR SOURCE: {res['url']}\nCONTENT: {res['content']}\n\n"
                except:
                    pass

        async def fetch_company_context(company: str) -> dict:
            query_gen = f"{company} {input_data.product_category} pricing reviews"
            feature_hints = " ".join(input_data.search_keywords[:4])
            query_feat = f"{company} {input_data.product_category} {feature_hints} features specs"
            
            try:
                res_gen, res_feat = await asyncio.gather(
                    asyncio.wait_for(self.search.search(query_gen, max_results=4), timeout=60.0),
                    asyncio.wait_for(self.search.search(query_feat, max_results=4), timeout=60.0),
                )
            except asyncio.TimeoutError:
                self.log.warning("researcher.search_timeout", company=company)
                res_gen, res_feat = [], []
            except Exception as exc:
                self.log.error("researcher.search_error", company=company, error=str(exc))
                res_gen, res_feat = [], []
            
            # Merge unique results
            seen_urls: set[str] = set()
            search_results: list[dict] = []
            for r in res_gen + res_feat:
                if r['url'] not in seen_urls:
                    search_results.append(r)
                    seen_urls.add(r['url'])
            search_results = search_results[:7]  # cap at 7 unique sources
            
            combined_content = ""
            errors = []
            
            if not search_results:
                errors.append(f"No search results found for {company}")
            else:
                for res in search_results:
                    combined_content += f"SOURCE: {res['url']}\nTITLE: {res['title']}\nCONTENT: {res['content']}\n\n"

            self.log.info(
                "researcher.search_complete",
                request_id=request_id,
                company=company,
                sources=len(search_results),
            )

            return {
                "company_name": company,
                "website_url": search_results[0]["url"] if search_results else f"https://www.{company.lower()}.com",
                "page_content": combined_content[:10000],  # increased for better data extraction
                "scraping_errors": errors
            }

        # Run competitor context and company contexts concurrently
        tasks = [fetch_company_context(c) for c in target_companies]
        
        # Await competitor fetch alongside companies
        comp_task = asyncio.create_task(fetch_competitor_context())
        company_contexts = await asyncio.gather(*tasks)
        await comp_task




        user_message = json.dumps(
            {
                "request_id": request_id,
                "product_category": input_data.product_category,
                "search_keywords": input_data.search_keywords,
                "companies": company_contexts,
                "competitor_intelligence": competitor_context[:5000], # Added comparison context
                "current_timestamp": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
        )

        # ── 4. Call Gemini ───────────────────────────────────────────────────
        self.log.info("researcher.gemini_call", request_id=request_id)
        try:
            raw_response = await self.client.generate(_SYSTEM_PROMPT, user_message)
        except Exception as exc:
            self.log_error(request_id, str(exc))
            raise PipelineError(
                message=f"Gemini call failed in @researcher: {exc}",
                request_id=request_id,
                stage="researcher",
                details={"exception_type": type(exc).__name__},
            ) from exc

        # ── 5. Parse and validate output ─────────────────────────────────────
        try:
            parsed = extract_json(raw_response)
            profiles = [CompetitorProfile(**p) for p in parsed.get("profiles", [])]
            
            # ── 6. Deterministic Market Price Calculation ────────────────────
            prices = []
            for p in profiles:
                if p.price_range:
                    prices.append((p.price_range[0] + p.price_range[1]) / 2)
            
            avg_price = sum(prices) / len(prices) if prices else None
            
            output = MarketResearchOutput(
                request_id=request_id,
                timestamp=datetime.now(timezone.utc),
                profiles=profiles,
                market_average_price=avg_price,
                data_completeness_score=float(parsed.get("data_completeness_score", 0.0)),
            )
        except Exception as exc:
            self.log_error(request_id, f"Output parsing failed: {exc}")
            raise PipelineError(
                message=f"@researcher output parsing failed: {exc}",
                request_id=request_id,
                stage="researcher.parse",
                details={"raw_preview": raw_response[:500]},
            ) from exc

        self.log_complete(request_id)
        self.log.info(
            "researcher.result",
            request_id=request_id,
            profiles=len(output.profiles),
            completeness=output.data_completeness_score,
        )
        return output
