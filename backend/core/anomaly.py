"""
Mission Debrief AI — Telemetry Anomaly Detection

Two layers:
1. Statistical: Z-score anomaly detection on continuous channels
2. Rule-based: Threshold/event detection (GPS loss, low battery, error events)
"""

import os
from typing import Any

import numpy as np
import pandas as pd
import structlog

from backend.api.models import AnomalyEvent

log = structlog.get_logger(__name__)

Z_THRESHOLD = float(os.getenv("ANOMALY_Z_THRESHOLD", "2.5"))

# Rule-based thresholds
RULES = {
    "battery_critical": {"channel": "battery_pct", "operator": "lt", "value": 20, "severity": "critical"},
    "battery_low": {"channel": "battery_pct", "operator": "lt", "value": 30, "severity": "warning"},
    "altitude_floor": {"channel": "altitude_m", "operator": "lt", "value": 5, "severity": "critical"},
    "speed_limit": {"channel": "speed_ms", "operator": "gt", "value": 20, "severity": "warning"},
    "temp_high": {"channel": "temperature_c", "operator": "gt", "value": 80, "severity": "warning"},
}

# Channels to run Z-score detection on
ZSCORE_CHANNELS = ["altitude_m", "speed_ms", "battery_pct", "vertical_speed_ms"]


def detect_anomalies(
    telemetry_df: pd.DataFrame | None,
    events: list[dict],
) -> list[AnomalyEvent]:
    """
    Run full anomaly detection pipeline.
    Returns a sorted list of AnomalyEvent objects.
    """
    anomalies: list[AnomalyEvent] = []

    if telemetry_df is not None and not telemetry_df.empty:
        # Statistical anomalies
        anomalies.extend(_zscore_detection(telemetry_df))
        # Rule-based threshold violations
        anomalies.extend(_rule_based_detection(telemetry_df))

    # Event log anomalies
    anomalies.extend(_event_anomalies(events))

    # Deduplicate (same channel, same time bucket within 30s)
    anomalies = _deduplicate(anomalies)

    # Sort by timestamp
    anomalies.sort(key=lambda a: a.timestamp)

    log.info("Anomaly detection complete", total=len(anomalies))
    return anomalies


def _zscore_detection(df: pd.DataFrame) -> list[AnomalyEvent]:
    """
    Detect anomalies using Z-score on telemetry channels.
    Flags readings more than Z_THRESHOLD standard deviations from the mean.
    """
    anomalies = []
    has_elapsed = "elapsed_seconds" in df.columns

    for channel in ZSCORE_CHANNELS:
        if channel not in df.columns:
            continue

        series = df[channel].dropna()
        if len(series) < 10:  # Not enough data
            continue

        mean = series.mean()
        std = series.std()
        if std == 0:
            continue

        z_scores = np.abs((series - mean) / std)
        flagged = df.loc[z_scores[z_scores > Z_THRESHOLD].index]

        # Group nearby anomalies (within 60s of each other)
        last_flagged_t = -999
        for _, row in flagged.iterrows():
            t = row.get("elapsed_seconds", 0) if has_elapsed else 0
            if t - last_flagged_t < 60:
                continue  # Skip clustered anomalies
            last_flagged_t = t

            value = row[channel]
            z = abs((value - mean) / std) if std > 0 else 0
            severity = "critical" if z > Z_THRESHOLD * 1.5 else "warning"

            anomalies.append(AnomalyEvent(
                timestamp=_format_timestamp(row, has_elapsed),
                type=f"zscore_{channel}",
                description=f"{_channel_label(channel)} anomaly: {value:.1f} (mean {mean:.1f}, z={z:.1f}σ)",
                severity=severity,
                channel=channel,
                value=float(value),
                threshold=float(mean + Z_THRESHOLD * std),
            ))

    return anomalies


def _rule_based_detection(df: pd.DataFrame) -> list[AnomalyEvent]:
    """Apply rule-based threshold checks to telemetry."""
    anomalies = []
    has_elapsed = "elapsed_seconds" in df.columns
    triggered_rules: set[str] = set()

    for rule_name, rule in RULES.items():
        channel = rule["channel"]
        if channel not in df.columns:
            continue

        op = rule["operator"]
        threshold = rule["value"]
        severity = rule["severity"]

        if op == "lt":
            mask = df[channel] < threshold
        elif op == "gt":
            mask = df[channel] > threshold
        else:
            continue

        flagged = df[mask]
        if flagged.empty:
            continue

        # Report first occurrence
        first = flagged.iloc[0]
        rule_key = f"{rule_name}_{int(first.get('elapsed_seconds', 0) // 60)}"
        if rule_key in triggered_rules:
            continue
        triggered_rules.add(rule_key)

        val = first[channel]
        anomalies.append(AnomalyEvent(
            timestamp=_format_timestamp(first, has_elapsed),
            type=rule_name,
            description=f"{_channel_label(channel)} {op} {threshold}: observed {val:.1f}",
            severity=severity,
            channel=channel,
            value=float(val),
            threshold=float(threshold),
        ))

    return anomalies


def _event_anomalies(events: list[dict]) -> list[AnomalyEvent]:
    """Detect anomalies from event log entries."""
    anomalies = []

    error_keywords = ["error", "fail", "critical", "lost", "warning", "anomaly", "alert", "fault"]

    for evt in events:
        severity = evt.get("severity", "info")
        msg = evt.get("message", "").lower()
        evt_type = evt.get("type", "").lower()

        # Flag critical/warning events and events with error keywords
        is_error = any(kw in msg or kw in evt_type for kw in error_keywords)
        if severity in ("critical", "warning") or is_error:
            anomalies.append(AnomalyEvent(
                timestamp=_hms_from_seconds(evt.get("elapsed_seconds", 0)),
                type=f"event_{evt.get('type', 'unknown')}",
                description=evt.get("message", str(evt)),
                severity=severity if severity in ("info", "warning", "critical") else "warning",
                channel="event_log",
                value=None,
                threshold=None,
            ))

    return anomalies


def _deduplicate(anomalies: list[AnomalyEvent]) -> list[AnomalyEvent]:
    """Remove near-duplicate anomalies (same channel, close in time)."""
    seen: set[str] = set()
    result = []
    for a in anomalies:
        key = f"{a.channel}_{a.type}"
        if key not in seen:
            seen.add(key)
            result.append(a)
    return result


def _format_timestamp(row: pd.Series, has_elapsed: bool) -> str:
    if has_elapsed:
        return _hms_from_seconds(row.get("elapsed_seconds", 0))
    elif "timestamp" in row and pd.notna(row["timestamp"]):
        return str(row["timestamp"])
    return "00:00:00"


def _hms_from_seconds(seconds: float) -> str:
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _channel_label(channel: str) -> str:
    labels = {
        "altitude_m": "Altitude",
        "speed_ms": "Speed",
        "battery_pct": "Battery",
        "vertical_speed_ms": "Vertical Speed",
        "temperature_c": "Temperature",
    }
    return labels.get(channel, channel.replace("_", " ").title())
