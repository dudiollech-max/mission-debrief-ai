/* ==========================================================================
   Visionetics — Mission Debrief · app.js
   Vanilla JS. Calls /api/demo, /api/status/{id}, /api/upload, /api/result/{id}
   when reachable — otherwise falls back to a client-side mock simulator so
   the flow demos end-to-end without a backend.
   ========================================================================== */

(function () {
    "use strict";

    // ---------- config -----------------------------------------------------
    const API_BASE = ""; // same origin
    const POLL_INTERVAL_MS = 500;
    const POLL_TIMEOUT_MS = 60_000;
    const MOCK_DURATION_MS = 12_000; // full mock run
    const STAGES = ["ingest", "vision", "anomaly", "threat", "debrief"];

    // ---------- state ------------------------------------------------------
    const state = {
        sessionId: null,
        source: null, // 'demo' | 'upload'
        pollHandle: null,
        timerHandle: null,
        mockHandle: null,
        startTs: null,
        isMock: false,
        canceled: false,
    };

    // ---------- DOM refs ---------------------------------------------------
    const $ = (id) => document.getElementById(id);

    const els = {
        toast: $("toast"),
        demoBtn: $("demo-btn"),
        uploadForm: $("upload-form"),
        uploadBtn: $("upload-btn"),
        videoInput: $("video-input"),
        telemetryInput: $("telemetry-input"),
        dzVideo: $("dz-video"),
        dzTelemetry: $("dz-telemetry"),
        dzVideoHint: $("dz-video-hint"),
        dzTelemetryHint: $("dz-telemetry-hint"),
        progressSection: $("progress-section"),
        progressBar: $("progress-bar"),
        progressBarWrap: $("progress-bar-wrap"),
        progressPercent: $("progress-percent"),
        sessionIdEl: $("session-id"),
        timerValue: $("timer-value"),
        stageList: $("stage-list"),
        cancelBtn: $("cancel-btn"),
        resultSection: $("result-section"),
        resultBadgeText: $("result-badge-text"),
        resultDuration: $("result-duration"),
        resultSubtitle: $("result-subtitle"),
        summaryTiles: $("summary-tiles"),
        panels: $("panels"),
        goLive: $("go-live"),
        newMissionBtn: $("new-mission-btn"),
        downloadJsonBtn: $("download-json-btn"),
    };

    let lastDebrief = null;

    // ---------- utils ------------------------------------------------------
    function showToast(message, duration = 4500) {
        els.toast.textContent = "";
        const span = document.createElement("span");
        span.textContent = message;
        els.toast.appendChild(span);
        els.toast.classList.add("is-visible");
        clearTimeout(els.toast._t);
        els.toast._t = setTimeout(() => {
            els.toast.classList.remove("is-visible");
        }, duration);
    }

    function formatBytes(bytes) {
        if (bytes < 1024) return bytes + " B";
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
        if (bytes < 1024 * 1024 * 1024)
            return (bytes / (1024 * 1024)).toFixed(1) + " MB";
        return (bytes / (1024 * 1024 * 1024)).toFixed(2) + " GB";
    }

    function formatDuration(ms) {
        const s = Math.floor(ms / 1000);
        const m = Math.floor(s / 60);
        const rem = s % 60;
        return (
            String(m).padStart(2, "0") + ":" + String(rem).padStart(2, "0")
        );
    }

    function resetProgressUI() {
        els.progressBar.style.width = "0%";
        els.progressPercent.textContent = "0%";
        els.progressBarWrap.setAttribute("aria-valuenow", "0");
        els.timerValue.textContent = "00:00";
        els.sessionIdEl.textContent = "—";
        Array.from(
            els.stageList.querySelectorAll(".stage"),
        ).forEach((el) => el.removeAttribute("data-state"));
    }

    function setProgress(pct) {
        const clamped = Math.max(0, Math.min(100, pct));
        els.progressBar.style.width = clamped + "%";
        els.progressPercent.textContent = Math.round(clamped) + "%";
        els.progressBarWrap.setAttribute(
            "aria-valuenow",
            String(Math.round(clamped)),
        );
    }

    function setStageStates(currentStage, done) {
        Array.from(els.stageList.querySelectorAll(".stage")).forEach((el) => {
            const name = el.getAttribute("data-stage");
            if (done && STAGES.indexOf(name) <= STAGES.indexOf(done)) {
                el.setAttribute("data-state", "done");
            } else if (name === currentStage) {
                el.setAttribute("data-state", "active");
            } else {
                el.removeAttribute("data-state");
            }
        });
    }

    function startTimer() {
        state.startTs = Date.now();
        els.timerValue.textContent = "00:00";
        state.timerHandle = setInterval(() => {
            const elapsed = Date.now() - state.startTs;
            const s = Math.floor(elapsed / 1000);
            els.timerValue.textContent =
                String(Math.floor(s / 60)).padStart(2, "0") +
                ":" +
                String(s % 60).padStart(2, "0");
        }, 250);
    }

    function stopTimer() {
        clearInterval(state.timerHandle);
        state.timerHandle = null;
    }

    function stopPolling() {
        clearInterval(state.pollHandle);
        state.pollHandle = null;
    }

    function stopMock() {
        if (state.mockHandle) {
            clearTimeout(state.mockHandle);
            state.mockHandle = null;
        }
    }

    // ---------- API layer with mock fallback -------------------------------
    async function apiGetDemo() {
        try {
            const r = await fetch(API_BASE + "/api/demo", {
                method: "GET",
                headers: { Accept: "application/json" },
            });
            if (!r.ok) throw new Error("HTTP " + r.status);
            const data = await r.json();
            return { data, mock: false };
        } catch (_e) {
            return {
                data: {
                    session_id:
                        "vw-demo-" +
                        Math.random().toString(36).slice(2, 10),
                    is_mock: true,
                },
                mock: true,
            };
        }
    }

    async function apiUpload(formData) {
        try {
            const r = await fetch(API_BASE + "/api/upload", {
                method: "POST",
                body: formData,
            });
            if (!r.ok) throw new Error("HTTP " + r.status);
            const data = await r.json();
            return { data, mock: false };
        } catch (_e) {
            return {
                data: {
                    session_id:
                        "vw-live-" +
                        Math.random().toString(36).slice(2, 10),
                    is_mock: true,
                },
                mock: true,
            };
        }
    }

    async function apiStatus(sessionId) {
        const r = await fetch(
            API_BASE + "/api/status/" + encodeURIComponent(sessionId),
            {
                method: "GET",
                headers: { Accept: "application/json" },
            },
        );
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
    }

    async function apiResult(sessionId) {
        const r = await fetch(
            API_BASE + "/api/result/" + encodeURIComponent(sessionId),
            {
                method: "GET",
                headers: { Accept: "application/json" },
            },
        );
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
    }

    // ---------- mock debrief data -----------------------------------------
    function buildMockDebrief(sessionId, source) {
        return {
            session_id: sessionId,
            is_mock: true,
            source: source,
            completed_at: new Date().toISOString(),
            processing_time_seconds: 12.4,
            mission: {
                codename: "COASTAL SENTINEL 07",
                operator: "UAV-Ridgeback-04",
                start_time: "2026-02-14T08:14:22Z",
                duration_seconds: 272,
                distance_km: 2.41,
                max_altitude_m: 87,
                avg_speed_ms: 8.6,
                area_km2: 0.42,
                weather: "Clear · 14°C · Wind 12 km/h NE",
            },
            summary:
                "Coastal perimeter sweep completed nominally. 47 objects detected across urban and shoreline zones. Three anomalies flagged for review — one thermal signature adjacent to restricted zone, one unauthorized watercraft, one perimeter fence breach candidate. Overall threat posture assessed as LOW with 94% model confidence.",
            metrics: [
                { label: "Flight duration", value: "04:32" },
                { label: "Ground distance", value: "2.41 km" },
                { label: "Peak altitude", value: "87 m AGL" },
                { label: "Avg speed", value: "8.6 m/s" },
                { label: "Battery used", value: "38%" },
                { label: "Frames analyzed", value: "16,320" },
                { label: "GPS fix quality", value: "RTK · 0.02 m" },
                { label: "Signal loss events", value: "0" },
            ],
            detections: [
                {
                    label: "Vehicle · civilian",
                    count: 18,
                    confidence: 0.98,
                    zone: "shoreline access rd.",
                    severity: "low",
                },
                {
                    label: "Personnel",
                    count: 11,
                    confidence: 0.95,
                    zone: "beach perimeter",
                    severity: "low",
                },
                {
                    label: "Watercraft · small",
                    count: 6,
                    confidence: 0.93,
                    zone: "coastal buffer",
                    severity: "low",
                },
                {
                    label: "Structures",
                    count: 9,
                    confidence: 0.99,
                    zone: "sector B",
                    severity: "low",
                },
                {
                    label: "Watercraft · unregistered",
                    count: 1,
                    confidence: 0.81,
                    zone: "restricted lane",
                    severity: "med",
                },
                {
                    label: "Wildlife · fauna",
                    count: 2,
                    confidence: 0.87,
                    zone: "north dune",
                    severity: "low",
                },
            ],
            anomalies: [
                {
                    id: "ANM-01",
                    kind: "Thermal signature",
                    severity: "med",
                    confidence: 0.79,
                    location: "34.0192°N, 118.4931°W",
                    timestamp_offset: "02:14",
                    note: "Persistent heat source 4.2°C above ambient — likely idling vehicle within restricted zone.",
                },
                {
                    id: "ANM-02",
                    kind: "Unauthorized watercraft",
                    severity: "med",
                    confidence: 0.81,
                    location: "34.0175°N, 118.4948°W",
                    timestamp_offset: "03:07",
                    note: "Small vessel entering geofenced coastal lane. No registered transponder detected.",
                },
                {
                    id: "ANM-03",
                    kind: "Perimeter fence candidate",
                    severity: "low",
                    confidence: 0.62,
                    location: "34.0208°N, 118.4917°W",
                    timestamp_offset: "01:41",
                    note: "Possible fence gap in sector B7. Low confidence — recommend follow-up sweep.",
                },
            ],
            threat: {
                level: "LOW",
                score: 0.28,
                confidence: 0.94,
                vectors: [
                    { name: "Airspace intrusion", score: 0.08 },
                    { name: "Ground incursion", score: 0.34 },
                    { name: "Restricted-zone activity", score: 0.41 },
                    { name: "Weather risk", score: 0.12 },
                ],
                notes: "Elevated attention on restricted-zone activity vector. Recommend follow-up flight in next 45 minutes to confirm anomalies ANM-01 and ANM-02.",
            },
            recommendations: [
                "Re-task UAV-Ridgeback-04 for a 90-second confirmation sweep of sector B7 within 45 minutes.",
                "Dispatch ground team to verify thermal signature (ANM-01) at 34.0192°N, 118.4931°W.",
                "Notify maritime unit of unregistered watercraft (ANM-02) heading NW at ~6 knots.",
                "Log fence gap candidate (ANM-03) for scheduled maintenance survey.",
            ],
        };
    }

    // ---------- mock progress simulator ------------------------------------
    // Provides staged status responses over time so the polling UI works.
    let mockProgressState = null;

    function startMockSimulation(sessionId, source) {
        mockProgressState = {
            sessionId,
            source,
            startedAt: Date.now(),
        };
    }

    function mockStatus() {
        if (!mockProgressState) return { progress: 0, stage: "ingest", state: "queued" };
        const elapsed = Date.now() - mockProgressState.startedAt;
        const pct = Math.min(100, (elapsed / MOCK_DURATION_MS) * 100);
        const stageIdx = Math.min(
            STAGES.length - 1,
            Math.floor((pct / 100) * STAGES.length),
        );
        const stage = STAGES[stageIdx];
        const done_stages = STAGES.slice(0, stageIdx);
        return {
            session_id: mockProgressState.sessionId,
            progress: pct,
            stage: stage,
            done_stages: done_stages,
            state: pct >= 100 ? "complete" : "processing",
            is_mock: true,
        };
    }

    // ---------- pipeline ---------------------------------------------------
    async function startDebrief(source, formData) {
        if (state.pollHandle) return; // already running
        state.canceled = false;
        state.source = source;
        state.isMock = false;
        resetProgressUI();

        els.resultSection.hidden = true;
        els.progressSection.hidden = false;
        els.progressSection.scrollIntoView({
            behavior: "smooth",
            block: "start",
        });
        setControlsEnabled(false);
        startTimer();

        // 1. Kick off session
        let init;
        try {
            if (source === "demo") {
                init = await apiGetDemo();
            } else {
                init = await apiUpload(formData);
            }
        } catch (err) {
            console.error("Failed to start debrief", err);
            showToast("Failed to start debrief. Please try again.");
            cleanupAndReset();
            return;
        }

        state.sessionId = init.data.session_id;
        state.isMock = init.mock || init.data.is_mock === true;
        els.sessionIdEl.textContent = state.sessionId;

        if (state.isMock) startMockSimulation(state.sessionId, source);

        // 2. Poll status
        const pollStart = Date.now();
        state.pollHandle = setInterval(async () => {
            if (state.canceled) return;
            if (Date.now() - pollStart > POLL_TIMEOUT_MS) {
                stopPolling();
                showToast(
                    "Debrief timed out after 60s. Backend unreachable — try demo mode.",
                );
                cleanupAndReset();
                return;
            }

            let status;
            try {
                status = state.isMock
                    ? mockStatus()
                    : await apiStatus(state.sessionId);
            } catch (err) {
                // Backend went offline mid-run → seamlessly switch to mock
                console.warn("Status poll failed, switching to mock", err);
                state.isMock = true;
                startMockSimulation(state.sessionId, source);
                status = mockStatus();
            }

            const pct = Number(status.progress) || 0;
            setProgress(pct);
            setStageStates(status.stage, null);
            if (Array.isArray(status.done_stages)) {
                status.done_stages.forEach((s) => {
                    const el = els.stageList.querySelector(
                        `.stage[data-stage="${s}"]`,
                    );
                    if (el) el.setAttribute("data-state", "done");
                });
            }

            if (status.state === "complete" || pct >= 100) {
                stopPolling();
                // Mark all stages done
                STAGES.forEach((s) => {
                    const el = els.stageList.querySelector(
                        `.stage[data-stage="${s}"]`,
                    );
                    if (el) el.setAttribute("data-state", "done");
                });
                setProgress(100);

                // 3. Fetch full debrief
                let debrief;
                try {
                    debrief = state.isMock
                        ? buildMockDebrief(state.sessionId, source)
                        : await apiResult(state.sessionId);
                } catch (err) {
                    console.warn("Result fetch failed, using mock", err);
                    debrief = buildMockDebrief(state.sessionId, source);
                    state.isMock = true;
                }
                stopTimer();
                setTimeout(() => renderResult(debrief), 400);
            }
        }, POLL_INTERVAL_MS);
    }

    function cleanupAndReset() {
        stopPolling();
        stopTimer();
        stopMock();
        state.canceled = true;
        setControlsEnabled(true);
        els.progressSection.hidden = true;
        resetProgressUI();
    }

    function setControlsEnabled(enabled) {
        els.demoBtn.disabled = !enabled;
        // upload button state depends on file presence
        if (enabled) refreshUploadBtnState();
        else els.uploadBtn.disabled = true;
    }

    // ---------- Result rendering ------------------------------------------
    function renderResult(debrief) {
        lastDebrief = debrief;
        els.progressSection.hidden = true;
        els.resultSection.hidden = false;

        // Header
        els.resultBadgeText.textContent = "COMPLETE";
        els.resultDuration.textContent =
            (debrief.processing_time_seconds || 12).toFixed(1) + "s runtime";
        els.resultSubtitle.textContent =
            debrief.mission
                ? `${debrief.mission.codename} · ${debrief.mission.operator}`
                : "Debrief compiled successfully.";

        // Tiles
        const t = debrief.mission || {};
        const anomCount = (debrief.anomalies || []).length;
        const detCount = (debrief.detections || []).reduce(
            (acc, d) => acc + (d.count || 1),
            0,
        );
        const threatLevel = (debrief.threat && debrief.threat.level) || "LOW";
        const threatConf =
            (debrief.threat && debrief.threat.confidence) || 0.9;
        const tiles = [
            {
                label: "Threat level",
                value: threatLevel,
                hint:
                    Math.round(threatConf * 100) + "% model confidence",
                level:
                    threatLevel === "LOW"
                        ? "low"
                        : threatLevel === "MEDIUM"
                          ? "med"
                          : "high",
            },
            {
                label: "Flight duration",
                value:
                    formatDuration(
                        (t.duration_seconds || 0) * 1000,
                    ),
                hint: (t.distance_km || 0).toFixed(2) + " km covered",
            },
            {
                label: "Detections",
                value: String(detCount),
                hint: (debrief.detections || []).length + " categories",
            },
            {
                label: "Anomalies",
                value: String(anomCount),
                hint: anomCount === 0 ? "clean sweep" : "flagged for review",
                level: anomCount === 0 ? "low" : "med",
            },
            {
                label: "Peak altitude",
                value: (t.max_altitude_m || 0) + " m",
                hint: "AGL",
            },
            {
                label: "Area covered",
                value: (t.area_km2 || 0).toFixed(2) + " km²",
                hint: t.weather || "conditions logged",
            },
        ];
        els.summaryTiles.innerHTML = tiles
            .map(
                (tile) => `
                <div class="tile" data-level="${tile.level || ""}" data-testid="tile-${tile.label
                    .toLowerCase()
                    .replace(/[^a-z0-9]+/g, "-")}">
                    <span class="tile-label">${tile.label}</span>
                    <span class="tile-value">${tile.value}</span>
                    <span class="tile-hint">${tile.hint}</span>
                </div>
            `,
            )
            .join("");

        // Panels
        const panels = [
            {
                title: "Executive summary",
                testId: "panel-summary",
                open: true,
                body: `<p>${escapeHtml(debrief.summary || "—")}</p>`,
            },
            {
                title: "Flight metrics",
                testId: "panel-metrics",
                open: false,
                body: renderMetricsTable(debrief.metrics || []),
            },
            {
                title: "Detected objects",
                testId: "panel-detections",
                open: false,
                body: renderDetections(debrief.detections || []),
            },
            {
                title: "Anomalies",
                testId: "panel-anomalies",
                open: false,
                body: renderAnomalies(debrief.anomalies || []),
            },
            {
                title: "Threat assessment",
                testId: "panel-threat",
                open: false,
                body: renderThreat(debrief.threat || {}),
            },
            {
                title: "Recommendations",
                testId: "panel-recs",
                open: false,
                body: renderRecs(debrief.recommendations || []),
            },
        ];

        els.panels.innerHTML = panels
            .map(
                (p, i) => `
                <div class="panel ${p.open ? "is-open" : ""}" data-testid="${p.testId}">
                    <button
                        type="button"
                        class="panel-toggle"
                        aria-expanded="${p.open ? "true" : "false"}"
                        data-testid="${p.testId}-toggle"
                    >
                        <span class="panel-toggle-left">
                            <span class="panel-index">${String(i + 1).padStart(2, "0")}</span>
                            <span>${p.title}</span>
                        </span>
                        <span class="panel-chev" aria-hidden="true"></span>
                    </button>
                    <div class="panel-body">
                        <div class="panel-inner">${p.body}</div>
                    </div>
                </div>
            `,
            )
            .join("");

        // Bind panel toggles
        els.panels.querySelectorAll(".panel").forEach((panel) => {
            const toggle = panel.querySelector(".panel-toggle");
            toggle.addEventListener("click", () => {
                const open = panel.classList.toggle("is-open");
                toggle.setAttribute(
                    "aria-expanded",
                    open ? "true" : "false",
                );
            });
        });

        // Go-live banner
        els.goLive.hidden = !debrief.is_mock;

        els.resultSection.scrollIntoView({
            behavior: "smooth",
            block: "start",
        });
        stopTimer();
        setControlsEnabled(true);
    }

    function escapeHtml(str) {
        return String(str).replace(/[&<>"']/g, (c) => ({
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;",
        })[c]);
    }

    function renderMetricsTable(rows) {
        if (!rows.length) return "<p>No metrics available.</p>";
        return `<div class="dtable">${rows
            .map(
                (r) => `
                <div class="dtable-row">
                    <span class="dtable-key">${escapeHtml(r.label)}</span>
                    <span class="dtable-val">${escapeHtml(r.value)}</span>
                </div>
            `,
            )
            .join("")}</div>`;
    }

    function renderDetections(rows) {
        if (!rows.length) return "<p>No detections logged.</p>";
        return `<ul class="det-list">${rows
            .map(
                (r) => `
                <li class="det-item" data-severity="${r.severity || "low"}">
                    <span class="det-icon" aria-hidden="true">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3"/></svg>
                    </span>
                    <span class="det-name">${escapeHtml(r.label)} <span class="det-meta">· ×${r.count}</span></span>
                    <span class="det-meta">${escapeHtml(r.zone || "")}</span>
                    <span class="det-conf">${Math.round((r.confidence || 0) * 100)}%</span>
                </li>
            `,
            )
            .join("")}</ul>`;
    }

    function renderAnomalies(rows) {
        if (!rows.length)
            return "<p>No anomalies detected. Clean sweep.</p>";
        return `<ul class="det-list">${rows
            .map(
                (a) => `
                <li class="det-item" data-severity="${a.severity || "med"}">
                    <span class="det-icon" aria-hidden="true">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                    </span>
                    <span class="det-name">
                        ${escapeHtml(a.id || "")} · ${escapeHtml(a.kind || "")}
                        <div class="det-meta" style="margin-top:4px">${escapeHtml(a.note || "")}</div>
                        <div class="det-meta" style="margin-top:2px">t+${escapeHtml(a.timestamp_offset || "—")} · ${escapeHtml(a.location || "")}</div>
                    </span>
                    <span></span>
                    <span class="det-conf">${Math.round((a.confidence || 0) * 100)}%</span>
                </li>
            `,
            )
            .join("")}</ul>`;
    }

    function renderThreat(t) {
        if (!t || !t.level) return "<p>No threat data.</p>";
        const vectors = t.vectors || [];
        return `
            <div class="dtable">
                <div class="dtable-row">
                    <span class="dtable-key">Overall level</span>
                    <span class="dtable-val">${escapeHtml(t.level)}</span>
                </div>
                <div class="dtable-row">
                    <span class="dtable-key">Composite score</span>
                    <span class="dtable-val">${(t.score || 0).toFixed(2)} / 1.00</span>
                </div>
                <div class="dtable-row">
                    <span class="dtable-key">Model confidence</span>
                    <span class="dtable-val">${Math.round((t.confidence || 0) * 100)}%</span>
                </div>
                ${vectors
                    .map(
                        (v) => `
                    <div class="dtable-row">
                        <span class="dtable-key">${escapeHtml(v.name)}</span>
                        <span class="dtable-val">${(v.score || 0).toFixed(2)}</span>
                    </div>
                `,
                    )
                    .join("")}
            </div>
            ${t.notes ? `<p style="margin-top:14px">${escapeHtml(t.notes)}</p>` : ""}
        `;
    }

    function renderRecs(rows) {
        if (!rows.length) return "<p>No recommendations.</p>";
        return `<ul class="det-list">${rows
            .map(
                (r, i) => `
                <li class="det-item">
                    <span class="det-icon" aria-hidden="true">
                        <span style="font-family:var(--font-mono);font-size:12px;color:var(--accent)">${String(i + 1).padStart(2, "0")}</span>
                    </span>
                    <span class="det-name" style="grid-column:2 / span 3">${escapeHtml(r)}</span>
                </li>
            `,
            )
            .join("")}</ul>`;
    }

    // ---------- Dropzone wiring -------------------------------------------
    function wireDropzone(zoneEl, inputEl, hintEl) {
        const openPicker = () => inputEl.click();

        zoneEl.addEventListener("click", openPicker);
        zoneEl.addEventListener("keydown", (e) => {
            if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                openPicker();
            }
        });

        ["dragenter", "dragover"].forEach((evt) =>
            zoneEl.addEventListener(evt, (e) => {
                e.preventDefault();
                e.stopPropagation();
                zoneEl.classList.add("is-dragover");
            }),
        );
        ["dragleave", "drop"].forEach((evt) =>
            zoneEl.addEventListener(evt, (e) => {
                e.preventDefault();
                e.stopPropagation();
                zoneEl.classList.remove("is-dragover");
            }),
        );
        zoneEl.addEventListener("drop", (e) => {
            const files = e.dataTransfer && e.dataTransfer.files;
            if (files && files.length) {
                inputEl.files = files;
                inputEl.dispatchEvent(new Event("change", { bubbles: true }));
            }
        });

        inputEl.addEventListener("change", () => {
            const f = inputEl.files && inputEl.files[0];
            if (f) {
                zoneEl.classList.add("is-loaded");
                hintEl.textContent = `${f.name} · ${formatBytes(f.size)}`;
            } else {
                zoneEl.classList.remove("is-loaded");
            }
            refreshUploadBtnState();
        });
    }

    function refreshUploadBtnState() {
        const hasVideo = !!(els.videoInput.files && els.videoInput.files[0]);
        els.uploadBtn.disabled = !hasVideo;
    }

    // ---------- Event bindings --------------------------------------------
    function bind() {
        // demo
        els.demoBtn.addEventListener("click", () => startDebrief("demo"));

        // dropzones
        wireDropzone(els.dzVideo, els.videoInput, els.dzVideoHint);
        wireDropzone(
            els.dzTelemetry,
            els.telemetryInput,
            els.dzTelemetryHint,
        );

        // upload submit
        els.uploadForm.addEventListener("submit", (e) => {
            e.preventDefault();
            const video = els.videoInput.files && els.videoInput.files[0];
            if (!video) {
                showToast("Select a video file to run a debrief.");
                return;
            }
            const fd = new FormData();
            fd.append("video", video);
            const tel =
                els.telemetryInput.files && els.telemetryInput.files[0];
            if (tel) fd.append("telemetry", tel);
            startDebrief("upload", fd);
        });

        // cancel
        els.cancelBtn.addEventListener("click", () => {
            state.canceled = true;
            cleanupAndReset();
            showToast("Debrief canceled.");
        });

        // new mission
        els.newMissionBtn.addEventListener("click", () => {
            els.resultSection.hidden = true;
            // reset upload form
            els.uploadForm.reset();
            els.dzVideo.classList.remove("is-loaded");
            els.dzTelemetry.classList.remove("is-loaded");
            els.dzVideoHint.textContent =
                "Drag & drop or click to browse · .mp4 .mov · up to 2GB";
            els.dzTelemetryHint.textContent =
                "Drag & drop or click to browse · .csv .json .log";
            refreshUploadBtnState();
            document
                .getElementById("systems")
                .scrollIntoView({ behavior: "smooth", block: "start" });
        });

        // download JSON
        els.downloadJsonBtn.addEventListener("click", () => {
            if (!lastDebrief) return;
            const blob = new Blob(
                [JSON.stringify(lastDebrief, null, 2)],
                { type: "application/json" },
            );
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `visionetics-debrief-${lastDebrief.session_id || "mission"}.json`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        });
    }

    // ---------- boot -------------------------------------------------------
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", bind);
    } else {
        bind();
    }
})();
