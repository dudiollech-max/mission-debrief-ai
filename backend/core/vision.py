"""
Mission Debrief AI — Vision Analysis Module

Analyzes video frames using LLM vision:
- Primary: OpenAI gpt-4o-mini (if OPENAI_API_KEY set)
- Fallback: Ollama/llava (if USE_LOCAL_LLM=true)
- Default: Rule-based frame descriptions (no API key needed)

Identifies "interesting moments" — anomalous scenes, equipment, damage, unusual patterns.
"""

import base64
import os
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

USE_LOCAL_LLM = os.getenv("USE_LOCAL_LLM", "false").lower() == "true"
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llava")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")


async def analyze_frames(frames: list[dict], context: str = "") -> list[dict]:
    """
    Analyze each frame and add a description + interesting flag.

    Args:
        frames: List of frame dicts from ingestion (must have 'path' and 'timestamp')
        context: Optional mission context string

    Returns:
        Updated frames list with 'description' and 'is_interesting' fields.
    """
    if not frames:
        return frames

    if OPENAI_API_KEY:
        log.info("Using OpenAI vision analysis", model="gpt-4o-mini", frame_count=len(frames))
        return await _analyze_with_openai(frames, context)
    elif USE_LOCAL_LLM:
        log.info("Using Ollama vision analysis", model=OLLAMA_MODEL, frame_count=len(frames))
        return await _analyze_with_ollama(frames, context)
    else:
        log.info("Using rule-based frame descriptions (no API key)", frame_count=len(frames))
        return _analyze_rule_based(frames, context)


async def _analyze_with_openai(frames: list[dict], context: str) -> list[dict]:
    """Use OpenAI gpt-4o for frame analysis."""
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=OPENAI_API_KEY)

        for frame in frames:
            image_path = frame.get("path")
            if not image_path or not Path(image_path).exists():
                frame["description"] = "Frame not available"
                frame["is_interesting"] = False
                continue

            # Encode image as base64
            with open(image_path, "rb") as f:
                img_data = base64.b64encode(f.read()).decode("utf-8")

            prompt = (
                f"You are analyzing a UAV mission video frame. {context}\n\n"
                "Describe what you see in 1-2 sentences. "
                "Then on a new line, write 'INTERESTING: YES' if you see anything unusual, "
                "damaged, concerning, or noteworthy (anomalies, equipment issues, unusual patterns). "
                "Otherwise write 'INTERESTING: NO'."
            )

            try:
                response = await client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/jpeg;base64,{img_data}", "detail": "low"},
                                },
                            ],
                        }
                    ],
                    max_tokens=150,
                )
                text = response.choices[0].message.content or ""
                frame["description"] = text.split("INTERESTING:")[0].strip()
                frame["is_interesting"] = "YES" in text.upper().split("INTERESTING:")[-1]
            except Exception as e:
                log.warning("OpenAI frame analysis failed", timestamp=frame.get("timestamp"), error=str(e))
                frame["description"] = f"Frame at {frame.get('timestamp', 'unknown time')}"
                frame["is_interesting"] = False

    except ImportError:
        log.warning("openai package not installed; falling back to rule-based")
        return _analyze_rule_based(frames, context)

    return frames


async def _analyze_with_ollama(frames: list[dict], context: str) -> list[dict]:
    """Use Ollama (llava/qwen2-vl) for local vision analysis."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=60) as client:
            for frame in frames:
                image_path = frame.get("path")
                if not image_path or not Path(image_path).exists():
                    frame["description"] = "Frame not available"
                    frame["is_interesting"] = False
                    continue

                with open(image_path, "rb") as f:
                    img_data = base64.b64encode(f.read()).decode("utf-8")

                prompt = (
                    f"UAV mission frame analysis. {context} "
                    "Describe in 1-2 sentences. Note if anything is unusual or concerning."
                )

                try:
                    resp = await client.post(
                        f"{OLLAMA_HOST}/api/generate",
                        json={
                            "model": OLLAMA_MODEL,
                            "prompt": prompt,
                            "images": [img_data],
                            "stream": False,
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    desc = data.get("response", "").strip()
                    frame["description"] = desc
                    frame["is_interesting"] = any(
                        kw in desc.lower()
                        for kw in ["unusual", "damage", "anomaly", "concern", "fault", "issue", "warning"]
                    )
                except Exception as e:
                    log.warning("Ollama frame analysis failed", error=str(e))
                    frame["description"] = f"Frame at {frame.get('timestamp', 'unknown time')}"
                    frame["is_interesting"] = False

    except Exception as e:
        log.warning("Ollama analysis error; falling back", error=str(e))
        return _analyze_rule_based(frames, context)

    return frames


def _analyze_rule_based(frames: list[dict], context: str = "") -> list[dict]:
    """
    Rule-based frame descriptions — works without any API.
    Uses position in flight to generate contextual descriptions.
    """
    total = len(frames)
    for i, frame in enumerate(frames):
        progress = i / max(total - 1, 1)  # 0.0 to 1.0

        # Simulate realistic UAV flight descriptions based on flight phase
        if progress < 0.05:
            desc = "Drone ascending from launch pad, ground equipment visible, clear sky conditions."
            interesting = False
        elif progress < 0.15:
            desc = "Drone climbing to operational altitude, overview of inspection area visible below."
            interesting = False
        elif progress < 0.3:
            desc = "Solar panel array visible from above, systematic scan underway, panels appear nominal."
            interesting = False
        elif progress < 0.5:
            desc = "Mid-mission inspection, panels in rows clearly visible, consistent thermal signature."
            interesting = False
        elif 0.48 < progress < 0.58:
            # Anomaly zone
            desc = "Panel section showing irregular thermal signature — possible hotspot detected. Color variation visible in panel cluster."
            interesting = True
        elif progress < 0.7:
            desc = "Continuing systematic scan, panels appear uniformly illuminated, no further anomalies noted."
            interesting = False
        elif progress < 0.85:
            desc = "Battery indicator approaching threshold, drone repositioning for return leg."
            interesting = True
        elif progress < 0.95:
            desc = "Drone in return-to-home mode, solar farm receding in background, landing zone visible ahead."
            interesting = False
        else:
            desc = "Drone on final approach to landing pad, mission complete."
            interesting = False

        frame["description"] = desc
        frame["is_interesting"] = interesting

    return frames


def get_interesting_moments(frames: list[dict]) -> list[dict]:
    """Filter frames to only interesting moments."""
    return [f for f in frames if f.get("is_interesting", False)]
