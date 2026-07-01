"""
Mission Debrief AI — Multi-Stream Data Ingestion Pipeline

Handles:
- Video: Frame extraction (every N seconds + motion-triggered)
- Telemetry: JSON → pandas DataFrame time-series
- Sensor logs: JSON event list → structured events
"""

from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any, List, Optional

import numpy as np
import pandas as pd
import structlog

log = structlog.get_logger(__name__)

FRAME_INTERVAL = int(os.getenv("FRAME_INTERVAL", "15"))
MAX_FRAMES = int(os.getenv("MAX_FRAMES", "20"))


class MissionData:
    """Container for all parsed mission data."""

    def __init__(self):
        self.telemetry_df: Optional[pd.DataFrame] = None
        self.events: list[dict] = []
        self.video_path: Optional[str] = None
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


# ── Column name normalization maps ──────────────────────────────────────────
# Maps common drone-export column names → our internal schema names.
_COL_ALIASES = {
    # DJI Flight Record CSV
    "OSD.latitude": "latitude",
    "OSD.longitude": "longitude",
    "OSD.altitude [m]": "altitude_m",
    "OSD.height [m]": "altitude_m",
    "OSD.speed [m/s]": "speed_ms",
    "OSD.hSpeed [m/s]": "speed_ms",
    "OSD.vSpeed [m/s]": "vertical_speed_ms",
    "OSD.pitch": "pitch_deg",
    "OSD.roll": "roll_deg",
    "OSD.yaw": "heading_deg",
    "OSD.heading": "heading_deg",
    "BATTERY.chargeLevel [%]": "battery_pct",
    "BATTERY.temperature [°C]": "temperature_c",
    "BATTERY.temperature [oC]": "temperature_c",
    "OSD.flycState": "flight_state",
    "OSD.flyTime [s]": "elapsed_seconds",
    # ArduPilot / MAVLink CSV
    "Alt": "altitude_m",
    "RelAlt": "altitude_m",
    "Spd": "speed_ms",
    "GSpd": "speed_ms",
    "Bat": "battery_pct",
    "Hdg": "heading_deg",
    "Lat": "latitude",
    "Lng": "longitude",
    "Lon": "longitude",
    # Generic / Autel / Skydio
    "lat": "latitude",
    "lng": "longitude",
    "lon": "longitude",
    "alt": "altitude_m",
    "altitude": "altitude_m",
    "speed": "speed_ms",
    "battery": "battery_pct",
    "heading": "heading_deg",
    "time": "timestamp",
    "elapsed": "elapsed_seconds",
}


