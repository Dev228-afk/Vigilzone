// VigilZone AI - Frontend JavaScript (v3)
// Supports: session_id, lane_votes, temporal_verifier, live camera frames,
//           upload mode, entity enrollment, identity live state, entity-aware alerts

let alerts = [];
let ws = null;
let activeFilter = "ALL";
let activeMode = "realtime";
let activeTab = "alerts";
let cameraRefreshInterval = null;
let jobsRefreshInterval = null;
let idLiveInterval = null;
let cachedCameras = [];

// ─── Init ────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    loadAlerts();
    loadCameras();
    connectWebSocket();
    setupFilterButtons();

    // Refresh alerts & cameras periodically as fallback
    setInterval(loadAlerts, 10000);
    cameraRefreshInterval = setInterval(refreshCameraFrames, 2000);
    setInterval(loadCameras, 15000);
});

// ─── Tab Navigation ──────────────────────────────────────────────────
function switchTab(tab) {
    activeTab = tab;
    document.querySelectorAll(".tab-btn").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.tab === tab);
    });
    document.querySelectorAll(".tab-content").forEach(el => {
        el.classList.toggle("active", el.id === "tab-" + tab);
    });

    // Tab-specific actions
    if (tab === "entities") {
        loadEntities();
    } else if (tab === "idlive") {
        populateIdLiveCameras();
    }

    // Stop identity live polling when leaving tab
    if (tab !== "idlive" && idLiveInterval) {
        clearInterval(idLiveInterval);
        idLiveInterval = null;
    }
}

// ─── Filter Buttons ──────────────────────────────────────────────────
function setupFilterButtons() {
    document.querySelectorAll(".filter-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".filter-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            activeFilter = btn.dataset.filter;
            renderAlerts();
        });
    });
}

// ─── Load alerts from REST API ───────────────────────────────────────
async function loadAlerts() {
    try {
        const resp = await fetch("/alerts?limit=200");
        if (!resp.ok) return;
        alerts = await resp.json();
        renderAlerts();
        updateStats();
    } catch (e) {
        console.error("Failed to load alerts:", e);
    }
}

// ─── Load cameras sidebar ────────────────────────────────────────────
async function loadCameras() {
    try {
        const resp = await fetch("/cameras");
        if (!resp.ok) return;
        const cameras = await resp.json();
        cachedCameras = cameras || [];
        renderCameras(cachedCameras);
    } catch (e) {
        console.error("Failed to load cameras:", e);
    }
}

function renderCameras(cameras) {
    const container = document.getElementById("camera-list");
    if (!cameras || cameras.length === 0) {
        container.innerHTML = '<div style="color:#555;font-size:12px">No cameras connected</div>';
        return;
    }
    container.innerHTML = cameras.map(cam => {
        const srcType = cam.source_type || "unknown";
        return `
        <div class="cam-card" data-cam="${cam.camera_id}">
            <div class="cam-frame">
                <img src="/frame/${cam.camera_id}?t=${Date.now()}"
                     onerror="this.style.display='none';this.nextElementSibling.style.display='flex'"
                     alt="${cam.camera_id}">
                <div class="offline" style="display:none">OFFLINE</div>
            </div>
            <div class="cam-label">
                <span class="name">${cam.camera_id}</span>
                <span class="type-badge">${srcType}</span>
            </div>
        </div>`;
    }).join("");
}

function refreshCameraFrames() {
    document.querySelectorAll(".cam-frame img").forEach(img => {
        const src = img.getAttribute("src");
        if (src) {
            const base = src.split("?")[0];
            img.setAttribute("src", base + "?t=" + Date.now());
            img.style.display = "";
            img.nextElementSibling.style.display = "none";
        }
    });
}

