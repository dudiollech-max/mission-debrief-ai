"""
Mission Debrief AI — Structured Debrief Generator

Combines:
- Telemetry anomalies (from anomaly.py)
- Vision findings (from vision.py)
- Event logs (from ingestion.py)

Generates:
- Mission summary
- Event timeline
- Anomaly list
- Decision points
- Assessment (went well / watch points / overall rating)
- Interesting moments

Primary: OpenAI gpt-4o-mini
Fallback: Rule-based generation (no API key needed)
"""

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from typing import AsyncGenerator

import structlog

from backend.api.models import (
    AnomalyEvent,
    Assessment,
    DecisionPoint,
    DebriefResult,
    InterestingMoment,
    TimelineEvent,
)
from backend.core.anomaly import detect_anomalies
from backend.core.ingestion import MissionData, ingest_mission_data
from backend.core.vision import analyze_frames, get_interesting_moments

log = structlog.get_logger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")


async def generate_debrief(session_id: str, session: dict) -> AsyncGenerator[dict, None]:
    """
    Full debrief pipeline. Yields SSE-ready progress dicts.
    Updates session['result'] on completion.
    """
    start_time = time.time()

    # ── Step 1: Ingest ─────────────────────────────────────────────────────────
    yield {"progress": 15, "status": "ingesting", "message": "Parsing mission data streams..."}
    await asyncio.sleep(0.2)

    mission_data = ingest_mission_data(session)

    # ── Step 2: Anomaly Detection ──────────────────────────────────────────────
    yield {"progress": 35, "status": "analyzing", "message": "Running anomaly detection on telemetry..."}
    await asyncio.sleep(0.2)

    anomalies = detect_anomalies(mission_data.telemetry_df, mission_data.events)

    # ── Step 3: Vision Analysis ────────────────────────────────────────────────
    yield {"progress": 55, "status": "analyzing", "message": "Analyzing video frames with AI vision..."}
    await asyncio.sleep(0.2)

    if mission_data.frames:
        context = f"Mission: {mission_data.mission_name} | Platform: {mission_data.platform}"
        mission_data.frames = await analyze_frames(mission_data.frames, context)

    # ── Step 4: Generate Debrief ───────────────────────────────────────────────
    yield {"progress": 75, "status": "generating", "message": "Synthesizing debrief with AI..."}
    await asyncio.sleep(0.2)

    if OPENAI_API_KEY:
        result = await _generate_with_openai(session_id, mission_data, anomalies)
    else:
        result = _generate_rule_based(session_id, mission_data, anomalies)

    # ── Step 5: Export PDF ─────────────────────────────────────────────────────
    yield {"progress": 90, "status": "exporting", "message": "Generating PDF report..."}
    await asyncio.sleep(0.2)

    try:
        from backend.core.export import export_pdf
        pdf_path = f"output/pdfs/{session_id}.pdf"
        await export_pdf(result, pdf_path)
        log.info("PDF exported", path=pdf_path)
    except Exception as e:
        log.warning("PDF export failed (non-fatal)", error=str(e))

    # ── Complete ───────────────────────────────────────────────────────────────
    elapsed = time.time() - start_time
    result.processing_time_seconds = round(elapsed, 2)

    session["result"] = result
    yield {
        "progress": 100,
        "status": "complete",
        "message": f"Debrief complete in {elapsed:.1f}s — {len(anomalies)} anomalies detected",
    }


