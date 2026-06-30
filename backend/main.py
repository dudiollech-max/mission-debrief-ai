"""
Mission Debrief AI — FastAPI Application Entry Point
Edge AI Recorder + Auto-Debrief for UAV missions
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.api.routes import router

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = structlog.get_logger(__name__)


# ─── App Lifespan ─────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    # Create required directories on startup
    for d in ["uploads", "output/pdfs", "output/frames"]:
        Path(d).mkdir(parents=True, exist_ok=True)

    log.info("Mission Debrief AI started", version="0.1.0")
    yield
    log.info("Mission Debrief AI shutting down")


# ─── Application ──────────────────────────────────────────────────────────────
app = FastAPI(
    title="Mission Debrief AI",
    description="Edge AI Recorder + Auto-Debrief — Multi-stream mission data to structured report in under 60 seconds",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── API Routes ───────────────────────────────────────────────────────────────
app.include_router(router, prefix="/api")


# ─── Health Check ─────────────────────────────────────────────────────────────
@app.get("/health", tags=["System"])
async def health():
    return {
        "status": "ok",
        "service": "mission-debrief-ai",
        "version": "0.1.0",
        "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
        "local_llm": os.getenv("USE_LOCAL_LLM", "false").lower() == "true",
    }


# ─── Frontend Static Files ────────────────────────────────────────────────────
frontend_path = Path(__file__).parent.parent / "frontend"
if frontend_path.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_path)), name="static")

    @app.get("/", include_in_schema=False)
    async def serve_frontend():
        return FileResponse(str(frontend_path / "index.html"))