// ─── WebSocket ───────────────────────────────────────────────────────
function connectWebSocket() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${proto}//${location.host}/ws`);

    ws.onopen = () => {
        document.getElementById("ws-status").textContent = "Connected";
        document.getElementById("ws-status").style.color = "#4CAF50";
    };

    ws.onmessage = (ev) => {
        try {
            const alert = JSON.parse(ev.data);
            alerts.push(alert);
            if (alerts.length > 300) alerts = alerts.slice(-300);
            renderAlerts();
            updateStats();
            showNotification(alert);
        } catch (e) {
            console.error("WS parse error:", e);
        }
    };

    ws.onerror = () => {
        document.getElementById("ws-status").textContent = "Error";
        document.getElementById("ws-status").style.color = "#F44336";
    };

    ws.onclose = () => {
        document.getElementById("ws-status").textContent = "Reconnecting...";
        document.getElementById("ws-status").style.color = "#FF9800";
        setTimeout(connectWebSocket, 5000);
    };
}

// ─── Render alerts ───────────────────────────────────────────────────
function renderAlerts() {
    const container = document.getElementById("alerts-list");
    let filtered = [...alerts];
    if (activeFilter !== "ALL") {
        filtered = filtered.filter(a => a.severity === activeFilter);
    }

    if (filtered.length === 0) {
        container.innerHTML = '<div class="no-alerts">No alerts yet. System is monitoring...</div>';
        return;
    }

    // Newest first
    filtered.reverse();

    container.innerHTML = filtered.map((alert, i) => {
        const time = new Date(alert.ts_utc).toLocaleString();
        const typeCls = (alert.type || "").replace(/\s/g, "_");
        const sessionHtml = alert.session_id
            ? `<div><strong>Session:</strong> <span class="session-id">${alert.session_id}</span></div>`
            : "";

        // Lane votes
        const votes = alert.payload && alert.payload.lane_votes;
        let votesHtml = "";
        if (votes && Array.isArray(votes) && votes.length) {
            votesHtml = `<div class="lane-votes">${votes.map(v => {
                const pos = v.conf > 0 ? "positive" : "";
                return `<span class="lane-vote ${pos}">${v.lane} ${(v.conf * 100).toFixed(0)}%</span>`;
            }).join("")}</div>`;
        }

        // Temporal verifier
        const tv = alert.payload && alert.payload.temporal_verifier;
        let tvHtml = "";
        if (tv && tv.ran) {
            const cls = tv.confirmed ? "confirmed" : "denied";
            const icon = tv.confirmed ? "&#10003;" : "&#10007;";
            tvHtml = `<span class="temporal-badge ${cls}">${icon} Temporal ${(tv.score * 100).toFixed(0)}%</span>`;
        } else {
            tvHtml = `<span class="temporal-badge na">-- no temporal --</span>`;
        }

        // Partial clip badge
        const partial = alert.evidence && alert.evidence.partial_clip;
        const partialHtml = partial ? `<span class="partial-badge">PARTIAL CLIP</span>` : "";

        const realIdx = alerts.indexOf(alert);

        // Entity identity badge (name + category + confidence)
        const ent = alert.entity || {};
        let entityHtml = "";
        if (ent.id) {
            const ekind = (ent.category || "").startsWith("UNKNOWN") ? "unknown" : "known";
            const eName = ent.name || ent.category || "Entity";
            const eCat = ent.category || "";
            const eConf = ((ent.confidence || 0) * 100).toFixed(0);
            entityHtml = `<div><span class="entity-badge ${ekind}">${eName} &middot; ${eCat} &middot; ${eConf}%</span></div>`;
        }

        // Identity debug info (best_sim, margin, quality_ok, locked)
        const idDebug = alert.payload && alert.payload.identity;
        let idDebugHtml = "";
        if (idDebug) {
            const parts = [];
            if (idDebug.best_sim != null) parts.push(`sim:${(idDebug.best_sim * 100).toFixed(0)}%`);
            if (idDebug.margin != null) parts.push(`margin:${(idDebug.margin * 100).toFixed(0)}%`);
            if (idDebug.quality_ok != null) parts.push(`quality:${idDebug.quality_ok ? "OK" : "LOW"}`);
            if (idDebug.locked != null) parts.push(`locked:${idDebug.locked ? "yes" : "no"}`);
            if (parts.length) {
                idDebugHtml = `<div class="identity-debug">${parts.join(" | ")}</div>`;
            }
        }

        return `
        <div class="alert-card ${alert.severity}" onclick="showAlertDetails(${realIdx >= 0 ? realIdx : i})">
            <div class="alert-top">
                <div class="alert-type-label ${typeCls}">${fmtType(alert.type)}</div>
                <div class="sev-badge ${alert.severity}">${alert.severity}</div>
            </div>
            <div class="alert-body">
                <div><strong>Camera:</strong> ${alert.camera_id}</div>
                <div><strong>Confidence:</strong> ${(alert.confidence * 100).toFixed(1)}%</div>
                <div><strong>K-of-N:</strong> ${alert.k_of_n.hits}/${alert.k_of_n.n}</div>
                ${entityHtml}
                ${idDebugHtml}
                ${sessionHtml}
                <div>${tvHtml}${partialHtml}</div>
                ${votesHtml}
            </div>
            <div class="alert-time">${time}</div>
        </div>`;
    }).join("");
}

