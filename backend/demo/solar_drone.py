"""
Mission Debrief AI — SolarDrone Demo

Generates a realistic 45-minute solar panel inspection mission:
- GPS track over solar farm, altitude 50m AGL
- Battery drain 100% → 30%
- Key anomaly: Panel #47 thermal hotspot detected
- Low battery warning → RTH initiated
- No real video needed — uses simulated frame descriptions

Usage:
    async for event in generate_solar_drone_demo(session_id):
        print(event)
"""

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator

import numpy as np
import pandas as pd
import structlog

from backend.api.models import (
    AnomalyEvent,
    Assessment,
    DebriefResult,
    DecisionPoint,
    InterestingMoment,
    TimelineEvent,
)
from backend.core.export import export_pdf

log = structlog.get_logger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# ─── Mission parameters ────────────────────────────────────────────────────────
MISSION_NAME = "Solar Farm Inspection — Block A"
PLATFORM = "SolarDrone MK2"
DURATION_SECONDS = 2700  # 45 minutes
PANEL_COUNT = 200
ANOMALY_PANEL = 47
SOLAR_FARM_CENTER = (51.5074, -0.1278)  # London area (demo)


async def generate_solar_drone_demo(session_id: str) -> AsyncGenerator[dict, None]:
    """
    Full demo pipeline — no video upload needed.
    Streams progress events and stores result in SESSIONS.
    """
    start_time = time.time()

    yield {"progress": 10, "status": "ingesting", "message": "Generating SolarDrone mission data..."}
    await asyncio.sleep(0.5)

    # Generate telemetry
    telemetry = _generate_telemetry()
    events = _generate_events()
    frames = _generate_frames()

    yield {"progress": 30, "status": "analyzing", "message": "Running anomaly detection on telemetry..."}
    await asyncio.sleep(0.5)

    anomalies = _generate_anomalies(telemetry, events)

    yield {"progress": 50, "status": "analyzing", "message": "Analyzing inspection frames..."}
    await asyncio.sleep(0.5)

    yield {"progress": 70, "status": "generating", "message": "Generating structured debrief..."}
    await asyncio.sleep(0.5)

    if OPENAI_API_KEY:
        result = await _generate_ai_debrief(session_id, telemetry, events, frames, anomalies)
    else:
        result = _generate_rule_based_debrief(session_id, anomalies, events, frames)

    yield {"progress": 88, "status": "exporting", "message": "Generating PDF report..."}
    await asyncio.sleep(0.3)

    try:
        pdf_path = f"output/pdfs/{session_id}.pdf"
        await export_pdf(result, pdf_path)
    except Exception as e:
        log.warning("PDF export failed (non-fatal)", error=str(e))

    elapsed = time.time() - start_time
    result.processing_time_seconds = round(elapsed, 2)

    yield {
        "progress": 100,
        "status": "complete",
        "message": f"Demo complete in {elapsed:.1f}s — Panel #{ANOMALY_PANEL} hotspot flagged",
        "result": result,
    }


# ─── Telemetry Generation ─────────────────────────────────────────────────────

