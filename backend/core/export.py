"""
Mission Debrief AI — PDF + JSON Export

Generates a clean, professional PDF debrief using ReportLab.
VisionWave-branded: dark theme, electric blue accents.
"""

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

from backend.api.models import DebriefResult

log = structlog.get_logger(__name__)

# ─── Color Palette (VisionWave dark theme) ────────────────────────────────────
DARK_BG = (0.06, 0.06, 0.10)          # Near-black
DARK_CARD = (0.10, 0.12, 0.18)        # Card background
ELECTRIC_BLUE = (0.12, 0.56, 1.0)     # Electric blue accent
LIGHT_TEXT = (0.95, 0.95, 0.98)       # Near-white text
MUTED_TEXT = (0.55, 0.60, 0.70)       # Muted secondary text
WARNING_AMBER = (1.0, 0.72, 0.0)      # Warning amber
CRITICAL_RED = (1.0, 0.27, 0.27)      # Critical red
SUCCESS_GREEN = (0.14, 0.90, 0.55)    # Success green

RATING_COLORS = {
    "green": SUCCESS_GREEN,
    "amber": WARNING_AMBER,
    "red": CRITICAL_RED,
}

SEVERITY_COLORS = {
    "info": ELECTRIC_BLUE,
    "warning": WARNING_AMBER,
    "critical": CRITICAL_RED,
}


