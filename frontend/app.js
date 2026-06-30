/**
 * Mission Debrief AI — Frontend App
 * VisionWave dark theme UI for demo + upload + live debrief display
 */

const API = '';  // Same-origin (served by FastAPI)
let currentSessionId = null;
let currentResult = null;
let demoTimerInterval = null;
let demoStartTime = null;

// ── Demo ────────────────────────────────────────────────────────────────────

async function runDemo() {
  const btn = document.getElementById('demo-btn');
  const progressSec = document.getElementById('demo-progress');
  const errorEl = document.getElementById('demo-error');

  btn.disabled = true;
  btn.textContent = '⌛ Starting demo...';
  errorEl.classList.remove('active');

  try {
    // POST /api/demo to start
    const res = await fetch(`${API}/api/demo`, { method: 'POST' });
    if (!res.ok) throw new Error(await res.text());

    const data = await res.json();
    currentSessionId = data.session_id;

    // Show progress UI
    progressSec.classList.add('active');
    document.getElementById('demo-status-msg').textContent = 'Demo running...';

    // Start timer
    demoStartTime = Date.now();
    if (demoTimerInterval) clearInterval(demoTimerInterval);
    demoTimerInterval = setInterval(() => {
      const elapsed = ((Date.now() - demoStartTime) / 1000).toFixed(1);
      document.getElementById('demo-timer').textContent = elapsed;
    }, 100);

    // Stream progress via SSE
    await streamDemoProgress(data.session_id);

  } catch (err) {
    showError('demo-error', `Demo failed: ${err.message}`);
    btn.disabled = false;
    btn.innerHTML = '<span>▶</span> Run SolarDrone Demo';
  }
}

async function streamDemoProgress(sessionId) {
  const es = new EventSource(`${API}/api/demo/stream/${sessionId}`);
  const btn = document.getElementById('demo-btn');

  es.addEventListener('progress', (e) => {
    const data = JSON.parse(e.data);
    updateProgress('demo', data.progress, data.message);
  });

  es.addEventListener('complete', (e) => {
    es.close();
    clearInterval(demoTimerInterval);

    const elapsed = ((Date.now() - demoStartTime) / 1000).toFixed(1);
    document.getElementById('demo-timer').textContent = elapsed;
    document.getElementById('demo-status-msg').textContent = `✅ Complete in ${elapsed}s`;
    updateProgress('demo', 100, 'Debrief generated!');

    const data = JSON.parse(e.data);
    if (data.result) {
      displayResult(data.result);
    } else {
      // Fetch result from API
      fetchAndDisplayResult(sessionId);
    }

    btn.disabled = false;
    btn.innerHTML = '<span>▶</span> Run Demo Again';

    showToast('✅ SolarDrone debrief complete!', 'success');
  });

  es.addEventListener('error', (e) => {
    es.close();
    clearInterval(demoTimerInterval);
    const data = e.data ? JSON.parse(e.data) : {};
    showError('demo-error', data.message || 'Demo stream error. Polling for result...');

    // Fallback: poll for result
    pollForResult(sessionId, 'demo');

    document.getElementById('demo-btn').disabled = false;
    document.getElementById('demo-btn').innerHTML = '<span>▶</span> Run SolarDrone Demo';
  });

  // Fallback timeout
  setTimeout(() => {
    if (es.readyState !== EventSource.CLOSED) {
      es.close();
      pollForResult(sessionId, 'demo');
    }
  }, 120000);
}

// ── Upload ──────────────────────────────────────────────────────────────────

async function runUpload() {
  const btn = document.getElementById('upload-btn');
  const errorEl = document.getElementById('upload-error');

  const missionName = document.getElementById('upload-mission-name').value || 'Mission';
  const platform = document.getElementById('upload-platform').value || 'UAV';
  const videoFile = document.getElementById('video-file').files[0];
  const telemFile = document.getElementById('telem-file').files[0];
  const logFile = document.getElementById('log-file').files[0];

  if (!videoFile && !telemFile && !logFile) {
    showError('upload-error', 'Please upload at least one file (video, telemetry, or event log).');
    return;
  }

  btn.disabled = true;
  btn.textContent = '⌛ Uploading...';
  errorEl.classList.remove('active');

  try {
    const formData = new FormData();
    formData.append('mission_name', missionName);
    formData.append('platform', platform);
    if (videoFile) formData.append('video', videoFile);
    if (telemFile) formData.append('telemetry', telemFile);
    if (logFile) formData.append('sensor_log', logFile);

    const res = await fetch(`${API}/api/ingest`, { method: 'POST', body: formData });
    if (!res.ok) throw new Error(await res.text());

    const data = await res.json();
    currentSessionId = data.session_id;

    document.getElementById('upload-progress').classList.add('active');
    updateProgress('upload', 10, 'Data ingested — starting debrief...');

    // Trigger debrief with SSE
    await streamDebrief(data.session_id);

  } catch (err) {
    showError('upload-error', `Upload failed: ${err.message}`);
    btn.disabled = false;
    btn.innerHTML = '<span>🚀</span> Ingest & Generate Debrief';
  }
}

