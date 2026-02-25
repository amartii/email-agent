// Email Agent — ONEtoONE CF — app.js

const STATUS_LABELS = {
    pending:      "Pendiente",
    sent:         "Enviado",
    replied:      "Respondido",
    followup_sent:"Follow-up",
    bounced:      "Rebotado",
    running:      "En curso",
    paused:       "Pausado",
    error:        "Error",
    draft:        "Borrador",
};

function statusBadge(status) {
    const label = STATUS_LABELS[status] || status;
    return `<span class="badge-status badge-${status}">${label}</span>`;
}

// ── Step 1: Upload Excel ──────────────────────────────────────────────────────
const uploadForm = document.getElementById("uploadForm");
if (uploadForm) {
    uploadForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const fileInput = document.getElementById("excelFile");
        if (!fileInput.files[0]) return;

        const btn = document.getElementById("btnUpload");
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Procesando...';

        const formData = new FormData();
        formData.append("file", fileInput.files[0]);

        try {
            const res = await fetch("/api/upload", { method: "POST", body: formData });
            const data = await res.json();

            if (!res.ok) { showAlert(data.error || "Error al subir el archivo", "danger"); return; }

            localStorage.setItem("excel_path", data.excel_path);
            localStorage.setItem("excel_columns", JSON.stringify(data.columns));

            const nameCol  = document.getElementById("nameCol");
            const emailCol = document.getElementById("emailCol");
            nameCol.innerHTML  = "";
            emailCol.innerHTML = "";
            data.columns.forEach(col => {
                nameCol.add(new Option(col, col));
                emailCol.add(new Option(col, col));
            });

            selectLikelyColumn(nameCol,  ["nombre", "name", "contacto"]);
            selectLikelyColumn(emailCol, ["email", "correo", "mail"]);

            updateColPreview(data.columns);
            document.getElementById("columnMapping").classList.remove("d-none");
        } catch (err) {
            showAlert("Error de conexión: " + err.message, "danger");
        } finally {
            btn.disabled = false;
            btn.innerHTML = '<i class="bi bi-search me-2"></i>Detectar columnas';
        }
    });

    const nextBtn = document.getElementById("btnNext");
    if (nextBtn) {
        nextBtn.addEventListener("click", () => {
            const nameCol  = document.getElementById("nameCol").value;
            const emailCol = document.getElementById("emailCol").value;
            localStorage.setItem("name_col", nameCol);
            localStorage.setItem("email_col", emailCol);
            window.location.href = "/configure";
        });
    }

    // Update preview text when selects change
    ["nameCol","emailCol"].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener("change", () => {
            const cols = JSON.parse(localStorage.getItem("excel_columns") || "[]");
            updateColPreview(cols);
        });
    });
}

function updateColPreview(cols) {
    const preview = document.getElementById("colPreviewText");
    if (!preview) return;
    const nameVal  = document.getElementById("nameCol")?.value;
    const emailVal = document.getElementById("emailCol")?.value;
    const others   = cols.filter(c => c !== emailVal).map(c => `{{${c}}}`).join(", ");
    preview.textContent = `Variables disponibles: ${others || "—"}`;
}

function selectLikelyColumn(select, keywords) {
    for (const opt of select.options) {
        if (keywords.some(k => opt.value.toLowerCase().includes(k))) {
            select.value = opt.value;
            return;
        }
    }
}

// ── Step 2: Configure campaign ────────────────────────────────────────────────
const configForm = document.getElementById("configForm");
if (configForm) {
    const cols     = JSON.parse(localStorage.getItem("excel_columns") || "[]");
    const emailCol = localStorage.getItem("email_col") || "Email";
    const others   = cols.filter(c => c !== emailCol).map(c => `{{${c}}}`).join(", ");
    const hint     = document.getElementById("variablesHint");
    if (hint && others) hint.textContent = others;

    const btnTest = document.getElementById("btnTestCreds");
    if (btnTest) {
        btnTest.addEventListener("click", async () => {
            const email = configForm.querySelector('[name=sender_email]').value;
            const pass  = configForm.querySelector('[name=app_password]').value;
            if (!email || !pass) { showAlert("Introduce email y contraseña primero", "warning"); return; }
            btnTest.disabled = true;
            btnTest.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Comprobando...';
            try {
                const res  = await fetch("/api/test-credentials", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ sender_email: email, app_password: pass }),
                });
                const data = await res.json();
                showAlert(data.message, data.ok ? "success" : "danger");
            } finally {
                btnTest.disabled = false;
                btnTest.innerHTML = '<i class="bi bi-plug me-2"></i>Probar conexión';
            }
        });
    }

    configForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const btn = configForm.querySelector("button[type=submit]");
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Lanzando campaña...';

        const fd = new FormData(configForm);
        const payload = {
            excel_path: localStorage.getItem("excel_path"),
            name_col:   localStorage.getItem("name_col") || "Nombre",
            email_col:  localStorage.getItem("email_col") || "Email",
        };
        fd.forEach((v, k) => payload[k] = v);

        try {
            let res  = await fetch("/api/configure", {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            let data = await res.json();
            if (!res.ok) { showAlert(data.error, "danger"); return; }

            res  = await fetch("/api/launch", { method: "POST" });
            data = await res.json();
            if (!res.ok) { showAlert(data.error, "danger"); return; }

            showAlert(data.message, "success");
            setTimeout(() => window.location.href = "/dashboard", 1500);
        } catch (err) {
            showAlert("Error: " + err.message, "danger");
        } finally {
            btn.disabled = false;
            btn.innerHTML = '<i class="bi bi-send me-2"></i>Guardar y lanzar campaña';
        }
    });
}