async def _generate_with_openai(
    session_id: str,
    data: MissionData,
    anomalies: list[AnomalyEvent],
) -> DebriefResult:
    """Generate debrief using OpenAI gpt-4o-mini."""
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=OPENAI_API_KEY)

        # Build context for LLM
        anomaly_summary = "\n".join(
            f"- [{a.severity.upper()}] {a.timestamp}: {a.description}"
            for a in anomalies[:20]
        )

        event_summary = "\n".join(
            f"- {e['timestamp']}: [{e['severity'].upper()}] {e['message']}"
            for e in data.events[:30]
        )

        frame_summary = "\n".join(
            f"- {f['timestamp']}: {f.get('description', 'N/A')}"
            for f in data.frames[:15]
        )

        prompt = f"""You are a professional UAV mission debrief analyst. Analyze the following mission data and generate a structured debrief.

MISSION: {data.mission_name}
PLATFORM: {data.platform}
DURATION: {data.duration_seconds // 60} minutes {data.duration_seconds % 60} seconds

TELEMETRY ANOMALIES:
{anomaly_summary or "No anomalies detected"}

EVENT LOG:
{event_summary or "No events logged"}

FRAME ANALYSIS:
{frame_summary or "No video frames analyzed"}

Generate a structured JSON debrief with EXACTLY this format:
{{
  "summary": "2-3 sentence mission summary",
  "timeline": [
    {{"timestamp": "HH:MM:SS", "event": "description", "severity": "info|warning|critical"}}
  ],
  "decision_points": [
    {{"timestamp": "HH:MM:SS", "situation": "what happened", "action_taken": "what was done"}}
  ],
  "assessment": {{
    "went_well": ["item1", "item2"],
    "watch_points": ["item1", "item2"],
    "overall_rating": "green|amber|red"
  }}
}}

Be concise, professional, and specific. Use the actual timestamps from the data."""

        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            response_format={"type": "json_object"},
            max_tokens=2000,
        )

        text = response.choices[0].message.content or "{}"
        ai_data = json.loads(text)

        # Parse AI response into schema
        timeline = [TimelineEvent(**t) for t in ai_data.get("timeline", [])]
        decision_points = [DecisionPoint(**d) for d in ai_data.get("decision_points", [])]
        assessment_data = ai_data.get("assessment", {})
        assessment = Assessment(
            went_well=assessment_data.get("went_well", []),
            watch_points=assessment_data.get("watch_points", []),
            overall_rating=assessment_data.get("overall_rating", "green"),
        )

        # Add events to timeline
        for evt in data.events:
            if evt["severity"] in ("warning", "critical"):
                timeline.append(TimelineEvent(
                    timestamp=_hms(evt.get("elapsed_seconds", 0)),
                    event=evt["message"],
                    severity=evt["severity"],
                ))

        timeline.sort(key=lambda t: t.timestamp)

        # Interesting moments from frames
        interesting = [
            InterestingMoment(
                timestamp=f.get("timestamp", ""),
                frame_description=f.get("description", ""),
                reason="Flagged by AI vision analysis",
            )
            for f in get_interesting_moments(data.frames)
        ]

        return DebriefResult(
            session_id=session_id,
            mission_name=data.mission_name,
            platform=data.platform,
            duration_seconds=data.duration_seconds,
            generated_at=datetime.now(timezone.utc).isoformat(),
            summary=ai_data.get("summary", "Mission completed."),
            timeline=timeline,
            anomalies=anomalies,
            decision_points=decision_points,
            assessment=assessment,
            interesting_moments=interesting,
            processing_time_seconds=0,
            ai_powered=True,
            total_frames_analyzed=len(data.frames),
            total_anomalies=len(anomalies),
        )

    except Exception as e:
        log.warning("OpenAI debrief failed; falling back to rule-based", error=str(e))
        return _generate_rule_based(session_id, data, anomalies)