async function streamDebrief(sessionId) {
  const btn = document.getElementById('upload-btn');

  try {
    const res = await fetch(`${API}/api/debrief/${sessionId}`, { method: 'POST' });

    if (!res.ok) throw new Error(await res.text());
    if (!res.body) throw new Error('No SSE stream');

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();

      for (const line of lines) {
        if (line.startsWith('event:')) {
          // handled below
        } else if (line.startsWith('data:')) {
          const eventType = lines[lines.indexOf(line) - 1]?.replace('event: ', '').trim();
          try {
            const data = JSON.parse(line.slice(5));
            if (data.progress !== undefined) {
              updateProgress('upload', data.progress, data.message || '');
            }
            if (data.result) {
              displayResult(data.result);
              showToast('✅ Debrief complete!', 'success');
            }
          } catch (_) {}
        }
      }
    }

    // Fetch result if we didn't get it via SSE
    const statusRes = await fetch(`${API}/api/status/${sessionId}`);
    const status = await statusRes.json();
    if (status.status === 'complete') {
      await fetchAndDisplayResult(sessionId);
    }

  } catch (err) {
    console.warn('SSE failed, falling back to polling:', err);
    pollForResult(sessionId, 'upload');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<span>🚀</span> Ingest & Generate Debrief';
  }
}

// ── Result Display ──────────────────────────────────────────────────────────

function displayResult(result) {
  currentResult = result;
  const section = document.getElementById('result-section');
  section.classList.add('active');

  // Scroll to result
  setTimeout(() => section.scrollIntoView({ behavior: 'smooth', block: 'start' }), 100);

  // Header metadata
  document.getElementById('res-mission').textContent = result.mission_name;
  document.getElementById('res-platform').textContent = result.platform;
  document.getElementById('res-duration').textContent = formatDuration(result.duration_seconds);
  document.getElementById('res-anomalies').textContent = result.total_anomalies || result.anomalies?.length || 0;
  document.getElementById('res-proc-time').textContent = `${result.processing_time_seconds?.toFixed(1)}s`;
  document.getElementById('res-ai-mode').textContent = result.ai_powered ? '🤖 AI' : '⚙ Rule-based';
  document.getElementById('dl-session-id').textContent = result.session_id;

  // Rating badge
  const rating = result.assessment?.overall_rating || 'green';
  const ratingEl = document.getElementById('res-rating');
  ratingEl.className = `rating-badge rating-${rating}`;
  ratingEl.textContent = rating.toUpperCase();

  // Summary
  document.getElementById('res-summary').textContent = result.summary;

  // Assessment
  const goodEl = document.getElementById('assess-good');
  const watchEl = document.getElementById('assess-watch');
  goodEl.innerHTML = (result.assessment?.went_well || []).map(item =>
    `<div class="assessment-item"><span class="assessment-bullet">✅</span><span>${escHtml(item)}</span></div>`
  ).join('');
  watchEl.innerHTML = (result.assessment?.watch_points || []).map(item =>
    `<div class="assessment-item"><span class="assessment-bullet">⚠</span><span>${escHtml(item)}</span></div>`
  ).join('');
  const assessTotal = (result.assessment?.went_well?.length || 0) + (result.assessment?.watch_points?.length || 0);
  document.getElementById('cnt-assessment').textContent = assessTotal;

  // Anomalies
  const anomalies = result.anomalies || [];
  document.getElementById('cnt-anomalies').textContent = anomalies.length;
  document.getElementById('anomaly-list').innerHTML = anomalies.length
    ? anomalies.map(a => `
      <div class="anomaly-item anomaly-${a.severity}">
        <div class="anomaly-header">
          <span class="anomaly-severity sev-${a.severity}">${a.severity.toUpperCase()}</span>
          <span class="anomaly-time">${a.timestamp}</span>
          <span class="anomaly-channel">${a.channel}</span>
        </div>
        <div class="anomaly-desc">${escHtml(a.description)}</div>
        ${a.value !== null && a.value !== undefined ? `<div class="anomaly-time">Value: ${a.value} · Threshold: ${a.threshold}</div>` : ''}
      </div>`).join('')
    : '<div style="color:var(--success-green);padding:16px 0;">✅ No anomalies detected</div>';

  // Timeline
  const timeline = result.timeline || [];
  document.getElementById('cnt-timeline').textContent = timeline.length;
  document.getElementById('timeline-list').innerHTML = timeline.map(t => `
    <div class="timeline-item">
      <div class="timeline-dot dot-${t.severity}"></div>
      <div class="timeline-content">
        <div class="timeline-time">${t.timestamp}</div>
        <div class="timeline-event">${escHtml(t.event)}</div>
      </div>
    </div>`).join('');

  // Decision points
  const decisions = result.decision_points || [];
  document.getElementById('cnt-decisions').textContent = decisions.length;
  document.getElementById('decision-list').innerHTML = decisions.map(d => `
    <div class="decision-item">
      <div class="decision-time">⏱ ${d.timestamp}</div>
      <div class="decision-situation">${escHtml(d.situation)}</div>
      <div class="decision-action">→ ${escHtml(d.action_taken)}</div>
    </div>`).join('');

  // Interesting moments
  const moments = result.interesting_moments || [];
  document.getElementById('cnt-moments').textContent = moments.length;
  document.getElementById('moments-list').innerHTML = moments.map(m => `
    <div class="moment-item">
      <div class="moment-time">📍 ${m.timestamp}</div>
      <div class="moment-reason">${escHtml(m.reason)}</div>
      <div class="moment-desc">${escHtml(m.frame_description)}</div>
    </div>`).join('');
}