// ─── Stats ───────────────────────────────────────────────────────────
function updateStats() {
    document.getElementById("total-alerts").textContent = alerts.length;
    document.getElementById("severe-count").textContent = alerts.filter(a => a.severity === "SEVERE").length;
    document.getElementById("high-count").textContent = alerts.filter(a => a.severity === "HIGH").length;
    document.getElementById("med-count").textContent = alerts.filter(a => a.severity === "MED").length;
}

// ─── Helpers ─────────────────────────────────────────────────────────
function fmtType(t) { return (t || "UNKNOWN").replace(/_/g, " "); }

// ─── Modal Detail View ──────────────────────────────────────────────
function showAlertDetails(index) {
    const alert = alerts[index];
    if (!alert) return;
    const modal = document.getElementById("alert-modal");
    document.getElementById("modal-title").textContent =
        `${fmtType(alert.type)} - ${alert.camera_id}`;

    const time = new Date(alert.ts_utc).toLocaleString();
    const p = alert.payload || {};
    const ev = alert.evidence || {};

    // Evidence media
    let evidenceHtml = "";
    if (ev.keyframe_path) {
        const fn = ev.keyframe_path.replace(/\\/g, "/").split("/").pop();
        evidenceHtml += `
        <div class="modal-section">
            <h3>Keyframe</h3>
            <div class="evidence-media">
                <img src="/evidence/${alert.camera_id}/${fn}"
                     alt="Keyframe"
                     onerror="this.alt='Image not available';this.style.opacity=0.3">
            </div>
        </div>`;
    }
    if (ev.clip_path) {
        const fn = ev.clip_path.replace(/\\/g, "/").split("/").pop();
        evidenceHtml += `
        <div class="modal-section">
            <h3>Video Clip ${ev.partial_clip ? '<span class="partial-badge">PARTIAL</span>' : ""}</h3>
            <div class="evidence-media">
                <video controls><source src="/evidence/${alert.camera_id}/${fn}" type="video/mp4"></video>
            </div>
        </div>`;
    }

    // Lane votes table
    const votes = p.lane_votes || [];
    let votesTable = "";
    if (votes.length) {
        votesTable = `
        <div class="modal-section">
            <h3>Lane Votes</h3>
            <table style="width:100%;font-size:13px;color:#bbb;border-collapse:collapse">
                <tr style="color:#64B5F6;text-align:left"><th style="padding:4px 8px">Lane</th><th style="padding:4px 8px">Confidence</th></tr>
                ${votes.map(v => `<tr><td style="padding:4px 8px">${v.lane}</td><td style="padding:4px 8px">${(v.conf * 100).toFixed(1)}%</td></tr>`).join("")}
            </table>
        </div>`;
    }

    // Temporal verifier section
    const tv = p.temporal_verifier || {};
    let tvSection = "";
    if (tv.ran) {
        tvSection = `
        <div class="modal-section">
            <h3>Temporal Verifier</h3>
            <div class="detail-grid">
                <div><strong>Confirmed:</strong> ${tv.confirmed ? "Yes" : "No"}</div>
                <div><strong>Score:</strong> ${(tv.score * 100).toFixed(1)}%</div>
            </div>
        </div>`;
    }

    // Identity debug section in modal
    const idDebug = p.identity || {};
    let idDebugSection = "";
    if (Object.keys(idDebug).length > 0) {
        idDebugSection = `
        <div class="modal-section">
            <h3>Identity Debug</h3>
            <div class="detail-grid">
                ${idDebug.best_sim != null ? `<div><strong>Best Sim:</strong> ${(idDebug.best_sim * 100).toFixed(1)}%</div>` : ""}
                ${idDebug.margin != null ? `<div><strong>Margin:</strong> ${(idDebug.margin * 100).toFixed(1)}%</div>` : ""}
                ${idDebug.quality_ok != null ? `<div><strong>Quality OK:</strong> ${idDebug.quality_ok ? "Yes" : "No"}</div>` : ""}
                ${idDebug.locked != null ? `<div><strong>Locked:</strong> ${idDebug.locked ? "Yes" : "No"}</div>` : ""}
                ${idDebug.track_id != null ? `<div><strong>Track ID:</strong> ${idDebug.track_id}</div>` : ""}
                ${idDebug.entity_id != null ? `<div><strong>Entity ID:</strong> ${idDebug.entity_id}</div>` : ""}
            </div>
        </div>`;
    }

    document.getElementById("modal-body").innerHTML = `
        <div class="modal-section">
            <h3>Details</h3>
            <div class="detail-grid">
                <div><strong>Time:</strong> ${time}</div>
                <div><strong>Type:</strong> ${fmtType(alert.type)}</div>
                <div><strong>Severity:</strong> ${alert.severity}</div>
                <div><strong>Confidence:</strong> ${(alert.confidence * 100).toFixed(1)}%</div>
                <div><strong>Camera:</strong> ${alert.camera_id}</div>
                <div><strong>K-of-N:</strong> ${alert.k_of_n.hits}/${alert.k_of_n.n}</div>
                <div><strong>Cooldown:</strong> ${alert.cooldown_s}s</div>
                ${alert.session_id ? `<div><strong>Session:</strong> <span class="session-id">${alert.session_id}</span></div>` : ""}
                ${alert.label ? `<div><strong>Label:</strong> ${alert.label}</div>` : ""}
                ${p.zone_name ? `<div><strong>Zone:</strong> ${p.zone_name}</div>` : ""}
                ${p.track_id ? `<div><strong>Track ID:</strong> ${p.track_id}</div>` : ""}
                ${p.bboxes ? `<div><strong>Bboxes:</strong> ${JSON.stringify(p.bboxes)}</div>` : ""}
            </div>
        </div>
        ${(() => { const e = alert.entity || {}; if (!e.id) return ""; return `
        <div class="modal-section">
            <h3>Identity</h3>
            <div class="detail-grid">
                <div><strong>Entity ID:</strong> ${e.id}</div>
                <div><strong>Name:</strong> ${e.name || "N/A"}</div>
                <div><strong>Category:</strong> ${e.category || "N/A"}</div>
                <div><strong>Match Confidence:</strong> ${((e.confidence || 0) * 100).toFixed(1)}%</div>
            </div>
        </div>`; })()}
        ${idDebugSection}
        ${evidenceHtml}
        ${votesTable}
        ${tvSection}
        <div class="json-viewer">
            <h3>Full Alert JSON</h3>
            <pre>${JSON.stringify(alert, null, 2)}</pre>
        </div>`;

    modal.classList.add("active");
}