// ── Step 3: Dashboard ─────────────────────────────────────────────────────────
let dashboardInterval = null;

async function loadDashboard() {
    try {
        const res  = await fetch("/api/status");
        const data = await res.json();

        if (!data.campaign) {
            document.getElementById("contactsTable").innerHTML =
                '<tr><td colspan="7" class="text-center py-5 text-muted">No hay ninguna campaña activa. <a href="/">Inicia una</a>.</td></tr>';
            return;
        }

        // Stats
        const s = data.stats || {};
        document.getElementById("statTotal").textContent   = s.total   ?? "—";
        document.getElementById("statSent").textContent    = (s.sent || 0) + (s.followup_sent || 0);
        document.getElementById("statReplied").textContent = s.replied ?? "—";
        document.getElementById("statPending").textContent = s.sent    ?? "—";

        // Title & status
        const titleEl = document.getElementById("campaignTitle");
        if (titleEl) titleEl.textContent = data.campaign.name;
        const statusEl = document.getElementById("campaignStatus");
        if (statusEl) statusEl.innerHTML = statusBadge(data.campaign.status);

        // Error banner
        const errBanner = document.getElementById("errorBanner");
        if (errBanner) {
            if (data.campaign.status === "error" && data.campaign.last_error) {
                document.getElementById("errorMsg").textContent = data.campaign.last_error;
                errBanner.classList.remove("d-none");
            } else {
                errBanner.classList.add("d-none");
            }
        }

        // Pause button
        const btnPause = document.getElementById("btnPause");
        if (btnPause) {
            btnPause.innerHTML = data.campaign.status === "running"
                ? '<i class="bi bi-pause-circle me-1"></i>Pausar'
                : '<i class="bi bi-play-circle me-1"></i>Reanudar';
        }

        // Table
        const tbody = document.getElementById("contactsTable");
        if (!data.contacts || !data.contacts.length) {
            tbody.innerHTML = '<tr><td colspan="7" class="text-center py-4 text-muted">Sin contactos cargados.</td></tr>';
        } else {
            tbody.innerHTML = data.contacts.map(c => `
                <tr>
                    <td class="fw-500">${esc(c.name)}</td>
                    <td style="color:var(--oto-muted)">${esc(c.email)}</td>
                    <td>${statusBadge(c.status)}</td>
                    <td style="color:var(--oto-muted)">${c.email_sent_at    ? fmt(c.email_sent_at)    : "—"}</td>
                    <td style="color:var(--oto-muted)">${c.replied_at       ? fmt(c.replied_at)       : "—"}</td>
                    <td style="color:var(--oto-muted)">${c.followup_sent_at ? fmt(c.followup_sent_at) : "—"}</td>
                    <td style="color:#991b1b;font-size:0.78rem">${c.send_error ? esc(c.send_error) : ""}</td>
                </tr>`).join("");
        }
    } catch (err) {
        console.error("Dashboard refresh error:", err);
    }
}

if (document.getElementById("contactsTable")) {
    loadDashboard();
    dashboardInterval = setInterval(loadDashboard, 30000);

    // Live clock — updates every second
    const clockEl = document.getElementById("lastUpdated");
    if (clockEl) {
        setInterval(() => {
            clockEl.textContent = "· " + new Date().toLocaleTimeString("es-ES");
        }, 1000);
    }

    const btnPause = document.getElementById("btnPause");
    if (btnPause) {
        btnPause.addEventListener("click", async () => {
            await fetch("/api/pause", { method: "POST" });
            loadDashboard();
        });
    }

    const btnReset = document.getElementById("btnReset");
    if (btnReset) {
        btnReset.addEventListener("click", async () => {
            if (!confirm("¿Archivar la campaña actual y empezar de nuevo?")) return;
            await fetch("/api/reset", { method: "POST" });
            window.location.href = "/";
        });
    }
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function esc(str) {
    if (!str) return "";
    return String(str).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

function fmt(isoStr) {
    if (!isoStr) return "—";
    const d = new Date(isoStr);
    return d.toLocaleString("es-ES", { day:"2-digit", month:"2-digit", year:"2-digit", hour:"2-digit", minute:"2-digit" });
}

function showAlert(msg, type = "info") {
    const container = document.getElementById("alertContainer");
    if (!container) { alert(msg); return; }
    const id = "alert_" + Date.now();
    container.insertAdjacentHTML("beforeend", `
        <div id="${id}" class="alert alert-${type} alert-dismissible fade show" role="alert">
            ${esc(msg)}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>`);
    setTimeout(() => document.getElementById(id)?.remove(), 6000);
}
