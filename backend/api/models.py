"""
Pydantic schemas for Mission Debrief AI API.
"""

from typing import Optional
from pydantic import BaseModel, Field


# ─── Core Debrief Schema ──────────────────────────────────────────────────────

class TimelineEvent(BaseModel):
    timestamp: str = Field(..., description="ISO timestamp or mission-relative time (HH:MM:SS)")
    event: str = Field(..., description="Human-readable event description")
    severity: str = Field(default="info", description="info | warning | critical")


class AnomalyEvent(BaseModel):
    timestamp: str = Field(..., description="When the anomaly occurred")
    type: str = Field(..., description="Anomaly type (e.g. altitude_drop, battery_spike)")
    description: str = Field(..., description="Human-readable anomaly description")
    severity: str = Field(default="warning", description="info | warning | critical")
    channel: str = Field(..., description="Telemetry channel or sensor that triggered")
    value: Optional[float] = Field(None, description="Observed value at anomaly")
    threshold: Optional[float] = Field(None, description="Threshold that was breached")


class DecisionPoint(BaseModel):
    timestamp: str = Field(..., description="When the decision point occurred")
    situation: str = Field(..., description="What situation triggered the decision")
    action_taken: str = Field(..., description="What action was taken by operator or autopilot")


class Assessment(BaseModel):
    went_well: list[str] = Field(default_factory=list, description="Things that went well")
    watch_points: list[str] = Field(default_factory=list, description="Things to watch or improve")
    overall_rating: str = Field(default="green", description="green | amber | red")


class InterestingMoment(BaseModel):
    timestamp: str = Field(..., description="When this moment occurred")
    frame_description: str = Field(..., description="Visual description of the scene")
    reason: str = Field(..., description="Why this moment was flagged as interesting")
    thumbnail_url: Optional[str] = Field(None, description="URL to thumbnail image")


class DebriefResult(BaseModel):
    session_id: str
    mission_name: str
    platform: str = Field(default="Unknown UAV", description="e.g. SolarDrone MK2")
    duration_seconds: int
    generated_at: str = Field(..., description="ISO timestamp when debrief was generated")
    summary: str = Field(..., description="2-3 sentence mission summary")
    timeline: list[TimelineEvent]
    anomalies: list[AnomalyEvent]
    decision_points: list[DecisionPoint]
    assessment: Assessment
    interesting_moments: list[InterestingMoment]
    processing_time_seconds: float
    ai_powered: bool = Field(default=False, description="Whether AI was used for generation")
    total_frames_analyzed: int = Field(default=0)
    total_anomalies: int = Field(default=0)


# ─── Session / Status Schema ──────────────────────────────────────────────────

class SessionStatus(BaseModel):
    session_id: str
    status: str = Field(..., description="pending | ingesting | analyzing | generating | complete | error")
    progress: int = Field(default=0, description="0-100")
    message: str = Field(default="")
    result: Optional[DebriefResult] = None
    error: Optional[str] = None


# ─── Ingest Response ──────────────────────────────────────────────────────────

class IngestResponse(BaseModel):
    session_id: str
    message: str
    has_video: bool
    has_telemetry: bool
    has_sensor_log: bool


# ─── Demo Response ────────────────────────────────────────────────────────────

class DemoResponse(BaseModel):
    session_id: str
    message: str
    demo_type: str = "solar_drone"