def _generate_telemetry() -> list[dict]:
    """Generate realistic 45-min solar inspection telemetry."""
    np.random.seed(42)
    records = []

    # Flight phases
    phases = [
        (0, 90, "takeoff"),        # 0-1:30 — takeoff and climb
        (90, 300, "transit"),      # 1:30-5:00 — transit to farm
        (300, 2400, "inspection"), # 5:00-40:00 — systematic scan
        (2400, 2580, "rth"),       # 40:00-43:00 — return to home
        (2580, 2700, "landing"),   # 43:00-45:00 — landing
    ]

    # Solar farm bounding box (simulated)
    lat_start, lon_start = 51.5080, -0.1250
    lat_end, lon_end = 51.5060, -0.1300
    lat_step = (lat_end - lat_start) / 10  # 10 scan rows

    current_row = 0
    scan_direction = 1  # 1 = east-west, -1 = west-east

    for t in range(0, DURATION_SECONDS + 1, 5):  # Sample every 5 seconds
        phase = _get_phase(t, phases)
        progress = t / DURATION_SECONDS

        # Altitude profile
        if phase == "takeoff":
            altitude = min(50, t * 0.6)  # Climb to 50m
        elif phase == "landing":
            alt_progress = (t - 2580) / 120
            altitude = max(0, 50 * (1 - alt_progress))
        else:
            altitude = 50 + np.random.normal(0, 0.3)  # Stable at 50m

        # Speed profile
        if phase in ("takeoff", "landing"):
            speed = 3.0 + np.random.normal(0, 0.2)
        elif phase == "transit":
            speed = 8.0 + np.random.normal(0, 0.4)
        elif phase == "inspection":
            speed = 5.0 + np.random.normal(0, 0.3)
        else:  # rth
            speed = 7.0 + np.random.normal(0, 0.3)

        # Battery drain (starts at 100%, ends at 30%)
        battery = max(30, 100 - (70 * progress))
        battery += np.random.normal(0, 0.5)

        # GPS position — systematic scan pattern
        if phase == "inspection":
            scan_progress = (t - 300) / 2100
            row = int(scan_progress * 10)
            row_progress = (scan_progress * 10) % 1.0
            if row % 2 == 0:
                lon = lon_start + (lon_end - lon_start) * row_progress
            else:
                lon = lon_end + (lon_start - lon_end) * row_progress
            lat = lat_start + (lat_end - lat_start) * (row / 10)
        elif phase == "transit":
            transit_progress = (t - 90) / 210
            lat = SOLAR_FARM_CENTER[0] + (lat_start - SOLAR_FARM_CENTER[0]) * transit_progress
            lon = SOLAR_FARM_CENTER[1] + (lon_start - SOLAR_FARM_CENTER[1]) * transit_progress
        elif phase == "rth":
            rth_progress = (t - 2400) / 180
            lat = lat_start + (SOLAR_FARM_CENTER[0] - lat_start) * rth_progress
            lon = lon_start + (SOLAR_FARM_CENTER[1] - lon_start) * rth_progress
        else:
            lat = SOLAR_FARM_CENTER[0] + np.random.normal(0, 0.0001)
            lon = SOLAR_FARM_CENTER[1] + np.random.normal(0, 0.0001)

        # Add panel #47 thermal anomaly at T+28:30 (1710s)
        thermal_temp = None
        if 1680 <= t <= 1740:
            # Panel 47 detected — thermal spike
            thermal_temp = 340 + np.random.normal(0, 5)  # 340°C hotspot

        records.append({
            "elapsed_seconds": t,
            "timestamp": f"2024-06-15T09:{(t//60):02d}:{(t%60):02d}Z",
            "latitude": round(lat + np.random.normal(0, 0.00005), 7),
            "longitude": round(lon + np.random.normal(0, 0.00005), 7),
            "altitude_m": round(max(0, altitude), 2),
            "speed_ms": round(max(0, speed), 2),
            "battery_pct": round(max(0, min(100, battery)), 1),
            "heading_deg": 90 if (t // 300) % 2 == 0 else 270,
            "vertical_speed_ms": round(np.random.normal(0, 0.1), 2),
            "signal_strength": round(max(60, 95 - progress * 20), 0),
            "thermal_temp_c": round(thermal_temp, 1) if thermal_temp else None,
            "phase": phase,
        })

    return records


def _get_phase(t: int, phases: list) -> str:
    for start, end, name in phases:
        if start <= t < end:
            return name
    return "complete"


# ─── Event Log Generation ─────────────────────────────────────────────────────

def _generate_events() -> list[dict]:
    """Generate realistic solar inspection event log."""
    return [
        {"elapsed_seconds": 0, "type": "mission_start", "severity": "info",
         "message": "SolarDrone MK2 powered on — GPS lock acquired (12 satellites)",
         "data": {"satellites": 12, "home_lat": 51.5074, "home_lon": -0.1278}},

        {"elapsed_seconds": 45, "type": "takeoff", "severity": "info",
         "message": "Takeoff initiated — weather: clear, wind 3 km/h NE",
         "data": {"wind_kmh": 3, "direction": "NE", "visibility": "excellent"}},

        {"elapsed_seconds": 90, "type": "altitude_hold", "severity": "info",
         "message": "Altitude hold engaged at 50m AGL — transiting to solar farm"},

        {"elapsed_seconds": 300, "type": "panel_scan_start", "severity": "info",
         "message": "Beginning systematic panel scan — Block A, 200 panels, 10 rows",
         "data": {"block": "A", "panel_count": 200, "rows": 10, "scan_speed": "5 m/s"}},

        {"elapsed_seconds": 600, "type": "panel_scan_row", "severity": "info",
         "message": "Completed scan rows 1-2 (40 panels) — all nominal",
         "data": {"rows_completed": 2, "panels_scanned": 40, "anomalies": 0}},

        {"elapsed_seconds": 900, "type": "panel_scan_row", "severity": "info",
         "message": "Completed scan rows 3-4 (80 panels) — all nominal",
         "data": {"rows_completed": 4, "panels_scanned": 80, "anomalies": 0}},

        {"elapsed_seconds": 1200, "type": "panel_scan_row", "severity": "info",
         "message": "Completed scan rows 5-6 (120 panels) — all nominal",
         "data": {"rows_completed": 6, "panels_scanned": 120, "anomalies": 0}},

        {"elapsed_seconds": 1710, "type": "thermal_anomaly_detected", "severity": "critical",
         "message": "🚨 THERMAL ANOMALY: Panel #47 — temperature 340°C (threshold: 80°C). Possible hotspot, cell failure, or bypass diode fault.",
         "data": {"panel_id": 47, "temp_celsius": 340, "threshold": 80,
                  "position": {"row": 7, "column": 7}, "severity": "critical",
                  "possible_cause": "bypass_diode_fault"}},

        {"elapsed_seconds": 1740, "type": "anomaly_flagged", "severity": "warning",
         "message": "Panel #47 flagged for immediate ground inspection — location logged, thumbnail captured",
         "data": {"action": "flagged", "panel_id": 47, "action": "Operator notified; location logged for ground team"}},

        {"elapsed_seconds": 1800, "type": "panel_scan_row", "severity": "info",
         "message": "Scan continuing — rows 7-8 (160 panels). Anomaly zone marked and isolated.",
         "data": {"rows_completed": 8, "panels_scanned": 160, "anomalies": 1}},

        {"elapsed_seconds": 2100, "type": "panel_scan_row", "severity": "info",
         "message": "Completed scan rows 9-10 (200 panels) — Block A scan complete",
         "data": {"rows_completed": 10, "panels_scanned": 200, "anomalies": 1}},

        {"elapsed_seconds": 2302, "type": "battery_warning", "severity": "warning",
         "message": "Battery at 30% — Return-to-Home threshold reached. Mission time: 38:22",
         "data": {"battery_pct": 30, "threshold": 30, "action": "Operator alerted; RTH standby"}},

        {"elapsed_seconds": 2465, "type": "rth_initiated", "severity": "warning",
         "message": "Return-to-Home initiated — battery at 26%. Estimated landing time: 3 minutes.",
         "data": {"battery_pct": 26, "distance_to_home_m": 420, "action": "RTH engaged by operator command"}},

        {"elapsed_seconds": 2640, "type": "landing_approach", "severity": "info",
         "message": "Approaching landing zone — final approach checklist complete",
         "data": {"altitude": 15, "battery_pct": 31}},

        {"elapsed_seconds": 2695, "type": "landed", "severity": "info",
         "message": "SolarDrone MK2 landed successfully — mission complete",
         "data": {"total_panels_scanned": 200, "anomalies_detected": 1,
                  "battery_remaining_pct": 30, "mission_status": "complete"}},
    ]


# ─── Frame Simulation ─────────────────────────────────────────────────────────

def _generate_frames() -> list[dict]:
    """Simulate video frame descriptions for the inspection flight."""
    return [
        {"elapsed_seconds": 0, "timestamp": "00:00:00", "path": None,
         "description": "Launch pad visible, SolarDrone MK2 sitting on ground. Clear blue sky, no clouds. Ground crew in high-visibility vests performing pre-flight checks.",
         "is_interesting": False},

        {"elapsed_seconds": 90, "timestamp": "00:01:30", "path": None,
         "description": "Ascending over launch area. Ground equipment shrinking below. Solar farm visible 500m ahead — rows of panels gleaming in morning sun.",
         "is_interesting": False},

        {"elapsed_seconds": 300, "timestamp": "00:05:00", "path": None,
         "description": "Arrived over Block A. Solar panels in perfect rows below, uniform dark blue color. First scan row initiated.",
         "is_interesting": False},

        {"elapsed_seconds": 600, "timestamp": "00:10:00", "path": None,
         "description": "Scanning rows 1-2. All panels show consistent appearance and thermal signature. No anomalies visible to sensor array.",
         "is_interesting": False},

        {"elapsed_seconds": 900, "timestamp": "00:15:00", "path": None,
         "description": "Rows 3-4 complete. Clear overhead view of panel grid. One panel appears slightly soiled (row 4, panel 23) — noted for maintenance log.",
         "is_interesting": False},

        {"elapsed_seconds": 1200, "timestamp": "00:20:00", "path": None,
         "description": "Mid-mission, rows 5-6. Thermal camera showing consistent temperature across panel surface. Grid pattern clean and aligned.",
         "is_interesting": False},

        {"elapsed_seconds": 1500, "timestamp": "00:25:00", "path": None,
         "description": "Approaching row 7. All panels nominal so far. Battery at 58%, well within operational margin.",
         "is_interesting": False},

        {"elapsed_seconds": 1710, "timestamp": "00:28:30", "path": None,
         "description": "⚠ CRITICAL: Panel #47 (row 7, column 7) showing intense thermal hotspot. Significant temperature variance from surrounding panels — glowing orange in thermal overlay. Classic bypass diode failure signature.",
         "is_interesting": True},

        {"elapsed_seconds": 1740, "timestamp": "00:29:00", "path": None,
         "description": "Close-up pass over Panel #47. Hotspot confirmed — localized overheating in upper-left quadrant of panel. Adjacent panels appear unaffected. Coordinates logged.",
         "is_interesting": True},

        {"elapsed_seconds": 1800, "timestamp": "00:30:00", "path": None,
         "description": "Scan continuing past anomaly zone. Row 8 panels appear normal. Battery at 51%.",
         "is_interesting": False},

        {"elapsed_seconds": 2100, "timestamp": "00:35:00", "path": None,
         "description": "Final rows 9-10 complete. Block A scan finished. 200 panels surveyed. 1 critical anomaly detected and logged.",
         "is_interesting": False},

        {"elapsed_seconds": 2302, "timestamp": "00:38:22", "path": None,
         "description": "Battery warning indicator visible on HUD overlay. Drone pivoting for return leg. Solar farm receding.",
         "is_interesting": True},

        {"elapsed_seconds": 2465, "timestamp": "00:41:05", "path": None,
         "description": "RTH mode active. Drone tracking direct line back to launch pad. Ground team visible below preparing for landing.",
         "is_interesting": False},

        {"elapsed_seconds": 2640, "timestamp": "00:44:00", "path": None,
         "description": "Final approach at 15m altitude. Landing pad clearly visible with visual markers. Smooth descent underway.",
         "is_interesting": False},

        {"elapsed_seconds": 2695, "timestamp": "00:44:55", "path": None,
         "description": "Touchdown on landing pad. Mission complete. Ground crew approaching for post-flight inspection.",
         "is_interesting": False},
    ]


# ─── Anomaly Generation ────────────────────────────────────────────────────────

def _generate_anomalies(telemetry: list[dict], events: list[dict]) -> list[AnomalyEvent]:
    """Generate anomalies for the solar drone demo."""
    return [
        AnomalyEvent(
            timestamp="00:28:30",
            type="thermal_hotspot",
            description=f"Panel #{ANOMALY_PANEL} thermal hotspot: 340°C temperature reading (threshold: 80°C). Possible bypass diode failure.",
            severity="critical",
            channel="thermal_sensor",
            value=340.0,
            threshold=80.0,
        ),
        AnomalyEvent(
            timestamp="00:38:22",
            type="battery_low",
            description="Battery reached 30% RTH threshold at T+38:22. Mission objective was complete; RTH protocol activated.",
            severity="warning",
            channel="battery_pct",
            value=30.0,
            threshold=30.0,
        ),
        AnomalyEvent(
            timestamp="00:41:05",
            type="event_rth_initiated",
            description="Return-to-Home initiated by operator command at 26% battery. Estimated 3-minute transit.",
            severity="warning",
            channel="event_log",
            value=26.0,
            threshold=30.0,
        ),
    ]


# ─── Debrief Generation ────────────────────────────────────────────────────────

async def _generate_ai_debrief(
    session_id: str,
    telemetry: list[dict],
    events: list[dict],
    frames: list[dict],
    anomalies: list[AnomalyEvent],
) -> DebriefResult:
    """Generate debrief using OpenAI when available."""
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=OPENAI_API_KEY)

        event_text = "\n".join(f"- {e['timestamp'] if 'timestamp' in e else _hms(e['elapsed_seconds'])}: {e['message']}" for e in events)
        anomaly_text = "\n".join(f"- [{a.severity.upper()}] {a.timestamp}: {a.description}" for a in anomalies)
        frame_text = "\n".join(
            f"- {f['timestamp']}: {f['description']}" + (" [INTERESTING]" if f.get("is_interesting") else "")
            for f in frames
        )

        prompt = f"""You are analyzing a SolarDrone inspection mission. Generate a professional debrief JSON.

MISSION: {MISSION_NAME}
PLATFORM: {PLATFORM}
DURATION: 45 minutes

KEY EVENTS:
{event_text}

ANOMALIES DETECTED:
{anomaly_text}

VIDEO ANALYSIS:
{frame_text}

Return ONLY valid JSON with this structure:
{{
  "summary": "2-3 sentence professional summary",
  "timeline": [{{"timestamp": "HH:MM:SS", "event": "description", "severity": "info|warning|critical"}}],
  "decision_points": [{{"timestamp": "HH:MM:SS", "situation": "...", "action_taken": "..."}}],
  "assessment": {{
    "went_well": ["list of positives"],
    "watch_points": ["list of concerns"],
    "overall_rating": "amber"
  }}
}}"""

        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            response_format={"type": "json_object"},
            max_tokens=2000,
        )

        ai_data = json.loads(response.choices[0].message.content or "{}")
        return _build_result(session_id, ai_data, anomalies, frames, ai_powered=True)

    except Exception as e:
        log.warning("OpenAI demo debrief failed; using rule-based", error=str(e))
        return _generate_rule_based_debrief(session_id, anomalies, events, frames)


