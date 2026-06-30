"""
Mission Debrief AI — Multi-Stream Data Ingestion Pipeline

Handles:
- Video: Frame extraction (every N seconds + motion-triggered)
- Telemetry: JSON → pandas DataFrame time-series
- Sensor logs: JSON event list → structured events
"""

import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import structlog

log = structlog.get_logger(__name__)

FRAME_INTERVAL = int(os.getenv("FRAME_INTERVAL", "15"))
MAX_FRAMES = int(os.getenv("MAX_FRAMES", "20"))


class MissionData:
    """Container for all parsed mission data."""

    def __init__(self):
        self.telemetry_df: pd.DataFrame | None = None
        self.events: list[dict] = []
        self.video_path: str | None = None
        self.frames: list[dict] = []  # [{timestamp, path, description}]
        self.duration_seconds: int = 0
        self.start_time: str = ""
        self.end_time: str = ""
        self.mission_name: str = ""
        self.platform: str = ""


def ingest_mission_data(session: dict) -> MissionData:
    """
    Parse all available mission data from session files.
    Returns a MissionData object with everything loaded.
    """
    data = MissionData()
    data.mission_name = session.get("mission_name", "Mission")
    data.platform = session.get("platform", "Unknown UAV")
    files = session.get("files", {})

    # Parse telemetry
    if "telemetry" in files:
        try:
            data.telemetry_df = _parse_telemetry(files["telemetry"])
            if data.telemetry_df is not None and not data.telemetry_df.empty:
                data.duration_seconds = int(
                    (data.telemetry_df["timestamp"].max() - data.telemetry_df["timestamp"].min()).total_seconds()
                    if pd.api.types.is_datetime64_any_dtype(data.telemetry_df["timestamp"])
                    else data.telemetry_df["elapsed_seconds"].max()
                )
                log.info("Telemetry parsed", rows=len(data.telemetry_df), duration=data.duration_seconds)
        except Exception as e:
            log.warning("Telemetry parse failed", error=str(e))

    # Parse sensor/event log
    if "sensor_log" in files:
        try:
            data.events = _parse_sensor_log(files["sensor_log"])
            log.info("Events parsed", count=len(data.events))
        except Exception as e:
            log.warning("Sensor log parse failed", error=str(e))

    # Extract video frames
    if "video" in files:
        try:
            data.video_path = files["video"]
            data.frames = _extract_video_frames(files["video"], session["session_id"])
            log.info("Video frames extracted", count=len(data.frames))
        except Exception as e:
            log.warning("Video frame extraction failed", error=str(e))

    return data


def _parse_telemetry(path: str) -> pd.DataFrame:
    """
    Parse telemetry JSON into a pandas DataFrame.

    Expected format:
    {
        "records": [
            {
                "timestamp": "2024-01-15T10:00:00Z",
                "elapsed_seconds": 0,
                "latitude": 51.5,
                "longitude": -0.1,
                "altitude_m": 50.0,
                "speed_ms": 5.0,
                "battery_pct": 100,
                "heading_deg": 90,
                ...
            }
        ]
    }
    """
    with open(path) as f:
        raw = json.load(f)

    # Support multiple formats
    if isinstance(raw, list):
        records = raw
    elif "records" in raw:
        records = raw["records"]
    elif "telemetry" in raw:
        records = raw["telemetry"]
    else:
        records = [raw]

    df = pd.DataFrame(records)

    # Normalize timestamp
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")

    # Add elapsed seconds if missing
    if "elapsed_seconds" not in df.columns and "timestamp" in df.columns:
        df["elapsed_seconds"] = (df["timestamp"] - df["timestamp"].iloc[0]).dt.total_seconds()

    # Ensure numeric columns
    numeric_cols = ["altitude_m", "speed_ms", "battery_pct", "latitude", "longitude",
                    "heading_deg", "vertical_speed_ms", "temperature_c"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df.sort_values("elapsed_seconds" if "elapsed_seconds" in df.columns else df.columns[0])


def _parse_sensor_log(path: str) -> list[dict]:
    """
    Parse sensor/event log JSON.

    Expected format:
    {
        "events": [
            {
                "timestamp": "2024-01-15T10:05:30Z",
                "elapsed_seconds": 330,
                "type": "panel_scan_start",
                "severity": "info",
                "message": "Beginning panel scan row 1",
                "data": {}
            }
        ]
    }
    """
    with open(path) as f:
        raw = json.load(f)

    if isinstance(raw, list):
        events = raw
    elif "events" in raw:
        events = raw["events"]
    elif "logs" in raw:
        events = raw["logs"]
    else:
        events = [raw]

    # Normalize
    normalized = []
    for evt in events:
        normalized.append({
            "timestamp": evt.get("timestamp", ""),
            "elapsed_seconds": float(evt.get("elapsed_seconds", 0)),
            "type": evt.get("type", "event"),
            "severity": evt.get("severity", "info"),
            "message": evt.get("message", str(evt)),
            "data": evt.get("data", {}),
        })

    return sorted(normalized, key=lambda x: x["elapsed_seconds"])


def _extract_video_frames(video_path: str, session_id: str) -> list[dict]:
    """
    Extract key frames from video using OpenCV.
    Falls back to empty list if cv2 not available.
    """
    frames = []
    output_dir = Path("output/frames") / session_id
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        import cv2

        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps

        frame_step = int(fps * FRAME_INTERVAL)
        frame_idx = 0
        extracted = 0

        while cap.isOpened() and extracted < MAX_FRAMES:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if not ret:
                break

            timestamp_sec = frame_idx / fps
            out_path = output_dir / f"frame_{extracted:04d}_{int(timestamp_sec):05d}s.jpg"
            cv2.imwrite(str(out_path), frame)

            frames.append({
                "frame_index": extracted,
                "elapsed_seconds": timestamp_sec,
                "timestamp": _seconds_to_hms(timestamp_sec),
                "path": str(out_path),
                "description": None,
            })

            frame_idx += frame_step
            extracted += 1

        cap.release()
        log.info("Video frames extracted via OpenCV", count=len(frames), duration=duration)

    except ImportError:
        log.warning("OpenCV not available; skipping video frame extraction")
    except Exception as e:
        log.warning("Video frame extraction failed", error=str(e))

    return frames


def _seconds_to_hms(seconds: float) -> str:
    """Convert seconds to HH:MM:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def parse_telemetry_from_dict(records: list[dict]) -> pd.DataFrame:
    """Parse telemetry from an already-loaded list of dicts (for demo mode)."""
    df = pd.DataFrame(records)
    if "elapsed_seconds" in df.columns:
        df["elapsed_seconds"] = pd.to_numeric(df["elapsed_seconds"], errors="coerce")
    numeric_cols = ["altitude_m", "speed_ms", "battery_pct", "latitude", "longitude",
                    "heading_deg", "vertical_speed_ms"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.sort_values("elapsed_seconds")