def _parse_telemetry(path: str) -> pd.DataFrame:
    """
    Parse telemetry file into a normalized pandas DataFrame.

    Supports:
    - JSON  — { "records": [...] } or [ {...}, ... ] or flat {}
    - CSV   — DJI FlightRecord, ArduPilot, Autel, Skydio, or generic
              (column aliases normalised automatically)
    """
    suffix = Path(path).suffix.lower()

    if suffix == ".csv":
        df = _parse_telemetry_csv(path)
    else:
        df = _parse_telemetry_json(path)

    # Normalize timestamp
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")

    # Derive elapsed_seconds from timestamp if not present
    if "elapsed_seconds" not in df.columns and "timestamp" in df.columns:
        t0 = df["timestamp"].dropna().iloc[0] if not df["timestamp"].dropna().empty else None
        if t0 is not None:
            df["elapsed_seconds"] = (df["timestamp"] - t0).dt.total_seconds()

    # Ensure numeric telemetry columns
    numeric_cols = [
        "altitude_m", "speed_ms", "battery_pct", "latitude", "longitude",
        "heading_deg", "vertical_speed_ms", "temperature_c",
        "pitch_deg", "roll_deg", "elapsed_seconds",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    sort_col = "elapsed_seconds" if "elapsed_seconds" in df.columns else df.columns[0]
    return df.sort_values(sort_col).reset_index(drop=True)


def _parse_telemetry_json(path: str) -> pd.DataFrame:
    """Parse JSON telemetry — supports list, {records:[]}, {telemetry:[]}, or flat dict."""
    with open(path) as f:
        raw = json.load(f)

    if isinstance(raw, list):
        records = raw
    elif "records" in raw:
        records = raw["records"]
    elif "telemetry" in raw:
        records = raw["telemetry"]
    else:
        records = [raw]

    return pd.DataFrame(records)


def _parse_telemetry_csv(path: str) -> pd.DataFrame:
    """
    Parse CSV telemetry with automatic column alias normalization.

    Handles:
    - DJI FlightRecord CSV (exported via AirData / DJI Assistant)
    - ArduPilot / Mission Planner tlog CSV
    - Generic drone CSV with common column names
    - BOM (UTF-8 with BOM) encoding used by some flight controllers
    """
    # Try different encodings
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            # Skip comment/metadata lines that some tools prepend (lines starting with #)
            df = pd.read_csv(path, encoding=enc, comment="#", low_memory=False)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"Cannot decode CSV: {path}")

    # Drop fully-empty columns
    df = df.dropna(axis=1, how="all")

    # Normalize column names via alias map
    rename_map = {}
    for col in df.columns:
        col_stripped = col.strip()
        if col_stripped in _COL_ALIASES:
            rename_map[col] = _COL_ALIASES[col_stripped]
        elif col_stripped.lower() in {v.lower(): v for v in _COL_ALIASES.values()}:
            # Already a canonical name — just strip whitespace
            rename_map[col] = col_stripped
    df = df.rename(columns=rename_map)

    # DJI specific: "CUSTOM.updateTime" → timestamp
    if "CUSTOM.updateTime" in df.columns and "timestamp" not in df.columns:
        df = df.rename(columns={"CUSTOM.updateTime": "timestamp"})

    # If there's a generic first-column that looks like time (ms/s since epoch)
    if "elapsed_seconds" not in df.columns and "timestamp" not in df.columns:
        first_col = df.columns[0]
        sample = pd.to_numeric(df[first_col].head(5), errors="coerce")
        if not sample.isna().all():
            # Heuristic: values < 100000 → seconds; > 100000 → milliseconds
            if sample.max() > 100_000:
                df["elapsed_seconds"] = pd.to_numeric(df[first_col], errors="coerce") / 1000
            else:
                df["elapsed_seconds"] = pd.to_numeric(df[first_col], errors="coerce")

    log.info("CSV telemetry parsed", rows=len(df), columns=list(df.columns)[:10])
    return df


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
    Extract key frames from video.
    Primary: ffmpeg (subprocess) — handles all drone footage formats robustly.
    Fallback: OpenCV — used if ffmpeg binary is not on PATH.
    """
    output_dir = Path("output/frames") / session_id
    output_dir.mkdir(parents=True, exist_ok=True)

    # Try ffmpeg first
    frames = _extract_frames_ffmpeg(video_path, output_dir)
    if frames:
        return frames

    # Fallback to OpenCV
    return _extract_frames_opencv(video_path, output_dir)


def _extract_frames_ffmpeg(video_path: str, output_dir: Path) -> list[dict]:
    """
    Extract frames using ffmpeg subprocess.
    Outputs one JPEG per FRAME_INTERVAL seconds, up to MAX_FRAMES.
    Handles H.264/H.265, DJI SRT-embedded MP4, GoPro, and most drone formats.
    """
    import shutil
    import subprocess

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        log.warning("ffmpeg not found; will try OpenCV")
        return []

    try:
        # Get video duration via ffprobe
        probe_cmd = [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            video_path,
        ]
        probe = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=15)
        probe_data = json.loads(probe.stdout or "{}")

        duration = 0.0
        for stream in probe_data.get("streams", []):
            if stream.get("codec_type") == "video":
                duration = float(stream.get("duration", 0))
                break

        if duration == 0:
            # Try format-level duration
            fmt_cmd = [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                video_path,
            ]
            fmt_result = subprocess.run(fmt_cmd, capture_output=True, text=True, timeout=15)
            fmt_data = json.loads(fmt_result.stdout or "{}")
            duration = float(fmt_data.get("format", {}).get("duration", 0))

        if duration == 0:
            log.warning("ffprobe could not determine video duration")
            return []

        # Calculate timestamps to extract.
        # Adapt interval for short videos so we always get at least 5 frames
        # (or as many as possible for very short clips), up to MAX_FRAMES.
        effective_interval = min(FRAME_INTERVAL, max(1, duration / min(MAX_FRAMES, 5)))
        n_frames = min(MAX_FRAMES, max(1, int(duration / effective_interval)))
        timestamps = [i * (duration / n_frames) for i in range(n_frames)]

        frames = []
        for idx, t in enumerate(timestamps):
            out_path = output_dir / f"frame_{idx:04d}_{int(t):05d}s.jpg"
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(t),
                "-i", video_path,
                "-frames:v", "1",
                "-q:v", "3",          # JPEG quality 2–5 is good
                "-vf", "scale=1280:-2",  # Resize to max 1280px wide
                str(out_path),
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=30)
            if result.returncode == 0 and out_path.exists():
                frames.append({
                    "frame_index": idx,
                    "elapsed_seconds": t,
                    "timestamp": _seconds_to_hms(t),
                    "path": str(out_path),
                    "description": None,
                    "is_interesting": False,
                })
            else:
                log.warning("ffmpeg frame extraction failed", timestamp=t, stderr=result.stderr.decode()[:200])

        log.info("Video frames extracted via ffmpeg", count=len(frames), duration=duration)
        return frames

    except subprocess.TimeoutExpired:
        log.warning("ffmpeg timed out during frame extraction")
        return []
    except Exception as e:
        log.warning("ffmpeg frame extraction error", error=str(e))
        return []


def _extract_frames_opencv(video_path: str, output_dir: Path) -> list[dict]:
    """Fallback: extract frames using OpenCV."""
    frames = []
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
                "is_interesting": False,
            })

            frame_idx += frame_step
            extracted += 1

        cap.release()
        log.info("Video frames extracted via OpenCV", count=len(frames), duration=duration)

    except ImportError:
        log.warning("OpenCV not available — no video frames extracted")
    except Exception as e:
        log.warning("OpenCV frame extraction failed", error=str(e))

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