def _generate_rule_based(
    session_id: str,
    data: MissionData,
    anomalies: list[AnomalyEvent],
) -> DebriefResult:
    """
    Generate a debrief without any API calls.
    Uses heuristics, templates, and structured data.
    """
    mission_name = data.mission_name
    platform = data.platform
    duration_min = data.duration_seconds // 60
    duration_sec = data.duration_seconds % 60
    n_anomalies = len(anomalies)
    n_critical = sum(1 for a in anomalies if a.severity == "critical")
    n_warning = sum(1 for a in anomalies if a.severity == "warning")

    # ── Summary ────────────────────────────────────────────────────────────────
    if n_critical > 0:
        summary = (
            f"{platform} completed {mission_name} in {duration_min}m{duration_sec:02d}s. "
            f"{n_critical} critical anomaly(s) and {n_warning} warning(s) detected during flight. "
            f"Immediate review of flagged items is recommended."
        )
        rating = "red"
    elif n_warning > 0:
        summary = (
            f"{platform} completed {mission_name} in {duration_min}m{duration_sec:02d}s. "
            f"Mission accomplished with {n_warning} warning-level anomaly(s). "
            f"Review flagged items before next deployment."
        )
        rating = "amber"
    else:
        summary = (
            f"{platform} completed {mission_name} in {duration_min}m{duration_sec:02d}s. "
            f"No anomalies detected. All telemetry within normal parameters. "
            f"Mission rated nominal."
        )
        rating = "green"

    # ── Timeline ───────────────────────────────────────────────────────────────
    timeline: list[TimelineEvent] = []

    # Add mission start
    timeline.append(TimelineEvent(timestamp="00:00:00", event=f"{platform} launched — {mission_name} commenced", severity="info"))

    # Add events from log
    for evt in data.events:
        timeline.append(TimelineEvent(
            timestamp=_hms(evt.get("elapsed_seconds", 0)),
            event=evt.get("message", evt.get("type", "Event")),
            severity=evt.get("severity", "info"),
        ))

    # Add anomaly-derived timeline entries
    for anomaly in anomalies:
        timeline.append(TimelineEvent(
            timestamp=anomaly.timestamp,
            event=f"⚠ {anomaly.description}",
            severity=anomaly.severity,
        ))

    # Add mission end
    timeline.append(TimelineEvent(
        timestamp=_hms(data.duration_seconds),
        event="Mission complete — landing successful",
        severity="info",
    ))

    # Deduplicate and sort
    seen_ts = set()
    unique_timeline = []
    for t in sorted(timeline, key=lambda x: x.timestamp):
        key = f"{t.timestamp}_{t.event[:30]}"
        if key not in seen_ts:
            seen_ts.add(key)
            unique_timeline.append(t)

    # ── Decision Points ────────────────────────────────────────────────────────
    decision_points: list[DecisionPoint] = []

    # Extract decision points from critical/warning events
    for evt in data.events:
        if evt.get("severity") in ("critical", "warning"):
            action = evt.get("data", {}).get("action", "Operator notified; system adjusted automatically")
            decision_points.append(DecisionPoint(
                timestamp=_hms(evt.get("elapsed_seconds", 0)),
                situation=evt.get("message", "Anomalous condition detected"),
                action_taken=action,
            ))

    for anomaly in anomalies:
        if anomaly.severity == "critical" and not any(
            dp.timestamp == anomaly.timestamp for dp in decision_points
        ):
            decision_points.append(DecisionPoint(
                timestamp=anomaly.timestamp,
                situation=anomaly.description,
                action_taken="System flagged for operator review; mission continued under protocol",
            ))

    decision_points = decision_points[:5]  # Top 5

    # ── Assessment ────────────────────────────────────────────────────────────
    went_well = []
    watch_points = []

    if data.duration_seconds > 0:
        went_well.append(f"Full mission duration completed ({duration_min}m {duration_sec:02d}s)")

    if n_anomalies == 0:
        went_well.append("All telemetry channels within normal parameters")
        went_well.append("No anomalies detected throughout mission")
    else:
        went_well.append("Mission completed despite anomaly conditions")

    # Check telemetry for positive indicators
    if data.telemetry_df is not None and not data.telemetry_df.empty:
        if "battery_pct" in data.telemetry_df.columns:
            final_battery = data.telemetry_df["battery_pct"].iloc[-1]
            if final_battery > 25:
                went_well.append(f"Battery margin maintained (landed at {final_battery:.0f}%)")
            else:
                watch_points.append(f"Low battery at landing ({final_battery:.0f}%) — consider shorter mission profile")

        if "altitude_m" in data.telemetry_df.columns:
            alt_std = data.telemetry_df["altitude_m"].std()
            if alt_std < 5:
                went_well.append("Altitude held steady throughout mission")

    for anomaly in anomalies[:3]:
        watch_points.append(f"{anomaly.description} ({anomaly.channel})")

    if not went_well:
        went_well = ["Mission executed successfully", "Data recorded for review"]
    if not watch_points:
        watch_points = ["Continue standard maintenance schedule", "Review telemetry data as part of routine ops"]

    assessment = Assessment(
        went_well=went_well[:4],
        watch_points=watch_points[:4],
        overall_rating=rating,
    )

    # ── Interesting Moments ────────────────────────────────────────────────────
    interesting: list[InterestingMoment] = []
    for frame in get_interesting_moments(data.frames):
        interesting.append(InterestingMoment(
            timestamp=frame.get("timestamp", ""),
            frame_description=frame.get("description", ""),
            reason="Flagged by frame analysis — visual anomaly detected",
        ))

    return DebriefResult(
        session_id=session_id,
        mission_name=mission_name,
        platform=platform,
        duration_seconds=data.duration_seconds,
        generated_at=datetime.now(timezone.utc).isoformat(),
        summary=summary,
        timeline=unique_timeline,
        anomalies=anomalies,
        decision_points=decision_points,
        assessment=assessment,
        interesting_moments=interesting,
        processing_time_seconds=0,
        ai_powered=False,
        total_frames_analyzed=len(data.frames),
        total_anomalies=n_anomalies,
    )


def _hms(seconds: float) -> str:
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"
