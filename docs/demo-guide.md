# SolarDrone Demo Guide

## Overview

The built-in SolarDrone demo simulates a complete 45-minute solar panel inspection flight. No real video needed — the system generates realistic telemetry, event logs, and frame descriptions, then runs the full debrief pipeline.

## Demo Scenario

**Mission:** Solar Farm Block A Inspection  
**Platform:** SolarDrone MK2  
**Duration:** 45 minutes  
**Coverage:** 200 solar panels, 10 scan rows, 2.4 km flight path  
**Altitude:** 50m AGL  

### Flight Profile

```
T+00:00  Launch from pad | GPS lock: 12 satellites
T+01:30  Climbing to operational altitude (50m)
T+05:00  Block A systematic scan begins
T+10:00  Rows 1-2 complete (40 panels) — nominal
T+15:00  Rows 3-4 complete (80 panels) — minor soiling panel 23
T+20:00  Rows 5-6 complete (120 panels) — nominal
T+25:00  Rows 7-8 scan initiated — battery 58%

⚠ T+28:30  CRITICAL: Panel #47 thermal hotspot — 340°C
           (threshold: 80°C, possible bypass diode failure)

T+29:00  Close-up pass — hotspot confirmed, GPS coords logged
T+30:00  Scan continues past anomaly zone
T+35:00  Block A complete — 200/200 panels surveyed

⚠ T+38:22  Battery 30% warning — RTH threshold reached
⚠ T+41:05  RTH initiated by operator — battery 26%

T+44:00  Final approach to landing pad
T+44:55  Touchdown — mission complete
```

### Key Anomaly

**Panel #47 Thermal Hotspot**
- Location: Row 7, Column 7
- Observed temp: 340°C
- Baseline temp: ~25°C
- Variance: +1,260%
- Probable cause: Bypass diode failure
- Action: Ground inspection team dispatched

---

## Running the Demo

### Method 1: Web UI

```bash
# Start the server
uvicorn backend.main:app --reload --port 8000

# Open browser
open http://localhost:8000

# Click "Run SolarDrone Demo"
```

### Method 2: API

```bash
# Start demo
curl -X POST http://localhost:8000/api/demo

# Response:
# {"session_id": "solar-demo-abc123", "message": "...", "demo_type": "solar_drone"}

# Poll status
curl http://localhost:8000/api/status/solar-demo-abc123

# Get result (when complete)
curl http://localhost:8000/api/result/solar-demo-abc123

# Download PDF
curl -O http://localhost:8000/api/result/solar-demo-abc123/pdf
```

### Method 3: SSE Stream

```bash
# Start demo
SESSION=$(curl -s -X POST http://localhost:8000/api/demo | python3 -c "import sys,json; print(json.load(sys.stdin)['session_id'])")

# Stream progress
curl -N http://localhost:8000/api/demo/stream/$SESSION
```

---

## What the Demo Produces

### Summary (rule-based, no API key)
> SolarDrone MK2 completed a 45-minute systematic inspection of Solar Farm Block A, successfully surveying all 200 panels along a 2.4 km flight path at 50m AGL. One critical finding: Panel #47 shows a severe thermal hotspot (340°C vs 25°C baseline), consistent with a bypass diode failure requiring immediate ground inspection. Battery RTH threshold triggered at T+38:22 — Block B deferred to next mission.

### Anomalies (3 total)
1. **CRITICAL** — Panel #47 thermal hotspot (340°C)
2. **WARNING** — Battery 30% RTH threshold
3. **WARNING** — RTH initiated at 26% battery

### Assessment
- **Overall:** 🟡 AMBER
- **Went well:** Full scan complete, GPS maintained, hotspot detected and logged
- **Watch points:** Panel #47 immediate inspection, battery drain rate, Block B pending

### PDF Output
Generated at: `output/pdfs/{session_id}.pdf`
- Dark-themed VisionWave branding
- Mission metadata table
- Summary paragraph
- Assessment grid
- Anomaly table
- Full event timeline
- Decision points
- Interesting moments

---

## AI-Powered Demo (with OpenAI key)

Set your API key for AI-generated text:

```bash
export OPENAI_API_KEY=sk-...
uvicorn backend.main:app --reload --port 8000
```

With the API key, the demo produces:
- AI-written mission summary (gpt-4o-mini)
- AI-generated timeline and decision points
- More nuanced assessment language
- Same structure, better prose

Typical processing time with OpenAI: 15-30 seconds.
Without API key (rule-based): 2-5 seconds.

---

## Uploading Real Mission Data

### Telemetry JSON Format

```json
{
  "records": [
    {
      "timestamp": "2024-06-15T09:00:00Z",
      "elapsed_seconds": 0,
      "latitude": 51.5074,
      "longitude": -0.1278,
      "altitude_m": 0,
      "speed_ms": 0,
      "battery_pct": 100,
      "heading_deg": 90,
      "vertical_speed_ms": 0
    },
    ...
  ]
}
```

### Event Log JSON Format

```json
{
  "events": [
    {
      "timestamp": "2024-06-15T09:00:00Z",
      "elapsed_seconds": 0,
      "type": "mission_start",
      "severity": "info",
      "message": "Mission started",
      "data": {}
    },
    ...
  ]
}
```

### Severity Levels

| Level | Meaning |
|-------|---------|
| `info` | Normal operational event |
| `warning` | Requires attention but not critical |
| `critical` | Requires immediate action |

---

## Troubleshooting

**Demo returns 500:** Check server logs — likely a Python import error.
```bash
pip install -r requirements.txt
```

**PDF not generating:** ReportLab may have font issues on some systems.
```bash
pip install reportlab pillow
```

**SSE progress not updating:** Some proxies buffer SSE. Try direct connection:
```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000
# Access at http://localhost:8000
```

**Vision analysis skipped:** No OpenAI key set. Rule-based mode is active.
Set `OPENAI_API_KEY` in `.env` or environment for AI vision analysis.
