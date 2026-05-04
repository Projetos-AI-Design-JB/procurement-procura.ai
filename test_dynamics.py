import asyncio
from pathlib import Path
import json

from core.orchestrator import Orchestrator

async def test():
    req_path = Path("sample_request.json")
    if not req_path.exists():
        req_path.write_text(json.dumps({
            "request_id": "test-123",
            "requester": "Test User",
            "supplier_name": "Hubspot",
            "product_category": "CRM / Sales Tools",
            "proposed_price": 500,
            "budget_ceiling": 1000,
            "urgency": "medium",
            "required_features": ["Lead scoring", "Pipeline automation"]
        }))
    
    print(f"Triggering pipeline for {req_path}...")
    orchestrator = Orchestrator()
    try:
        await orchestrator.run(req_path)
        print("\n\n=== PIPELINE SUCCESS ===")
        report = Path(f"output/report_test-123.md")
        if report.exists():
            print("REPORT CONTENT:")
            print(report.read_text())
        else:
            print("NO REPORT FOUND!")
    except Exception as e:
        print(f"\n\n=== PIPELINE ERROR ===\n{e}")

if __name__ == "__main__":
    asyncio.run(test())
