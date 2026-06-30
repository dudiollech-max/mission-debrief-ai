# Mission Debrief AI — Architecture

## Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     Mission Debrief AI                           │
│             Edge AI Recorder + Auto-Debrief System              │
└─────────────────────────────────────────────────────────────────┘
                              │
                 ┌────────────┴────────────┐
                 │                         │
          ┌──────▼──────┐          ┌───────▼───────┐
          │  Frontend   │          │   FastAPI     │
          │  (HTML/JS)  │◄────────►│   Backend     │
          └─────────────┘  HTTP/  └───────────────┘
                            SSE           │
                                    ┌─────┴──────────────────┐
                                    │    Core Pipeline        │
                                    ├────────────────────────┤
                                    │ ingestion.py           │
                                    │ anomaly.py             │
                                    │ vision.py              │
                                    │ debrief.py             │
                                    │ export.py              │
                                    └────────────────────────┘
                                              │
                              ┌───────────────┼───────────────┐
                              │               │               │
                        ┌─────▼─────┐  ┌──────▼──────┐  ┌───▼───┐
                        │ OpenAI    │  │   Ollama    │  │ Rules │
                        │ gpt-4o    │  │ llava/qwen  │  │ Based │
                        └───────────┘  └─────────────┘  └───────┘
```

## Data Flow

### 1. Ingest (`POST /api/ingest`)

```
Video (MP4/MOV) ──────► Frame Extraction (OpenCV)
                              │
Telemetry (JSON) ─────► DataFrame (pandas) ──► Time-series
                              │
Sensor Log (JSON) ────► Event List ──────────► Structured events
                              │
                         Session Store (in-memory)
                              │
                         session_id returned
```

### 2. Debrief Generation (`POST /api/debrief/{session_id}`)

```
Session Data
     │
     ├── Anomaly Detection (anomaly.py)
     │      ├── Z-score detection on continuous channels
     │      │   (altitude, speed, battery, vertical_speed)
     │      ├── Rule-based threshold violations
     │      │   (battery < 20%, altitude < 5m, speed > 20 m/s)
     │      └── Event log anomaly extraction
     │
     ├── Vision Analysis (vision.py)
     │      ├── For each extracted frame:
     │      │   ├── OpenAI gpt-4o: "describe + INTERESTING: YES/NO"
     │      │   ├── Ollama/llava: local inference
     │      │   └── Rule-based: position-based descriptions
     │      └── Filter → interesting_moments[]
     │
     └── Debrief Generation (debrief.py)
            ├── OpenAI gpt-4o-mini:
            │   Input: anomalies + events + frame descriptions
            │   Output: summary, timeline, decision_points, assessment
            │
            └── Rule-based fallback:
                Heuristic generation from structured data
```

### 3. Export

```
DebriefResult (Pydantic model)
     │
     ├── JSON: model.model_dump() → response
     │
     └── PDF (export.py + ReportLab):
            ├── Dark-themed A4 document
            ├── Mission header + metadata table
            ├── Summary paragraph
            ├── Assessment grid (went well / watch points)
            ├── Anomaly table (sortable by severity)
            ├── Timeline table
            ├── Decision points (bordered cards)
            └── Interesting moments
```

## Key Design Decisions

### Session Store
Currently in-memory dict (`SESSIONS`). In production, replace with:
- Redis (for horizontal scaling)
- PostgreSQL (for persistence)
- S3/blob storage for uploaded files

### LLM Strategy (3-tier)

| Tier | When | Model | Cost |
|------|------|-------|------|
| 1 | OPENAI_API_KEY set + not USE_LOCAL_LLM | gpt-4o-mini | ~$0.001/debrief |
| 2 | USE_LOCAL_LLM=true | Ollama/llava | Free (local) |
| 3 | No key, no local | Rule-based | Free |

Vision analysis uses gpt-4o (more capable) when API key is set.

### Anomaly Detection

Z-score: `|value - mean| / std > threshold` (default 2.5σ)
- Applied per channel independently
- Clustering: skip anomalies within 60s of each other
- Channels: altitude_m, speed_ms, battery_pct, vertical_speed_ms

Rule-based thresholds:
```python
RULES = {
    "battery_critical": {"channel": "battery_pct", "op": "lt", "value": 20},
    "battery_low": {"channel": "battery_pct", "op": "lt", "value": 30},
    "altitude_floor": {"channel": "altitude_m", "op": "lt", "value": 5},
    "speed_limit": {"channel": "speed_ms", "op": "gt", "value": 20},
    "temp_high": {"channel": "temperature_c", "op": "gt", "value": 80},
}
```

### SSE Streaming
The `/api/debrief/{session_id}` endpoint uses Server-Sent Events for real-time progress:
```
event: progress
data: {"progress": 35, "message": "Running anomaly detection..."}

event: progress
data: {"progress": 75, "message": "Generating debrief with AI..."}

event: complete
data: {"result": {...}}
```

## File Structure

```
mission-debrief-ai/
├── backend/
│   ├── main.py          # FastAPI app + static file serving
│   ├── api/
│   │   ├── routes.py    # All endpoints
│   │   └── models.py    # Pydantic schemas
│   ├── core/
│   │   ├── ingestion.py # Multi-stream parsing
│   │   ├── anomaly.py   # Z-score + rule detection
│   │   ├── vision.py    # LLM frame analysis
│   │   ├── debrief.py   # Report generation
│   │   └── export.py    # PDF/JSON export
│   └── demo/
│       ├── solar_drone.py  # Demo data generator
│       └── sample_data/    # Static sample JSON
├── frontend/
│   ├── index.html       # SPA (served by FastAPI)
│   ├── app.js           # UI logic
│   └── style.css        # VisionWave dark theme
└── docs/
    ├── architecture.md  # This file
    └── demo-guide.md    # Demo walkthrough
```

## Performance

Target: debrief in under 60 seconds.

| Step | Time (no API) | Time (OpenAI) |
|------|--------------|---------------|
| Ingest + parse | ~0.5s | ~0.5s |
| Anomaly detection | ~0.2s | ~0.2s |
| Vision analysis (20 frames) | ~0s | ~15-30s |
| Debrief generation | ~0.1s | ~3-5s |
| PDF export | ~1-2s | ~1-2s |
| **Total** | **~2-3s** | **~20-40s** |

Demo mode (no real video): typically 2-5 seconds total.
