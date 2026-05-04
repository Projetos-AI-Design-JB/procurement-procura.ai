# api/main.py
"""
FastAPI Dashboard for Sales Agents Procurement System.
"""

import os
import sys
from pathlib import Path

# Ensure root directory is in sys.path for core.* imports
root_dir = Path(__file__).parent.parent
if str(root_dir) not in sys.path:
    sys.path.append(str(root_dir))

from typing import List, Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from core.orchestrator import Orchestrator
from core.database import DatabaseClient
from core.logger import get_logger

app = FastAPI(title="Sales Agents Procurement Dashboard")
log = get_logger("api")

# Static files for the frontend
static_path = Path(__file__).parent / "static"
static_path.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

# Mount output directory to serve reports
output_path = Path(__file__).parent.parent / "output"
output_path.mkdir(exist_ok=True)
app.mount("/reports", StaticFiles(directory=str(output_path)), name="reports")

db = DatabaseClient()

class RequestTrigger(BaseModel):
    request_file: str  # Path relative to project root or ID

class ResearchInput(BaseModel):
    supplier_name: str
    category: str
    proposed_price: float
    budget_usd: float
    required_features: list[str] = ["Performance", "Security", "Reliability"]

@app.get("/")
async def read_index():
    return FileResponse(static_path / "index.html")

@app.post("/api/research")
async def start_research(input: ResearchInput, background_tasks: BackgroundTasks):
    """Dynamically start research for a new supplier."""
    import json
    import uuid
    
    request_id = f"req-dyn-{uuid.uuid4().hex[:6]}"
    # Include ALL required ProcurementRequest fields to avoid ValidationError
    payload = {
        "request_id": request_id,
        "requester": "Dashboard User",
        "supplier_name": input.supplier_name,
        "product_category": input.category,
        "proposed_price": input.proposed_price,
        "budget_ceiling": input.budget_usd,
        "urgency": "medium",
        "required_features": input.required_features or ["Performance", "Security", "Reliability"]
    }
    
    # Save to root directory
    temp_file = root_dir / f"request_{request_id}.json"
    temp_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    
    # Trigger pipeline
    background_tasks.add_task(run_pipeline_task, temp_file)
    
    return {
        "status": "started", 
        "request_id": request_id, 
        "message": f"Deep Research started for {input.supplier_name}. This will take ~30-60 seconds."
    }

@app.get("/api/requests")
async def list_requests():
    """List all procurement requests from Supabase or local files."""
    if db.is_available:
        try:
            response = db._client.table("procurement_requests").select("*").order("created_at", descending=True).execute()
            return {"status": "online", "data": response.data}
        except Exception as exc:
            log.error("api.list_requests_failed", error=str(exc))
            # Fall back to local parsing

    import json
    requests = []
    output_dir = root_dir / "output"
    # Scan for all request files (dynamic and sample)
    for p in root_dir.iterdir():
        if p.is_file() and p.name.startswith("request_") and p.name.endswith(".json"):
                try:
                    raw = json.loads(p.read_text(encoding="utf-8"))
                    req_id = raw.get("request_id")
                    if not any(r["request_id"] == req_id for r in requests):
                        has_report = (output_dir / f"report_{req_id}.json").exists()
                        error_file = root_dir / f"{req_id}.error"
                        has_error = error_file.exists()
                        error_msg = ""
                        
                        status = "ready"
                        if has_report:
                            status = "done"
                        elif has_error:
                            status = "error"
                            try:
                                error_msg = error_file.read_text(encoding="utf-8").split("\n")[0] # Just first line
                            except:
                                error_msg = "Unknown background error"
                            
                        requests.append({
                            "request_id": req_id,
                            "supplier_name": raw.get("supplier_name", "Unknown"),
                            "budget_usd": raw.get("budget_ceiling", 0.0),
                            "status": status,
                            "error_message": error_msg
                        })
                except:
                    continue
    # Also ensure sample_request.json is included if present
    sample_path = root_dir / "sample_request.json"
    if sample_path.exists():
        try:
            raw = json.loads(sample_path.read_text(encoding="utf-8"))
            req_id = raw.get("request_id")
            if not any(r["request_id"] == req_id for r in requests):
                has_report = (output_dir / f"report_{req_id}.json").exists()
                requests.append({
                    "request_id": req_id,
                    "supplier_name": raw.get("supplier_name", "Sample Supplier"),
                    "budget_usd": raw.get("budget_ceiling", 0.0),
                    "status": "done" if has_report else "ready"
                })
        except:
            pass
            
    return {"status": "offline", "data": requests}