function closeModal() {
    document.getElementById("alert-modal").classList.remove("active");
}

window.onclick = (ev) => {
    const modal = document.getElementById("alert-modal");
    if (ev.target === modal) closeModal();
};

// ─── Browser Notification ────────────────────────────────────────────
function showNotification(alert) {
    if (!("Notification" in window)) return;
    if (Notification.permission === "granted") {
        new Notification(`${fmtType(alert.type)}`, {
            body: `Camera: ${alert.camera_id} | ${alert.severity} | ${(alert.confidence * 100).toFixed(0)}%`,
        });
    } else if (Notification.permission !== "denied") {
        Notification.requestPermission();
    }
}

// ─── FP Debug Panel ──────────────────────────────────────────────────
let fpDebugActive = false;
let fpDebugInterval = null;

function toggleFireDebug() {
    fpDebugActive = !fpDebugActive;
    const btn = document.getElementById("fp-debug-btn");
    const panel = document.getElementById("fp-debug-panel");

    btn.classList.toggle("active", fpDebugActive);
    panel.classList.toggle("visible", fpDebugActive);

    if (fpDebugActive) {
        loadFireDebug();
        fpDebugInterval = setInterval(loadFireDebug, 3000);
    } else {
        if (fpDebugInterval) { clearInterval(fpDebugInterval); fpDebugInterval = null; }
    }
}

