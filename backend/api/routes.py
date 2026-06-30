"""
Mission Debrief AI — API Routes
Endpoints: /ingest, /debrief, /status, /result, /demo
"""

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import AsyncGenerator

import aiofiles
import structlog
from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from backend.api.models import (
    DebriefResult,
    DemoResponse,
    IngestResponse,
    SessionStatus,
)
from backend.core.debrief import generate_debrief
from backend.core.ingestion import ingest_mission_data
from backend.demo.solar_drone import generate_solar_drone_demo

log = structlog.get_logger(__name__)

router = APIRouter()

# ─── In-memory session store (replace with Redis/DB in production) ─────────────
SESSIONS: dict[str, dict] = {}


# ─── POST /ingest ─────────────────────────────────────────────────────────────
@router.post("/ingest", response_model=IngestResponse, tags=["Mission"])
async def ingest(
    background_tasks: BackgroundTasks,
    mission_name: str = Form(default="Mission"),
    platform: str = Form(default="Unknown UAV"),
    video: Optional[UploadFile] = File(default=None),
    telemetry: Optional[UploadFile] = File(default=None),
    sensor_log: Optional[UploadFile] = File(default=None),
):
    """
    Ingest multi-stream mission data.
    Accepts: video (MP4/MOV), telemetry (JSON), sensor_log (JSON).
    Returns a session_id to poll for status.
    """
    session_id = str(uuid.uuid4())[:8]
    upload_dir = Path("uploads") / session_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    saved = {}

    # Save uploaded files
    for name, file_obj in [("video", video), ("telemetry", telemetry), ("sensor_log", sensor_log)]:
        if file_obj and file_obj.filename:
            dest = upload_dir / file_obj.filename
            async with aiofiles.open(dest, "wb") as f:
                content = await file_obj.read()
                await f.write(content)
            saved[name] = str(dest)
            log.info("Saved upload", session_id=session_id, file=name, path=str(dest))

    # Initialize session
    SESSIONS[session_id] = {
        "session_id": session_id,
        "status": "pending",
        "progress": 0,
        "message": "Mission data received. Ready for debrief.",
        "mission_name": mission_name,
        "platform": platform,
        "files": saved,
        "result": None,
        "error": None,
    }

    return IngestResponse(
        session_id=session_id,
        message="Mission data ingested. POST /api/debrief/{session_id} to generate debrief.",
        has_video="video" in saved,
        has_telemetry="telemetry" in saved,
        has_sensor_log="sensor_log" in saved,
    )


