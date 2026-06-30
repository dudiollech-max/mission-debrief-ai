# 🛸 Mission Debrief AI

> **Edge AI Recorder + Auto-Debrief** — Multi-stream mission data → structured natural-language report in under 60 seconds.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green.svg)](https://fastapi.tiangolo.com/)
[![Docker](https://img.shields.io/badge/docker-compose-blue.svg)](https://docs.docker.com/compose/)

Part of the **VisionWave AI Suite** — autonomous intelligence for the next generation of UAV operations.

---

## 🎯 What It Does

Mission Debrief AI ingests multi-stream mission data — video, telemetry, sensor logs — and produces a **structured natural-language debrief in under 60 seconds**.

- 📹 **Video Analysis** — Frame extraction + LLM vision analysis of key moments
- 📊 **Telemetry Processing** — Time-series anomaly detection (Z-score + rule-based)
- 📋 **Event Log Parsing** — Structured event timeline reconstruction
- 🤖 **AI Debrief Generation** — GPT-4o-mini synthesizes everything into a professional report
- 📄 **PDF Export** — Print-ready report with thumbnails, tables, and anomaly highlights
- 🔌 **Offline Mode** — Works without any API key (rule-based fallback)

---

## 🚀 Quick Start

### Option 1: Docker (Recommended)

```bash
# Clone the repo
git clone https://github.com/dudiollech-max/mission-debrief-ai.git
cd mission-debrief-ai

# (Optional) Add your OpenAI API key for AI-powered debriefs
echo "OPENAI_API_KEY=your_key_here" > .env

# Start everything
docker-compose up

# Open in browser
open http://localhost:8000
```

### Option 2: Local Python

```bash
git clone https://github.com/dudiollech-max/mission-debrief-ai.git
cd mission-debrief-ai

python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# (Optional) Add your OpenAI API key
cp .env.example .env
# Edit .env with your API key

# Run the demo
uvicorn backend.main:app --reload --port 8000

# Open in browser
open http://localhost:8000
```

---

## 🎬 SolarDrone Demo

Run the built-in demo — no video upload needed:

```bash
# Via HTTP API
curl -X POST http://localhost:8000/api/demo

# Or click "Run SolarDrone Demo" in the UI at http://localhost:8000
```

**Demo Scenario:** 45-minute solar panel inspection flight over a 200-panel solar farm.
- GPS track: 2.4 km inspection route at 50m AGL
- Anomaly detected: Panel #47 thermal hotspot (temperature variance 340°C)
- Low battery warning at T+38:22
- Automatic RTH initiated at T+41:05
- Full debrief generated in ~15 seconds (rule-based) or ~30 seconds (with OpenAI)

---

## 📡 API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/demo` | POST | Run built-in SolarDrone demo |
| `/api/ingest` | POST | Upload mission data (video + telemetry + logs) |
| `/api/debrief/{session_id}` | POST | Trigger debrief generation (SSE streaming) |
| `/api/status/{session_id}` | GET | Get session status + progress % |
| `/api/result/{session_id}` | GET | Get debrief as structured JSON |
| `/api/result/{session_id}/pdf` | GET | Download debrief as PDF |
| `/docs` | GET | Interactive API docs (Swagger UI) |
| `/health` | GET | Health check |

### Ingest Request

```bash
curl -X POST http://localhost:8000/api/ingest \
  -F "video=@mission.mp4" \
  -F "telemetry=@telemetry.json" \
  -F "sensor_log=@events.json" \
  -F "mission_name=Solar Farm Inspection" \
  -F "platform=SolarDrone MK2"
```

---

## 🔧 Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | `""` | OpenAI API key (optional — enables AI debrief) |
| `USE_LOCAL_LLM` | `false` | Use local Ollama instead of OpenAI |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama host URL |
| `OLLAMA_MODEL` | `llava` | Ollama model for vision |
| `MAX_FRAMES` | `20` | Max video frames to extract |
| `FRAME_INTERVAL` | `15` | Extract frame every N seconds |
| `ANOMALY_Z_THRESHOLD` | `2.5` | Z-score threshold for anomaly detection |
| `PDF_OUTPUT_DIR` | `./output/pdfs` | PDF output directory |
| `LOG_LEVEL` | `INFO` | Logging level |

---

## 📐 Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Mission Debrief AI                    │
├─────────────────────────────────────────────────────────┤
│  Frontend (HTML/JS/CSS)                                 │
│  ├── Upload UI (video + telemetry + logs)               │
│  ├── Demo trigger (SolarDrone)                          │
│  ├── Live progress (SSE streaming)                      │
│  └── Debrief display + PDF download                     │
├─────────────────────────────────────────────────────────┤
│  FastAPI Backend                                         │
│  ├── /api/ingest    → Ingestion Pipeline                │
│  ├── /api/debrief   → Debrief Generator (SSE)           │
│  ├── /api/result    → JSON + PDF export                 │
│  └── /api/demo      → SolarDrone demo                   │
├─────────────────────────────────────────────────────────┤
│  Core Pipeline                                           │
│  ├── ingestion.py   → Video frames + telemetry parsing  │
│  ├── anomaly.py     → Z-score + rule-based detection    │
│  ├── vision.py      → LLM frame analysis                │
│  ├── debrief.py     → LLM report generation             │
│  └── export.py      → PDF / JSON export                 │
├─────────────────────────────────────────────────────────┤
│  AI Layer                                                │
│  ├── OpenAI gpt-4o-mini (default, if API key set)       │
│  ├── OpenAI gpt-4o (vision analysis)                    │
│  ├── Ollama / llava (local LLM option)                  │
│  └── Rule-based fallback (no API key needed)            │
└─────────────────────────────────────────────────────────┘
```

---

## 📋 Sample Debrief Output (JSON)

```json
{
  "session_id": "solar-demo-001",
  "mission_name": "Solar Farm Inspection — Block A",
  "platform": "SolarDrone MK2",
  "duration_seconds": 2700,
  "summary": "Completed 45-minute solar panel inspection of Block A (200 panels). One critical thermal anomaly detected on Panel #47. Battery management triggered early RTH at 30% charge.",
  "assessment": {
    "overall_rating": "amber",
    "went_well": ["Full panel coverage achieved", "GPS lock maintained throughout"],
    "watch_points": ["Panel #47 requires immediate thermal inspection", "Battery drain 15% above baseline"]
  }
}
```

---

## 🏗️ Built With

- **[FastAPI](https://fastapi.tiangolo.com/)** — Async Python API framework
- **[OpenAI API](https://platform.openai.com/)** — GPT-4o-mini for debrief generation
- **[Pandas](https://pandas.pydata.org/)** — Telemetry time-series processing
- **[SciPy](https://scipy.org/)** — Statistical anomaly detection
- **[ReportLab](https://www.reportlab.com/)** — PDF generation
- **[OpenCV](https://opencv.org/)** — Video frame extraction
- **[Docker](https://www.docker.com/)** — Containerized deployment

---

## 📄 License

MIT License — See [LICENSE](LICENSE) for details.

---

*VisionWave AI Suite · Mission Debrief AI · Edge Intelligence for UAV Operations*