async function loadFireDebug() {
    try {
        const resp = await fetch("/fire_debug");
        if (!resp.ok) {
            document.getElementById("fp-debug-content").innerHTML =
                '<div class="fp-debug-empty">Endpoint unavailable</div>';
            return;
        }
        const data = await resp.json();
        renderFireDebug(data);
    } catch (e) {
        console.error("Fire debug fetch failed:", e);
    }
}

function renderFireDebug(data) {
    document.getElementById("fp-debug-ts").textContent = new Date().toLocaleTimeString();

    if (!data || Object.keys(data).length === 0) {
        document.getElementById("fp-debug-content").innerHTML =
            '<div class="fp-debug-empty">No fire lane data available</div>';
        return;
    }

    let html = "";
    for (const [camId, info] of Object.entries(data)) {
        const statusClass = info.active ? "active" : "disabled";
        const statusText = info.active ? "ACTIVE" : "DISABLED";

        html += `<div class="fp-debug-cam">
            <div class="fp-debug-cam-label">
                ${camId}
                <span class="fp-debug-status ${statusClass}">${statusText}</span>
            </div>`;

        const dets = info.last_debug_detections || [];
        if (dets.length === 0) {
            html += '<div class="fp-debug-empty">No recent detections</div>';
        } else {
            html += `<table class="fp-debug-table">
                <tr>
                    <th>Class</th>
                    <th>Conf</th>
                    <th>Area (px)</th>
                    <th>Area Ratio</th>
                    <th>Status</th>
                </tr>`;
            for (const d of dets) {
                const conf = d.conf != null ? d.conf : 0;
                const confClass = conf >= 0.5 ? "high" : conf >= 0.3 ? "med" : "low";
                const area = d.area_px != null ? d.area_px.toFixed(0) : "—";
                const ratio = d.area_ratio != null ? (d.area_ratio * 100).toFixed(3) + "%" : "—";
                const cls = d.class_name || d.cls || "?";
                const kept = d.kept !== undefined ? (d.kept ? "✓ Kept" : "✗ Dropped") : "—";
                const reason = d.reason || "";
                const statusText = reason ? `${kept} (${reason})` : kept;

                html += `<tr>
                    <td>${cls}</td>
                    <td class="fp-debug-conf ${confClass}">${(conf * 100).toFixed(1)}%</td>
                    <td>${area}</td>
                    <td>${ratio}</td>
                    <td>${statusText}</td>
                </tr>`;
            }
            html += '</table>';
        }
        html += '</div>';
    }

    document.getElementById("fp-debug-content").innerHTML = html;
}