# ─── POST /debrief/{session_id} — SSE streaming ───────────────────────────────
@router.post("/debrief/{session_id}", tags=["Mission"])
async def trigger_debrief(session_id: str):
    """
    Trigger debrief generation for a session.
    Returns Server-Sent Events (SSE) stream with progress updates.
    """
    if session_id not in SESSIONS:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    session = SESSIONS[session_id]
    if session["status"] in ("generating", "complete"):
        raise HTTPException(status_code=409, detail=f"Session already in state: {session['status']}")

    async def event_stream() -> AsyncGenerator[str, None]:
        try:
            session["status"] = "ingesting"
            session["progress"] = 10
            yield _sse_event("progress", {"progress": 10, "message": "Parsing mission data..."})

            # Run ingestion + debrief pipeline
            async for event in generate_debrief(session_id, session):
                yield _sse_event("progress", event)
                SESSIONS[session_id].update(event)

            # Final result
            result = SESSIONS[session_id].get("result")
            if result:
                yield _sse_event("complete", {"result": result.model_dump() if hasattr(result, 'model_dump') else result})
            else:
                yield _sse_event("error", {"message": "Debrief generation failed"})

        except Exception as e:
            log.exception("Debrief generation error", session_id=session_id, error=str(e))
            SESSIONS[session_id]["status"] = "error"
            SESSIONS[session_id]["error"] = str(e)
            yield _sse_event("error", {"message": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ─── GET /status/{session_id} ─────────────────────────────────────────────────
@router.get("/status/{session_id}", response_model=SessionStatus, tags=["Mission"])
async def get_status(session_id: str):
    """Get session status and progress percentage."""
    if session_id not in SESSIONS:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    s = SESSIONS[session_id]
    return SessionStatus(
        session_id=session_id,
        status=s.get("status", "unknown"),
        progress=s.get("progress", 0),
        message=s.get("message", ""),
        error=s.get("error"),
    )


# ─── GET /result/{session_id} ─────────────────────────────────────────────────
@router.get("/result/{session_id}", response_model=DebriefResult, tags=["Mission"])
async def get_result(session_id: str):
    """Get the completed debrief result as structured JSON."""
    if session_id not in SESSIONS:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    s = SESSIONS[session_id]
    if s["status"] != "complete":
        raise HTTPException(
            status_code=202,
            detail=f"Debrief not ready. Status: {s['status']} ({s.get('progress', 0)}%)",
        )

    return s["result"]


# ─── GET /result/{session_id}/pdf ─────────────────────────────────────────────
@router.get("/result/{session_id}/pdf", tags=["Mission"])
async def get_pdf(session_id: str):
    """Download the debrief as a PDF file."""
    if session_id not in SESSIONS:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    s = SESSIONS[session_id]
    if s["status"] != "complete":
        raise HTTPException(status_code=202, detail="Debrief not ready yet.")

    pdf_path = Path("output/pdfs") / f"{session_id}.pdf"
    if not pdf_path.exists():
        # Generate PDF on demand
        from backend.core.export import export_pdf
        result = s.get("result")
        if not result:
            raise HTTPException(status_code=404, detail="No result available")
        await export_pdf(result, str(pdf_path))

    if not pdf_path.exists():
        raise HTTPException(status_code=500, detail="PDF generation failed")

    mission_name = s.get("mission_name", "mission").replace(" ", "_")
    return FileResponse(
        str(pdf_path),
        media_type="application/pdf",
        filename=f"debrief_{session_id}_{mission_name}.pdf",
    )


# ─── POST /demo ───────────────────────────────────────────────────────────────
@router.post("/demo", response_model=DemoResponse, tags=["Demo"])
async def run_demo(background_tasks: BackgroundTasks):
    """
    Run the built-in SolarDrone inspection demo.
    No upload needed — generates realistic mission data and produces a full debrief.
    """
    session_id = f"solar-demo-{str(uuid.uuid4())[:6]}"

    # Initialize demo session
    SESSIONS[session_id] = {
        "session_id": session_id,
        "status": "pending",
        "progress": 0,
        "message": "SolarDrone demo initializing...",
        "mission_name": "Solar Farm Inspection — Block A",
        "platform": "SolarDrone MK2",
        "files": {},
        "is_demo": True,
        "result": None,
        "error": None,
    }

    # Run demo in background
    background_tasks.add_task(_run_demo_background, session_id)

    return DemoResponse(
        session_id=session_id,
        message="SolarDrone demo started. Poll GET /api/status/{session_id} for progress.",
        demo_type="solar_drone",
    )


async def _run_demo_background(session_id: str):
    """Background task: run the full solar drone demo pipeline."""
    try:
        session = SESSIONS[session_id]
        async for event in generate_solar_drone_demo(session_id):
            SESSIONS[session_id].update(event)
            await asyncio.sleep(0.1)
    except Exception as e:
        log.exception("Demo error", session_id=session_id, error=str(e))
        SESSIONS[session_id]["status"] = "error"
        SESSIONS[session_id]["error"] = str(e)


# ─── GET /demo/stream/{session_id} — SSE for demo progress ────────────────────
@router.get("/demo/stream/{session_id}", tags=["Demo"])
async def demo_stream(session_id: str):
    """SSE stream for demo progress (poll-friendly alternative to status)."""
    if session_id not in SESSIONS:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    async def stream():
        last_progress = -1
        timeout = 120  # max 120 seconds
        start = time.time()

        while time.time() - start < timeout:
            s = SESSIONS.get(session_id, {})
            status = s.get("status", "unknown")
            progress = s.get("progress", 0)

            if progress != last_progress:
                last_progress = progress
                yield _sse_event("progress", {
                    "progress": progress,
                    "message": s.get("message", ""),
                    "status": status,
                })

            if status == "complete":
                result = s.get("result")
                if result:
                    yield _sse_event("complete", {
                        "result": result.model_dump() if hasattr(result, 'model_dump') else result
                    })
                break
            elif status == "error":
                yield _sse_event("error", {"message": s.get("error", "Unknown error")})
                break

            await asyncio.sleep(0.5)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ─── Helpers ──────────────────────────────────────────────────────────────────
def _sse_event(event_type: str, data: dict) -> str:
    """Format a Server-Sent Event message."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
