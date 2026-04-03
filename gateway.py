#!/usr/bin/env python3
"""
OpenClaw Gateway — production API with orchestration, approvals, metrics, security.
"""
import os
import time
import uuid
import json
import logging
import yaml
from typing import Optional, Dict, Any, List
from datetime import datetime

from fastapi import FastAPI, Request, HTTPException, Header, Depends, Body, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn

from .config.settings import settings
from .state.models import init_db, Event, EventType
from .core.orchestrator import Orchestrator
from .approvals.api import router as approvals_router
from .telemetry import set_trace_id

START_TIME = time.time()

# ----- Auth dependencies -----
def verify_api_key(Authorization: Optional[str] = Header(None)):
    """Enforce Bearer token if OPENCLAW_API_KEY is set."""
    api_key = os.getenv("OPENCLAW_API_KEY")
    if api_key:
        if not Authorization:
            raise HTTPException(status_code=401, detail="Missing Authorization header")
        try:
            scheme, token = Authorization.split()
            if scheme.lower() != "bearer":
                raise HTTPException(status_code=401, detail="Invalid scheme")
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid Authorization header")
        if token != api_key:
            raise HTTPException(status_code=401, detail="Invalid API key")

def require_user_id(x_user_id: Optional[str] = Header(None, alias="X-User-ID")):
    """Require a user identifier for approval operations."""
    if not x_user_id:
        raise HTTPException(status_code=400, detail="X-User-ID header required")
    return x_user_id

# ----- App setup -----
logging.basicConfig(
    level=getattr(logging, settings.logging.level),
    format='%(asctime)s %(levelname)s %(name)s %(message)s' if settings.logging.format == "text" else '%(message)s'
)
logger = logging.getLogger("openclaw.gateway")

app = FastAPI(title="OpenClaw Gateway", version="1.2.0")
# Approvals router will have its own dependencies (+ user_id)
app.include_router(approvals_router, dependencies=[Depends(verify_api_key)])

# DB & Permissions
db_factory = init_db(settings.database.url)
with open(settings.permissions.path) as f:
    perms = yaml.safe_load(f)

# Orchestrator
orchestrator = Orchestrator(db_session_factory=db_factory, permissions=perms)

# Metrics
metrics = {
    "requests_total": 0,
    "requests_failed": 0,
    "rate_limited": 0,
    "webhooks_received": 0,
}
def refresh_metrics():
    metrics.update(orchestrator.metrics)

# ----- Middleware -----
@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    request_id = str(uuid.uuid4())[:8]
    request.state.request_id = request_id
    set_trace_id(request_id)  # propagate for this request
    start = time.time()
    metrics["requests_total"] += 1
    try:
        response = await call_next(request)
        elapsed = time.time() - start
        logger.info("http completed", extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "ms": int(elapsed*1000)
        })
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception as exc:
        metrics["requests_failed"] += 1
        logger.error("http failed", extra={"request_id": request_id, "error": str(exc)})
        raise

# ----- Public endpoints -----
@app.get("/health")
async def health():
    uptime = time.time() - START_TIME
    orchestrator_metrics = orchestrator.metrics if orchestrator else {}
    return {
        "status": "ok",
        "timestamp": time.time(),
        "version": "1.2.0",
        "environment": settings.ENV,
        "uptime_seconds": round(uptime, 2),
        "database": "connected" if db_factory else "disconnected",
        "orchestrator": orchestrator_metrics,
    }

@app.get("/metrics")
async def get_metrics():
    refresh_metrics()
    return metrics

# ----- Protected endpoints (orchestration) -----
@app.post("/tasks", dependencies=[Depends(verify_api_key)])
async def create_task(
    description: str = Body(..., embed=True),
    task_type: str = Body("generic", embed=True),
    user: Optional[str] = Body(None, embed=True)
):
    """Receive a new task → orchestrator.receive_task()"""
    task_id = orchestrator.receive_task(task_type, {"description": description})
    plan = orchestrator.plan_task(task_id, description)
    result = orchestrator.execute_plan(task_id, plan, user)
    refresh_metrics()
    return result

@app.get("/tasks/{task_id}/events", dependencies=[Depends(verify_api_key)])
async def task_events(task_id: str):
    db = db_factory()
    events = db.query(Event).filter(Event.task_id == task_id).order_by(Event.timestamp.asc()).all()
    return [
        {
            "event_id": e.event_id,
            "type": e.type.value,
            "payload": e.payload,
            "timestamp": e.timestamp.isoformat(),
            "source": e.source,
        }
        for e in events
    ]

@app.post("/hooks/github", dependencies=[Depends(verify_api_key)])
async def github_webhook(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(None),
    x_github_event: Optional[str] = Header(None, alias="X-GitHub-Event"),
):
    payload = await request.body()
    # TODO: implement HMAC verification using settings.gateway.secret
    metrics["webhooks_received"] += 1
    try:
        data = json.loads(payload.decode())
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    logger.info("github webhook", extra={"event": x_github_event, "repo": data.get("repository", {}).get("full_name")})
    return {"status": "queued", "event": x_github_event}

if __name__ == "__main__":
    uvicorn.run(
        "polish.openclaw.gateway:app",
        host="0.0.0.0",
        port=settings.gateway.port,
        reload=settings.ENV == "development",
    )