// ─── Mode Toggle (Realtime / Upload) ─────────────────────────────────
function setMode(mode) {
    activeMode = mode;
    document.querySelectorAll(".mode-btn").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.mode === mode);
    });

    const uploadPanel = document.getElementById("upload-panel");
    if (mode === "upload") {
        uploadPanel.style.display = "block";
        loadJobs();
        if (!jobsRefreshInterval) {
            jobsRefreshInterval = setInterval(loadJobs, 3000);
        }
    } else {
        uploadPanel.style.display = "none";
        if (jobsRefreshInterval) {
            clearInterval(jobsRefreshInterval);
            jobsRefreshInterval = null;
        }
    }
}

// ─── Upload Video ────────────────────────────────────────────────────
async function uploadVideo() {
    const fileInput = document.getElementById("upload-file");
    const forceAA = document.getElementById("force-anyanomaly").checked;
    const btn = document.getElementById("upload-btn");

    if (!fileInput.files || !fileInput.files[0]) {
        alert("Please select a video file");
        return;
    }

    btn.disabled = true;
    btn.textContent = "Uploading...";

    const formData = new FormData();
    formData.append("file", fileInput.files[0]);

    try {
        const resp = await fetch(`/upload_video?force_anyanomaly=${forceAA}`, {
            method: "POST",
            body: formData,
        });
        const data = await resp.json();
        if (data.job_id) {
            loadJobs();
        }
    } catch (e) {
        console.error("Upload failed:", e);
    } finally {
        btn.disabled = false;
        btn.textContent = "Upload & Process";
        fileInput.value = "";
    }
}

// ─── Jobs List ───────────────────────────────────────────────────────
async function loadJobs() {
    try {
        const resp = await fetch("/jobs");
        if (!resp.ok) return;
        const jobs = await resp.json();
        renderJobs(jobs);
    } catch (e) {
        console.error("Failed to load jobs:", e);
    }
}

function renderJobs(jobs) {
    const container = document.getElementById("jobs-list");
    if (!jobs || jobs.length === 0) {
        container.innerHTML = '<div style="color:#555;padding:8px">No upload jobs</div>';
        return;
    }

    container.innerHTML = jobs.map(job => {
        const progress = job.progress || 0;
        return `
        <div class="job-item">
            <div>
                <strong style="color:#ccc">${job.filename || job.job_id}</strong>
                <span style="color:#777;margin-left:8px">${job.job_id}</span>
            </div>
            <div style="display:flex;align-items:center;gap:8px">
                ${job.status === "processing" ? `
                    <div class="job-progress">
                        <div class="job-progress-fill" style="width:${progress}%"></div>
                    </div>
                    <span style="color:#aaa;font-size:10px">${progress.toFixed(0)}%</span>
                ` : ""}
                <span class="job-status ${job.status}">${job.status}</span>
                ${job.alerts_count > 0 ? `<span style="color:#4CAF50;font-size:11px">${job.alerts_count} alerts</span>` : ""}
                ${job.status === "completed" ? `<button onclick="viewJobAlerts('${job.job_id}')" style="font-size:11px;padding:2px 8px;border:1px solid #3a3a6e;background:transparent;color:#64B5F6;border-radius:4px;cursor:pointer">View</button>` : ""}
            </div>
        </div>`;
    }).join("");
}

async function viewJobAlerts(jobId) {
    try {
        const resp = await fetch(`/jobs/${jobId}/alerts`);
        if (!resp.ok) return;
        const jobAlerts = await resp.json();
        alerts = jobAlerts;
        renderAlerts();
        updateStats();
    } catch (e) {
        console.error("Failed to load job alerts:", e);
    }
}

// ═══════════════════════════════════════════════════════════════════════
// ENTITIES TAB — Enrollment + List + Delete
// ═══════════════════════════════════════════════════════════════════════