@app.get("/api/reports")
async def list_reports():
    """List all reports from Supabase or local output folder."""
    if db.is_available:
        try:
            response = db._client.table("procurement_reports").select("*").order("created_at", descending=True).execute()
            return {"status": "online", "data": response.data}
        except Exception as exc:
            log.error("api.list_reports_failed", error=str(exc))
            # Fall back to local parsing
            
    output_dir = root_dir / "output"
    reports = []
    if output_dir.exists():
        import json
        for p in output_dir.iterdir():
            if not (p.is_file() and p.name.startswith("report_") and p.name.endswith(".json")):
                continue
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                req_id = raw.get("request_id")
                # Try to get supplier_name from matching request file
                supplier = raw.get("supplier_name", "")
                if not supplier:
                    for req_p in root_dir.iterdir():
                        if req_p.is_file() and req_p.name.endswith(".json"):
                            try:
                                rq = json.loads(req_p.read_text(encoding="utf-8"))
                                if rq.get("request_id") == req_id:
                                    supplier = rq.get("supplier_name", req_id)
                                    break
                            except:
                                pass
                reports.append({
                    "request_id": req_id,
                    "supplier_name": supplier or req_id,
                    "decision": raw.get("procurement_decision", {}).get("decision", "N/A"),
                    "created_at": raw.get("generated_at", "N/A")
                })
            except:
                continue
        return {"status": "offline", "data": reports}

@app.post("/api/run")
async def trigger_pipeline(trigger: RequestTrigger, background_tasks: BackgroundTasks):
    """Trigger the pipeline for a specific request file or ID."""
    if trigger.request_file in ["req-001", "request_req-001.json", "test-123", "request_test-123.json"]:
        sample_path = root_dir / "sample_request.json"
        if sample_path.exists():
            path = sample_path
        else:
            raise HTTPException(status_code=404, detail="Sample request not found.")
    else:
        # Try direct path
        path = Path(trigger.request_file)
        if not path.exists():
            # Try as ID in root_dir
            id_path = root_dir / f"request_{trigger.request_file}.json"
            if id_path.exists():
                path = id_path
            else:
                # Try as filename in root_dir
                root_path = root_dir / trigger.request_file
                if root_path.exists():
                    path = root_path
                else:
                    raise HTTPException(status_code=404, detail=f"Request file or ID '{trigger.request_file}' not found.")

    # Run in background to avoid blocking the API
    background_tasks.add_task(run_pipeline_task, path)
    
    return {"status": "queued", "message": f"Pipeline started for {path.name}"}

@app.delete("/api/request/{request_id}")
async def delete_request(request_id: str):
    """Delete a request and its associated report files."""
    try:
        # 1. Delete from Supabase if available
        if db.is_available:
            try:
                db._client.table("procurement_requests").delete().eq("request_id", request_id).execute()
                db._client.table("procurement_reports").delete().eq("request_id", request_id).execute()
            except Exception as e:
                log.error("api.delete_db_failed", error=str(e))
                
        # 2. Delete request files and error markers
        for p in root_dir.iterdir():
            if p.is_file():
                if (request_id in p.name and p.name.startswith("request_")) or p.name == f"{request_id}.error":
                    p.unlink(missing_ok=True)
                elif p.name == "sample_request.json" and request_id in ["req-001", "test-123"]:
                    p.unlink(missing_ok=True)
        
        # 2. Delete report files in output/
        output_dir = root_dir / "output"
        if output_dir.exists():
            for p in output_dir.iterdir():
                if p.is_file() and request_id in p.name and p.name.startswith("report_"):
                    p.unlink(missing_ok=True)
                    
        return {"status": "success", "message": f"Request {request_id} deleted."}
    except Exception as exc:
        log.error("api.delete_failed", request_id=request_id, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))

async def run_pipeline_task(path: Path):
    import traceback
    log.info("api.pipeline_task_start", file=path.name)
    try:
        orchestrator = Orchestrator()
        await orchestrator.run(path)
        log.info("api.pipeline_task_complete", file=path.name)
    except Exception as exc:
        tb = traceback.format_exc()
        log.error("api.pipeline_task_failed", file=path.name, error=str(exc))
        
        # In local mode, create a .error file to notify the UI
        if not db.is_available:
            try:
                # Extract request_id from filename or path
                req_id = path.stem.replace("request_", "")
                (root_dir / f"{req_id}.error").write_text(str(exc), encoding="utf-8")
            except:
                pass

        # Print full traceback so it's visible in the server console
        print(f"\n[PIPELINE ERROR] {path.name}:\n{tb}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