async def export_pdf(result: DebriefResult, output_path: str) -> str:
    """
    Generate a VisionWave-branded PDF debrief report.
    Returns the path to the generated PDF.
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Run in thread to avoid blocking
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _generate_pdf, result, output_path)
    return output_path


def _generate_pdf(result: DebriefResult, output_path: str):
    """Synchronous PDF generation with ReportLab."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm, mm
        from reportlab.platypus import (
            HRFlowable,
            PageBreak,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
        from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

    except ImportError:
        log.error("reportlab not installed — cannot generate PDF")
        return

    W, H = A4
    margin = 2 * cm

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
        title=f"Mission Debrief — {result.mission_name}",
        author="VisionWave AI",
        subject="UAV Mission Debrief Report",
    )

    # ── ReportLab colors ──────────────────────────────────────────────────────
    def rgb(t):
        return colors.Color(*t)

    bg = rgb(DARK_BG)
    card = rgb(DARK_CARD)
    blue = rgb(ELECTRIC_BLUE)
    light = rgb(LIGHT_TEXT)
    muted = rgb(MUTED_TEXT)
    amber = rgb(WARNING_AMBER)
    red = rgb(CRITICAL_RED)
    green = rgb(SUCCESS_GREEN)

    # ── Styles ────────────────────────────────────────────────────────────────
    styles = getSampleStyleSheet()

    def style(name, **kwargs):
        return ParagraphStyle(name, parent=styles["Normal"], **kwargs)

    title_style = style("Title", fontSize=22, textColor=light, fontName="Helvetica-Bold",
                        spaceAfter=6, alignment=TA_LEFT)
    subtitle_style = style("Subtitle", fontSize=12, textColor=rgb(MUTED_TEXT),
                           fontName="Helvetica", spaceAfter=4)
    h2_style = style("H2", fontSize=14, textColor=blue, fontName="Helvetica-Bold",
                     spaceBefore=12, spaceAfter=6)
    body_style = style("Body", fontSize=9, textColor=light, fontName="Helvetica",
                       spaceAfter=4, leading=14)
    muted_style = style("Muted", fontSize=8, textColor=muted, fontName="Helvetica",
                        spaceAfter=3)
    mono_style = style("Mono", fontSize=8, textColor=light, fontName="Courier",
                       spaceAfter=2)

    content = []

    def hr(color=blue, thickness=1):
        return HRFlowable(width="100%", thickness=thickness, color=color, spaceAfter=8, spaceBefore=4)

    def sp(h=0.3):
        return Spacer(1, h * cm)

    # ── Cover / Header ────────────────────────────────────────────────────────
    content.append(sp(0.5))
    content.append(Paragraph("🛸 MISSION DEBRIEF REPORT", title_style))
    content.append(Paragraph("VisionWave AI — Edge Intelligence for UAV Operations", subtitle_style))
    content.append(hr(blue, 2))

    # Mission metadata table
    rating_color = RATING_COLORS.get(result.assessment.overall_rating, SUCCESS_GREEN)
    rating_label = result.assessment.overall_rating.upper()

    meta_data = [
        ["Mission", result.mission_name, "Platform", result.platform],
        ["Duration", _fmt_duration(result.duration_seconds), "Status", rating_label],
        ["Generated", result.generated_at[:19].replace("T", " "), "AI Powered", "Yes" if result.ai_powered else "No (Rule-based)"],
        ["Session ID", result.session_id, "Anomalies", str(result.total_anomalies)],
    ]

    meta_table = Table(meta_data, colWidths=[3 * cm, 7 * cm, 3.5 * cm, 3.5 * cm])
    meta_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), card),
        ("TEXTCOLOR", (0, 0), (-1, -1), light),
        ("TEXTCOLOR", (0, 0), (0, -1), blue),   # Left labels
        ("TEXTCOLOR", (2, 0), (2, -1), blue),   # Right labels
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("PADDING", (0, 0), (-1, -1), 6),
        ("GRID", (0, 0), (-1, -1), 0.5, rgb(DARK_BG)),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [card, rgb((0.12, 0.14, 0.21))]),
        ("TEXTCOLOR", (3, 1), (3, 1), rgb(rating_color)),  # Rating value color
        ("FONTNAME", (3, 1), (3, 1), "Helvetica-Bold"),
    ]))
    content.append(meta_table)
    content.append(sp())

    # ── Summary ────────────────────────────────────────────────────────────────
    content.append(Paragraph("MISSION SUMMARY", h2_style))
    content.append(hr())
    content.append(Paragraph(result.summary, body_style))
    content.append(sp())

    # ── Assessment ────────────────────────────────────────────────────────────
    content.append(Paragraph("ASSESSMENT", h2_style))
    content.append(hr())

    assessment_data = [["✅ WENT WELL", "⚠ WATCH POINTS"]]
    max_rows = max(len(result.assessment.went_well), len(result.assessment.watch_points))
    for i in range(max_rows):
        well = result.assessment.went_well[i] if i < len(result.assessment.went_well) else ""
        watch = result.assessment.watch_points[i] if i < len(result.assessment.watch_points) else ""
        assessment_data.append([
            Paragraph(f"• {well}", body_style) if well else "",
            Paragraph(f"• {watch}", body_style) if watch else "",
        ])

    assess_table = Table(assessment_data, colWidths=[9 * cm, 9 * cm])
    assess_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), rgb((0.08, 0.25, 0.15))),
        ("BACKGROUND", (1, 0), (1, 0), rgb((0.25, 0.15, 0.05))),
        ("BACKGROUND", (0, 1), (-1, -1), card),
        ("TEXTCOLOR", (0, 0), (-1, -1), light),
        ("TEXTCOLOR", (0, 0), (0, 0), green),
        ("TEXTCOLOR", (1, 0), (1, 0), amber),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("PADDING", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, bg),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    content.append(assess_table)
    content.append(sp())

    # ── Anomalies ─────────────────────────────────────────────────────────────
    if result.anomalies:
        content.append(Paragraph(f"ANOMALIES DETECTED ({len(result.anomalies)})", h2_style))
        content.append(hr(red))

        anom_data = [["TIME", "SEVERITY", "TYPE", "DESCRIPTION", "CHANNEL"]]
        for a in result.anomalies:
            sev_color = SEVERITY_COLORS.get(a.severity, ELECTRIC_BLUE)
            anom_data.append([
                Paragraph(a.timestamp, mono_style),
                Paragraph(a.severity.upper(), style(f"Sev_{a.severity}", fontSize=8,
                    textColor=rgb(sev_color), fontName="Helvetica-Bold")),
                Paragraph(a.type.replace("_", " "), muted_style),
                Paragraph(a.description, body_style),
                Paragraph(a.channel, muted_style),
            ])

        col_widths = [2 * cm, 2 * cm, 3 * cm, 8.5 * cm, 2.5 * cm]
        anom_table = Table(anom_data, colWidths=col_widths, repeatRows=1)
        anom_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), rgb((0.20, 0.08, 0.08))),
            ("TEXTCOLOR", (0, 0), (-1, 0), red),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 8),
            ("BACKGROUND", (0, 1), (-1, -1), card),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [card, rgb((0.12, 0.14, 0.21))]),
            ("GRID", (0, 0), (-1, -1), 0.5, bg),
            ("FONTSIZE", (0, 1), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("PADDING", (0, 0), (-1, -1), 5),
        ]))
        content.append(anom_table)
        content.append(sp())

    # ── Timeline ──────────────────────────────────────────────────────────────
    if result.timeline:
        content.append(Paragraph(f"EVENT TIMELINE ({len(result.timeline)} events)", h2_style))
        content.append(hr(blue))

        tl_data = [["TIME", "SEV", "EVENT"]]
        for t in result.timeline[:30]:  # Max 30 events in PDF
            sev_color = SEVERITY_COLORS.get(t.severity, ELECTRIC_BLUE)
            sev_indicator = "●"
            tl_data.append([
                Paragraph(t.timestamp, mono_style),
                Paragraph(sev_indicator, style(f"Tl_{t.severity}", fontSize=10,
                    textColor=rgb(sev_color), fontName="Helvetica-Bold")),
                Paragraph(t.event, body_style),
            ])

        tl_table = Table(tl_data, colWidths=[2 * cm, 1 * cm, 15 * cm], repeatRows=1)
        tl_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), rgb((0.08, 0.15, 0.25))),
            ("TEXTCOLOR", (0, 0), (-1, 0), blue),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("BACKGROUND", (0, 1), (-1, -1), card),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [card, rgb((0.12, 0.14, 0.21))]),
            ("GRID", (0, 0), (-1, -1), 0.5, bg),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("PADDING", (0, 0), (-1, -1), 5),
            ("ALIGN", (1, 0), (1, -1), "CENTER"),
        ]))
        content.append(tl_table)
        content.append(sp())

    # ── Decision Points ────────────────────────────────────────────────────────
    if result.decision_points:
        content.append(Paragraph(f"DECISION POINTS ({len(result.decision_points)})", h2_style))
        content.append(hr(amber))

        for dp in result.decision_points:
            dp_data = [
                [Paragraph(f"⏱ {dp.timestamp}", mono_style)],
                [Paragraph(f"Situation: {dp.situation}", body_style)],
                [Paragraph(f"Action taken: {dp.action_taken}", style("DPAction",
                    fontSize=9, textColor=rgb(ELECTRIC_BLUE),
                    fontName="Helvetica-Oblique"))],
            ]
            dp_table = Table(dp_data, colWidths=[18 * cm])
            dp_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), card),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
                ("LINEAFTER", (0, 0), (0, -1), 3, amber),
                ("GRID", (0, 0), (-1, -1), 0, bg),
            ]))
            content.append(dp_table)
            content.append(sp(0.2))

    # ── Interesting Moments ────────────────────────────────────────────────────
    if result.interesting_moments:
        content.append(sp(0.5))
        content.append(Paragraph(f"INTERESTING MOMENTS ({len(result.interesting_moments)})", h2_style))
        content.append(hr(blue))

        for m in result.interesting_moments:
            im_data = [
                [Paragraph(f"📍 {m.timestamp}", mono_style),
                 Paragraph(m.reason, muted_style)],
                [Paragraph(m.frame_description, body_style), ""],
            ]
            im_table = Table(im_data, colWidths=[9 * cm, 9 * cm])
            im_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), card),
                ("PADDING", (0, 0), (-1, -1), 7),
                ("SPAN", (0, 1), (1, 1)),
                ("GRID", (0, 0), (-1, -1), 0.5, bg),
                ("TOPPADDING", (0, 0), (-1, 0), 8),
                ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
            ]))
            content.append(im_table)
            content.append(sp(0.2))

    # ── Footer ─────────────────────────────────────────────────────────────────
    content.append(sp())
    content.append(hr(muted, 0.5))
    content.append(Paragraph(
        f"Generated by VisionWave Mission Debrief AI v0.1.0 · {result.generated_at[:19].replace('T', ' ')} UTC · "
        f"Processing time: {result.processing_time_seconds:.1f}s",
        style("Footer", fontSize=7, textColor=muted, fontName="Helvetica", alignment=TA_CENTER)
    ))

    # ── Build ─────────────────────────────────────────────────────────────────
    def _page_bg(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(rgb(DARK_BG))
        canvas.rect(0, 0, W, H, fill=True, stroke=False)
        canvas.restoreState()

    doc.build(content, onFirstPage=_page_bg, onLaterPages=_page_bg)
    log.info("PDF generated", path=output_path)


def _fmt_duration(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h}h {m:02d}m {s:02d}s"
    return f"{m}m {s:02d}s"


async def export_json(result: DebriefResult, output_path: str) -> str:
    """Export debrief result as JSON."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(result.model_dump(), f, indent=2, default=str)
    return output_path