def _generate_rule_based_debrief(
    session_id: str,
    anomalies: list[AnomalyEvent],
    events: list[dict],
    frames: list[dict],
) -> DebriefResult:
    """Generate a complete rule-based debrief for the solar drone demo."""

    timeline = [
        TimelineEvent(timestamp="00:00:00", event="SolarDrone MK2 powered on — GPS lock acquired (12 satellites)", severity="info"),
        TimelineEvent(timestamp="00:01:30", event="Takeoff initiated — clear conditions, wind 3 km/h NE", severity="info"),
        TimelineEvent(timestamp="00:05:00", event="Block A systematic scan commenced — 200 panels, 10 rows", severity="info"),
        TimelineEvent(timestamp="00:10:00", event="Rows 1-2 complete (40 panels) — all nominal", severity="info"),
        TimelineEvent(timestamp="00:15:00", event="Rows 3-4 complete (80 panels) — minor soiling noted on panel 23", severity="info"),
        TimelineEvent(timestamp="00:20:00", event="Rows 5-6 complete (120 panels) — all nominal", severity="info"),
        TimelineEvent(timestamp="00:25:00", event="Rows 7-8 scan initiated — battery 58%", severity="info"),
        TimelineEvent(timestamp="00:28:30", event=f"🚨 CRITICAL: Panel #{ANOMALY_PANEL} thermal hotspot detected — 340°C (threshold 80°C)", severity="critical"),
        TimelineEvent(timestamp="00:29:00", event=f"Panel #{ANOMALY_PANEL} flagged — close-up pass completed, coordinates logged", severity="warning"),
        TimelineEvent(timestamp="00:30:00", event="Scan continuing past anomaly zone — rows 8-10", severity="info"),
        TimelineEvent(timestamp="00:35:00", event="Block A scan complete — 200/200 panels surveyed", severity="info"),
        TimelineEvent(timestamp="00:38:22", event="⚠ Battery 30% RTH threshold reached — operator alerted", severity="warning"),
        TimelineEvent(timestamp="00:41:05", event="Return-to-Home initiated by operator — battery 26%", severity="warning"),
        TimelineEvent(timestamp="00:44:00", event="Final approach to landing pad — battery 31%", severity="info"),
        TimelineEvent(timestamp="00:44:55", event="Touchdown — SolarDrone MK2 landed successfully", severity="info"),
    ]

    decision_points = [
        DecisionPoint(
            timestamp="00:28:30",
            situation=f"Critical thermal anomaly detected on Panel #{ANOMALY_PANEL}. Temperature reading 340°C vs baseline 25°C. Possible bypass diode failure.",
            action_taken="Operator initiated close-up inspection pass. Panel location logged with GPS coordinates. Ground inspection team dispatched to location.",
        ),
        DecisionPoint(
            timestamp="00:38:22",
            situation="Battery reached 30% RTH threshold with 5 rows of scan remaining in Block B (not yet started).",
            action_taken="Operator assessed risk: Block A complete (primary objective). Made decision to allow continuation until battery 26% before RTH.",
        ),
        DecisionPoint(
            timestamp="00:41:05",
            situation="Battery at 26%, drone 420m from home base. Continued flight poses landing risk.",
            action_taken="RTH engaged via operator command. Mission scope reduced — Block B deferred to next flight.",
        ),
    ]

    interesting = [
        InterestingMoment(
            timestamp="00:28:30",
            frame_description=f"Panel #{ANOMALY_PANEL} (row 7, column 7) showing intense thermal hotspot. Temperature variance of 340°C from surrounding panels. Classic bypass diode failure signature visible in thermal overlay.",
            reason=f"Critical thermal anomaly — Panel #{ANOMALY_PANEL} exceeds safety threshold by 325%. Immediate ground inspection required.",
        ),
        InterestingMoment(
            timestamp="00:29:00",
            frame_description="Close-up pass confirms localized overheating in upper-left quadrant of panel. Adjacent panels unaffected. Hotspot clearly isolated to single cell cluster.",
            reason="Confirmation pass — anomaly isolated and documented for ground team.",
        ),
        InterestingMoment(
            timestamp="00:38:22",
            frame_description="Battery warning HUD overlay visible. Drone pivoting for return leg. 160 panels visible below completing scan.",
            reason="Battery threshold reached — operational decision point requiring RTH evaluation.",
        ),
    ]

    assessment = Assessment(
        went_well=[
            "Full Block A scan completed — 200/200 panels surveyed",
            "GPS lock maintained throughout 45-minute flight (12 satellites)",
            "Critical thermal anomaly on Panel #47 successfully detected and logged",
            "Battery management protocol triggered correctly at threshold",
            "Clean landing with 30% battery reserve maintained",
        ],
        watch_points=[
            f"Panel #{ANOMALY_PANEL} requires immediate ground inspection — thermal hotspot indicates bypass diode failure",
            "Battery drain 15% above baseline — review power consumption or reduce mission scope",
            "Block B scan not completed — schedule follow-up flight",
            "Panel #23 (row 4) noted for minor soiling — schedule cleaning",
        ],
        overall_rating="amber",
    )

    return DebriefResult(
        session_id=session_id,
        mission_name=MISSION_NAME,
        platform=PLATFORM,
        duration_seconds=DURATION_SECONDS,
        generated_at=datetime.now(timezone.utc).isoformat(),
        summary=(
            f"SolarDrone MK2 completed a 45-minute systematic inspection of Solar Farm Block A, "
            f"successfully surveying all 200 panels along a 2.4 km flight path at 50m AGL. "
            f"One critical finding: Panel #{ANOMALY_PANEL} shows a severe thermal hotspot (340°C vs 25°C baseline), "
            f"consistent with a bypass diode failure requiring immediate ground inspection. "
            f"Battery RTH threshold triggered at T+38:22 — Block B deferred to next mission."
        ),
        timeline=timeline,
        anomalies=anomalies,
        decision_points=decision_points,
        assessment=assessment,
        interesting_moments=interesting,
        processing_time_seconds=0,
        ai_powered=False,
        total_frames_analyzed=len(frames),
        total_anomalies=len(anomalies),
    )