async function loadEntities() {
    const container = document.getElementById("entities-list");
    try {
        const resp = await fetch("/entities");
        if (!resp.ok) {
            container.innerHTML = '<div class="no-entities">Identity subsystem not available.</div>';
            return;
        }
        const data = await resp.json();
        if (data.error) {
            container.innerHTML = `<div class="no-entities">${data.error}</div>`;
            return;
        }
        const entities = Array.isArray(data) ? data : [];
        if (entities.length === 0) {
            container.innerHTML = '<div class="no-entities">No entities enrolled yet. Use the buttons above to enroll persons or pets.</div>';
            return;
        }
        container.innerHTML = entities.map(e => {
            const catClass = (e.category || "").includes("PET") ? "PET" : "";
            return `
            <div class="entity-card ${catClass}">
                <div class="entity-name">${e.name || "Unnamed"}</div>
                <div class="entity-meta">
                    <div><strong>ID:</strong> ${e.entity_id || e.id || "—"}</div>
                    <div><strong>Category:</strong> ${e.category || "—"}</div>
                    <div><strong>Role:</strong> ${e.role || "—"}</div>
                </div>
                <button class="entity-del-btn" onclick="deleteEntity('${e.entity_id || e.id}')">Delete</button>
            </div>`;
        }).join("");
    } catch (e) {
        console.error("Failed to load entities:", e);
        container.innerHTML = '<div class="no-entities">Error loading entities.</div>';
    }
}

function showEnrollForm(type) {
    hideEnrollForms();
    const form = document.getElementById(`enroll-${type}-form`);
    if (form) form.classList.add("visible");
}

function hideEnrollForms() {
    document.querySelectorAll(".enroll-form").forEach(f => f.classList.remove("visible"));
    // Clear status messages
    document.querySelectorAll(".enroll-status").forEach(el => {
        el.className = "enroll-status";
        el.textContent = "";
    });
}

async function submitEnroll(type) {
    const statusEl = document.getElementById(`enroll-${type}-status`);
    const nameEl = document.getElementById(`enroll-${type}-name`);
    const filesEl = document.getElementById(`enroll-${type}-files`);

    const name = nameEl.value.trim();
    if (!name) {
        statusEl.className = "enroll-status error";
        statusEl.textContent = "Name is required.";
        return;
    }
    if (!filesEl.files || filesEl.files.length === 0) {
        statusEl.className = "enroll-status error";
        statusEl.textContent = "At least one image is required.";
        return;
    }

    const formData = new FormData();
    formData.append("name", name);
    for (const f of filesEl.files) {
        formData.append("files", f);
    }

    if (type === "person") {
        const roleEl = document.getElementById("enroll-person-role");
        formData.append("role", roleEl.value);
    }

    statusEl.className = "enroll-status";
    statusEl.style.display = "block";
    statusEl.style.background = "#333";
    statusEl.style.color = "#aaa";
    statusEl.textContent = "Enrolling...";

    const endpoint = type === "person" ? "/entities/enroll_person" : "/entities/enroll_pet";

    try {
        const resp = await fetch(endpoint, { method: "POST", body: formData });
        const data = await resp.json();

        if (data.error) {
            statusEl.className = "enroll-status error";
            statusEl.textContent = data.error;
            return;
        }

        statusEl.className = "enroll-status success";
        statusEl.textContent = `Enrolled "${data.name}" (${data.category}) — ${data.embeddings_stored || 0} embeddings stored.`;

        // Reload matcher indices
        await fetch("/identity/reload", { method: "POST" });

        // Reset form
        nameEl.value = "";
        filesEl.value = "";

        // Refresh entities list
        loadEntities();
    } catch (e) {
        console.error("Enrollment failed:", e);
        statusEl.className = "enroll-status error";
        statusEl.textContent = "Network error during enrollment.";
    }
}

async function deleteEntity(entityId) {
    if (!confirm(`Delete entity ${entityId}? This cannot be undone.`)) return;
    try {
        const resp = await fetch(`/entities/${entityId}`, { method: "DELETE" });
        const data = await resp.json();
        if (data.error) {
            alert(data.error);
            return;
        }
        // Reload matcher
        await fetch("/identity/reload", { method: "POST" });
        loadEntities();
    } catch (e) {
        console.error("Delete failed:", e);
        alert("Failed to delete entity.");
    }
}