async function fetchAndDisplayResult(sessionId) {
  try {
    const res = await fetch(`${API}/api/result/${sessionId}`);
    if (res.ok) {
      const result = await res.json();
      displayResult(result);
    }
  } catch (err) {
    console.error('Failed to fetch result:', err);
  }
}

// ── Polling fallback ────────────────────────────────────────────────────────

async function pollForResult(sessionId, prefix) {
  const maxAttempts = 60;
  let attempts = 0;

  const poll = async () => {
    if (attempts++ > maxAttempts) return;

    try {
      const res = await fetch(`${API}/api/status/${sessionId}`);
      const status = await res.json();

      updateProgress(prefix, status.progress || 0, status.message || `Status: ${status.status}`);

      if (status.status === 'complete') {
        await fetchAndDisplayResult(sessionId);
        showToast('✅ Debrief complete!', 'success');
        return;
      } else if (status.status === 'error') {
        showError(`${prefix}-error`, status.error || 'Unknown error');
        return;
      }

      setTimeout(poll, 1500);
    } catch (err) {
      setTimeout(poll, 2000);
    }
  };

  await poll();
}

// ── Downloads ───────────────────────────────────────────────────────────────

function downloadJson() {
  if (!currentResult) return;
  const blob = new Blob([JSON.stringify(currentResult, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `debrief_${currentResult.session_id}.json`;
  a.click();
  URL.revokeObjectURL(url);
  showToast('📄 JSON downloaded', 'success');
}

async function downloadPdf() {
  if (!currentSessionId) return;
  const btn = document.getElementById('pdf-btn');
  btn.disabled = true;
  btn.textContent = '⌛ Generating PDF...';

  try {
    const res = await fetch(`${API}/api/result/${currentSessionId}/pdf`);
    if (!res.ok) throw new Error(await res.text());

    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `debrief_${currentSessionId}.pdf`;
    a.click();
    URL.revokeObjectURL(url);
    showToast('📄 PDF downloaded', 'success');
  } catch (err) {
    showToast(`PDF error: ${err.message}`, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = '⬇ PDF Report';
  }
}

// ── UI Helpers ──────────────────────────────────────────────────────────────

function updateProgress(prefix, pct, msg) {
  const bar = document.getElementById(`${prefix}-bar`);
  const pctEl = document.getElementById(`${prefix}-pct`);
  const msgEl = document.getElementById(`${prefix}-msg`);

  if (bar) bar.style.width = `${pct}%`;
  if (pctEl) pctEl.textContent = `${pct}%`;
  if (msgEl) msgEl.textContent = msg;
}

function toggleSection(btn) {
  btn.classList.toggle('open');
  const bodyId = btn.nextElementSibling.id;
  const body = document.getElementById(bodyId);
  if (body) body.classList.toggle('open');
}

function handleFileDrop(input, dropId, label) {
  const drop = document.getElementById(dropId);
  drop.classList.add('has-file');
  drop.querySelector('.file-drop-label').textContent = label;
}

function showError(elId, msg) {
  const el = document.getElementById(elId);
  if (el) {
    el.textContent = msg;
    el.classList.add('active');
  }
}

function showToast(msg, type = 'success') {
  const toast = document.getElementById('toast');
  toast.textContent = msg;
  toast.className = `toast toast-${type} show`;
  setTimeout(() => toast.classList.remove('show'), 3500);
}

function escHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function formatDuration(seconds) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}h ${m}m ${s}s`;
  return `${m}m ${s}s`;
}

// ── Drag-over visual ────────────────────────────────────────────────────────
document.querySelectorAll('.file-drop').forEach(drop => {
  drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('dragover'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('dragover'));
  drop.addEventListener('drop', () => drop.classList.remove('dragover'));
});

// ── Health check on load ────────────────────────────────────────────────────
(async () => {
  try {
    const res = await fetch(`${API}/health`);
    const data = await res.json();
    const badge = document.querySelector('.header-badge');
    if (data.openai_configured) {
      badge.innerHTML = '<span class="status-dot"></span> AI Ready';
      badge.style.color = 'var(--success-green)';
    } else {
      badge.innerHTML = '<span class="status-dot"></span> Rule-based Mode';
      badge.title = 'Set OPENAI_API_KEY for AI-powered debriefs';
    }
  } catch {
    const badge = document.querySelector('.header-badge');
    badge.innerHTML = '⚠ API Offline';
    badge.style.borderColor = 'var(--critical-red)';
    badge.style.color = 'var(--critical-red)';
  }
})();