def _build_result(
    session_id: str,
    ai_data: dict,
    anomalies: list[AnomalyEvent],
    frames: list[dict],
    ai_powered: bool = True,
) -> DebriefResult:
    """Build DebriefResult from AI-generated data."""
    timeline = [TimelineEvent(**t) for t in ai_data.get("timeline", [])]
    decision_points = [DecisionPoint(**d) for d in ai_data.get("decision_points", [])]
    assessment_d = ai_data.get("assessment", {})
    assessment = Assessment(
        went_well=assessment_d.get("went_well", []),
        watch_points=assessment_d.get("watch_points", []),
        overall_rating=assessment_d.get("overall_rating", "amber"),
    )
    interesting = [
        InterestingMoment(
            timestamp=f["timestamp"],
            frame_description=f["description"],
            reason="AI-flagged interesting moment",
        )
        for f in frames if f.get("is_interesting")
    ]

    return DebriefResult(
        session_id=session_id,
        mission_name=MISSION_NAME,
        platform=PLATFORM,
        duration_seconds=DURATION_SECONDS,
        generated_at=datetime.now(timezone.utc).isoformat(),
        summary=ai_data.get("summary", "Mission completed."),
        timeline=timeline,
        anomalies=anomalies,
        decision_points=decision_points,
        assessment=assessment,
        interesting_moments=interesting,
        processing_time_seconds=0,
        ai_powered=ai_powered,
        total_frames_analyzed=len(frames),
        total_anomalies=len(anomalies),
    )


def _hms(seconds: float) -> str:
    s = int(seconds)
    return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}"


def load_sample_data() -> dict:
    """Load the sample JSON data file."""
    path = Path(__file__).parent / "sample_data" / "solar_mission.json"
    with open(path) as f:
        return json.load(f)