// ═══════════════════════════════════════════════════════════════════════
// IDENTITY LIVE TAB — Per-track identity state polling
// ═══════════════════════════════════════════════════════════════════════

function populateIdLiveCameras() {
    const sel = document.getElementById("idlive-camera");
    // Preserve current selection
    const current = sel.value;
    // Clear options except default
    sel.innerHTML = '<option value="">-- Select Camera --</option>';
    for (const cam of cachedCameras) {
        const opt = document.createElement("option");
        opt.value = cam.camera_id;
        opt.textContent = cam.camera_id;
        sel.appendChild(opt);
    }
    if (current) {
        sel.value = current;
    }
}

function onIdLiveCameraChange() {
    const camId = document.getElementById("idlive-camera").value;

    // Stop existing polling
    if (idLiveInterval) {
        clearInterval(idLiveInterval);
        idLiveInterval = null;
    }

    if (!camId) {
        document.getElementById("idlive-content").innerHTML =
            '<div class="idlive-empty">Select a camera to view per-track identity states.</div>';
        document.getElementById("idlive-status").textContent = "Not polling";
        return;
    }

    // Start polling every 1.5s
    document.getElementById("idlive-status").textContent = "Polling...";
    loadIdLiveState(camId);
    idLiveInterval = setInterval(() => loadIdLiveState(camId), 1500);
}

async function loadIdLiveState(camId) {
    try {
        const resp = await fetch(`/identity/state?camera_id=${encodeURIComponent(camId)}`);
        if (!resp.ok) {
            document.getElementById("idlive-content").innerHTML =
                '<div class="idlive-empty">Identity state endpoint unavailable.</div>';
            return;
        }
        const data = await resp.json();
        if (data.error) {
            document.getElementById("idlive-content").innerHTML =
                `<div class="idlive-empty">${data.error}</div>`;
            return;
        }
        renderIdLiveState(data);
    } catch (e) {
        console.error("Identity live fetch failed:", e);
    }
}

function renderIdLiveState(data) {
    const tracks = data.tracks || {};
    const trackKeys = Object.keys(tracks);
    const statusEl = document.getElementById("idlive-status");
    statusEl.textContent = `Polling — ${trackKeys.length} track(s)`;

    if (trackKeys.length === 0) {
        document.getElementById("idlive-content").innerHTML =
            '<div class="idlive-empty">No active tracks for this camera.</div>';
        return;
    }

    let html = `<table class="idlive-table">
        <thead><tr>
            <th>Track ID</th>
            <th>Name</th>
            <th>Category</th>
            <th>Confidence</th>
            <th>Best Sim</th>
            <th>Margin</th>
            <th>Locked Until</th>
        </tr></thead><tbody>`;

    for (const [trackId, t] of Object.entries(tracks)) {
        const conf = t.confidence != null ? (t.confidence * 100).toFixed(0) + "%" : "—";
        const confClass = t.confidence != null ? (t.confidence >= 0.7 ? "high" : t.confidence >= 0.4 ? "med" : "low") : "";
        const bestSim = t.best_sim != null ? (t.best_sim * 100).toFixed(1) + "%" : "—";
        const margin = t.margin != null ? (t.margin * 100).toFixed(1) + "%" : "—";
        const locked = t.locked_until || "—";
        const name = t.name || t.entity_name || "—";
        const cat = t.category || "—";

        html += `<tr>
            <td>${trackId}</td>
            <td>${name}</td>
            <td>${cat}</td>
            <td class="conf-cell ${confClass}">${conf}</td>
            <td>${bestSim}</td>
            <td>${margin}</td>
            <td>${locked}</td>
        </tr>`;
    }

    html += "</tbody></table>";
    document.getElementById("idlive-content").innerHTML = html;
}
