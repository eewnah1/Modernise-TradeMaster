const API = "";
let charts = {};
let state = {
  datasets: [],
  agents: [],
  envs: [],
  experiments: [],
  selectedJobId: null,
  selectedResultJobId: null,
  selectedResource: null,
  tailLines: 200,
};

// Helpers
async function getJSON(path) {
  const r = await fetch(API + path);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

async function postJSON(path, body) {
  const r = await fetch(API + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const text = await r.text();
  if (!r.ok) throw new Error(text);
  try { return JSON.parse(text); } catch { return { message: text }; }
}

function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 4000);
}

function formatBytes(b) {
  if (b < 1024) return `${b} B`;
  const kb = b / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  return `${(kb / 1024).toFixed(2)} MB`;
}

function formatTime(ts) {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString();
}

// Navigation
document.querySelectorAll(".nav-item").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".nav-item").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(btn.dataset.tab).classList.add("active");
    document.getElementById("page-title").textContent = btn.querySelector("span").textContent;
    if (btn.dataset.tab === "jobs") loadJobs();
    if (btn.dataset.tab === "results") loadResultsJobs();
    if (btn.dataset.tab === "resources") loadResources();
  });
});

function switchTab(name) {
  document.querySelector(`.nav-item[data-tab="${name}"]`).click();
}

async function init() {
  refreshHealth();
  setInterval(refreshHealth, 5000);
  document.getElementById("refresh-all").addEventListener("click", refreshAll);

  const [datasets, agents, envs, experiments, system] = await Promise.all([
    getJSON("/api/v1/datasets"),
    getJSON("/api/v1/agents"),
    getJSON("/api/v1/envs"),
    getJSON("/api/v1/experiments"),
    getJSON("/api/v1/system"),
  ]).catch((e) => {
    setStatus("error", "offline");
    showToast(`Dashboard API error: ${e.message}`, "error");
    return [[], [], [], [], {}];
  });

  state.datasets = datasets;
  state.agents = agents;
  state.envs = envs;
  state.experiments = experiments;

  populateSelect("demo-data", datasets, (d) => `${d.universe} / ${d.name}`, (d) => d.path);
  populateSelect("exp-script", experiments, (e) => `${e.task} / ${e.agent}`, (e) => e.path);

  updateHomeStats(agents, envs, datasets, system);
  setStatus("ok", "online");

  // Event bindings
  document.getElementById("run-demo").addEventListener("click", runDemo);
  document.getElementById("run-experiment").addEventListener("click", runExperiment);
  document.getElementById("refresh-jobs").addEventListener("click", loadJobs);
  document.getElementById("result-job").addEventListener("change", (e) => loadResult(e.target.value));
  document.getElementById("tail-50").addEventListener("click", () => { state.tailLines = 50; showLog(); });
  document.getElementById("tail-500").addEventListener("click", () => { state.tailLines = 500; showLog(); });

  // Polling
  setInterval(() => {
    if (document.getElementById("jobs").classList.contains("active")) loadJobs();
    if (document.getElementById("results").classList.contains("active")) loadResultsJobs();
  }, 2000);
}

function populateSelect(id, items, labelFn, valueFn) {
  const sel = document.getElementById(id);
  sel.innerHTML = "";
  if (items.length === 0) {
    sel.innerHTML = "<option disabled>None available</option>";
    return;
  }
  items.forEach((item) => {
    const opt = document.createElement("option");
    opt.value = valueFn(item);
    opt.textContent = labelFn(item);
    sel.appendChild(opt);
  });
}

function setStatus(cls, text) {
  const pill = document.getElementById("status-pill");
  const txt = document.getElementById("status-text");
  pill.className = `status-pill ${cls}`;
  txt.textContent = text;
}

async function refreshHealth() {
  try {
    const h = await getJSON("/health");
    setStatus("ok", `online · ${h.active_jobs || 0} running`);
    const activeEl = document.getElementById("stat-active");
    if (activeEl) activeEl.textContent = h.active_jobs || 0;
  } catch (e) {
    setStatus("error", "offline");
  }
}

function updateHomeStats(agents, envs, datasets, system) {
  document.getElementById("stat-agents").textContent = agents.length;
  document.getElementById("stat-envs").textContent = envs.length;
  document.getElementById("stat-datasets").textContent = datasets.length;

  const mem = system.memory_gb || {};
  document.getElementById("stat-mem").textContent = mem.available_gb != null ? `${mem.available_gb} GB` : "—";
  document.getElementById("stat-mem-sub").innerHTML = mem.total_gb ? `of ${mem.total_gb} GB total` : "available";

  const load = system.load || {};
  document.getElementById("stat-load").textContent = load["1m"] != null ? load["1m"] : "—";

  const disk = system.disk || {};
  document.getElementById("stat-disk").textContent = disk.free_gb != null ? `${disk.free_gb} GB` : "—";

  document.getElementById("stat-uptime").textContent = system.uptime_seconds != null ? Math.round(system.uptime_seconds) : "—";

  // active jobs updated separately
  refreshHealth();
}

async function refreshAll() {
  const [agents, envs, datasets, system, jobs] = await Promise.all([
    getJSON("/api/v1/agents"),
    getJSON("/api/v1/envs"),
    getJSON("/api/v1/datasets"),
    getJSON("/api/v1/system"),
    getJSON("/api/v1/jobs"),
  ]).catch((e) => {
    showToast(`Refresh failed: ${e.message}`, "error");
    return [];
  });
  state.datasets = datasets;
  state.agents = agents;
  state.envs = envs;
  updateHomeStats(agents, envs, datasets, system);
  if (document.getElementById("jobs").classList.contains("active")) renderJobs(jobs);
  showToast("Dashboard refreshed");
}

// Demo runner
async function runDemo() {
  const msg = document.getElementById("demo-message");
  msg.textContent = "Starting demo job...";
  msg.className = "message";
  try {
    const res = await postJSON("/api/v1/jobs/demo", {
      data: document.getElementById("demo-data").value,
      episodes: parseInt(document.getElementById("demo-episodes").value, 10),
      lr: parseFloat(document.getElementById("demo-lr").value),
      eps: parseFloat(document.getElementById("demo-eps").value),
      gamma: parseFloat(document.getElementById("demo-gamma").value),
    });
    msg.textContent = `Demo started: job ${res.job_id}`;
    msg.className = "message ok";
    showToast(`Demo job ${res.job_id} started`);
    switchTab("jobs");
    state.selectedJobId = res.job_id;
  } catch (e) {
    msg.textContent = "Error: " + e.message;
    msg.className = "message error";
  }
}

// Experiment runner
async function runExperiment() {
  const msg = document.getElementById("exp-message");
  msg.textContent = "Starting experiment job...";
  msg.className = "message";
  try {
    const res = await postJSON("/api/v1/jobs/experiment", {
      script: document.getElementById("exp-script").value,
      args: {},
    });
    msg.textContent = `Experiment started: job ${res.job_id}`;
    msg.className = "message ok";
    showToast(`Experiment ${res.job_id} started`);
    switchTab("jobs");
    state.selectedJobId = res.job_id;
  } catch (e) {
    msg.textContent = "Error: " + e.message;
    msg.className = "message error";
  }
}

// Jobs
async function loadJobs() {
  const wrap = document.getElementById("jobs-table-wrap");
  try {
    const jobs = await getJSON("/api/v1/jobs");
    document.getElementById("stat-active").textContent = jobs.filter((j) => j.status === "running").length;
    renderJobs(jobs);
    if (state.selectedJobId) showLog();
  } catch (e) {
    wrap.innerHTML = `<p class="message error">Could not load jobs: ${e.message}</p>`;
  }
}

function renderJobs(jobs) {
  const wrap = document.getElementById("jobs-table-wrap");
  if (jobs.length === 0) {
    wrap.innerHTML = "<p class=\"message\">No jobs yet.</p>";
    return;
  }
  const html = [
    "<table><thead><tr><th>ID</th><th>Type</th><th>Status</th><th>Created</th><th>Duration</th><th>Actions</th></tr></thead><tbody>",
  ];
  jobs.forEach((job) => {
    const duration = job.finished ? `${((job.finished - job.started) / 60).toFixed(1)} min` : "running";
    const selected = job.id === state.selectedJobId ? "style='background:rgba(59,130,246,0.08)'" : "";
    html.push(`
      <tr ${selected}>
        <td><strong>${job.id}</strong></td>
        <td>${job.type}</td>
        <td><span class="status-badge ${job.status}">${job.status}</span></td>
        <td>${new Date(job.created).toLocaleString()}</td>
        <td>${duration}</td>
        <td>
          <button class="secondary" onclick="selectJob('${job.id}')">View</button>
          ${job.status === "running" ? `<button class="secondary" style="margin-left:6px" onclick="stopJob('${job.id}')">Stop</button>` : ""}
          <button class="danger" style="margin-left:6px" onclick="deleteJob('${job.id}')">Delete</button>
        </td>
      </tr>
    `);
  });
  html.push("</tbody></table>");
  wrap.innerHTML = html.join("");
}

function selectJob(id) {
  state.selectedJobId = id;
  document.getElementById("selected-job-id").textContent = ` · ${id}`;
  showLog();
  loadJobs();
}

async function stopJob(id) {
  await fetch(`${API}/api/v1/jobs/${id}/stop`, { method: "POST" });
  showToast(`Job ${id} stopped`);
  loadJobs();
}

async function deleteJob(id) {
  if (!confirm(`Delete job ${id}?`)) return;
  await fetch(`${API}/api/v1/jobs/${id}`, { method: "DELETE" });
  showToast(`Job ${id} deleted`);
  if (state.selectedJobId === id) state.selectedJobId = null;
  loadJobs();
}

async function showLog() {
  if (!state.selectedJobId) return;
  try {
    const job = await getJSON(`/api/v1/jobs/${state.selectedJobId}?tail=${state.tailLines}`);
    const pre = document.getElementById("job-log");
    pre.textContent = `[${job.id}] ${job.status}\n${job.log || "(no output)"}`;
    pre.scrollTop = pre.scrollHeight;
  } catch (e) {
    document.getElementById("job-log").textContent = "Error loading log: " + e.message;
  }
}

// Results
async function loadResultsJobs() {
  const sel = document.getElementById("result-job");
  try {
    const jobs = await getJSON("/api/v1/jobs");
    const current = sel.value;
    sel.innerHTML = '<option value="">-- choose a completed job --</option>';
    jobs.filter((j) => j.status === "success").forEach((j) => {
      const opt = document.createElement("option");
      opt.value = j.id;
      opt.textContent = `${j.id} · ${j.type} · ${new Date(j.created).toLocaleString()}`;
      sel.appendChild(opt);
    });
    if (current && Array.from(sel.options).some((o) => o.value === current)) sel.value = current;
  } catch (e) { /* ignore */ }
}

async function loadResult(jobId) {
  if (!jobId) return;
  state.selectedResultJobId = jobId;
  const metricsEl = document.getElementById("metrics");
  const tradeWrap = document.getElementById("trade-table-wrap");
  const filesEl = document.getElementById("result-files");
  try {
    const data = await getJSON(`/api/v1/jobs/${jobId}/results`);
    renderMetrics(data.metrics || {});
    renderEquity(data.equity || [], data.drawdown || []);
    renderTrades(data.trades || []);
    renderResultFiles(data.files || []);
  } catch (err) {
    metricsEl.innerHTML = `<p class="message error">${err.message}</p>`;
    tradeWrap.innerHTML = "";
    filesEl.innerHTML = "";
  }
}

function renderMetrics(metrics) {
  const names = {
    total_return_pct: "Total Return %",
    sharpe: "Sharpe",
    max_drawdown_pct: "Max Drawdown %",
    final_equity: "Final Equity",
    num_trades: "# Trades",
    data_points: "Data Points",
  };
  const container = document.getElementById("metrics");
  container.innerHTML = "";
  const keys = Object.keys(metrics);
  if (keys.length === 0) {
    container.innerHTML = "<p class=\"message\">No metrics available.</p>";
    return;
  }
  keys.forEach((k) => {
    const val = typeof metrics[k] === "number" ? metrics[k].toFixed(4) : metrics[k];
    const div = document.createElement("div");
    div.className = "metric";
    div.innerHTML = `<div class="value">${val}</div><div class="label">${names[k] || k}</div>`;
    container.appendChild(div);
  });
}

function renderEquity(equity, drawdown) {
  const labels = equity.map((_, i) => i);
  const data = equity.map((r) => r.equity);
  destroyChart("equity");
  destroyChart("drawdown");

  charts.equity = new Chart(document.getElementById("equity-chart"), {
    type: "line",
    data: {
      labels,
      datasets: [{
        label: "Equity Curve",
        data,
        borderColor: "#3b82f6",
        backgroundColor: "rgba(59, 130, 246, 0.1)",
        fill: true,
        tension: 0.2,
        pointRadius: 0,
      }],
    },
    options: commonChartOptions(),
  });

  charts.drawdown = new Chart(document.getElementById("drawdown-chart"), {
    type: "line",
    data: {
      labels,
      datasets: [{
        label: "Drawdown %",
        data: drawdown,
        borderColor: "#ef4444",
        backgroundColor: "rgba(239, 68, 68, 0.1)",
        fill: true,
        tension: 0.2,
        pointRadius: 0,
      }],
    },
    options: commonChartOptions(),
  });
}

function commonChartOptions() {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: { legend: { display: true, labels: { color: "#e8eef8" } } },
    scales: {
      x: { ticks: { color: "#8b9bb4" }, grid: { color: "#243047" } },
      y: { ticks: { color: "#8b9bb4" }, grid: { color: "#243047" } },
    },
  };
}

function destroyChart(name) {
  if (charts[name]) { charts[name].destroy(); charts[name] = null; }
}

function renderTrades(trades) {
  const wrap = document.getElementById("trade-table-wrap");
  if (trades.length === 0) {
    wrap.innerHTML = "<p class=\"message\">No trades recorded.</p>";
    return;
  }
  const rows = trades.map((t) => `
    <tr>
      <td>${t.step}</td>
      <td><span class="status-badge ${t.action}">${t.action}</span></td>
      <td>${t.price?.toFixed ? t.price.toFixed(2) : t.price}</td>
    </tr>
  `).join("");
  wrap.innerHTML = `<table><thead><tr><th>Step</th><th>Action</th><th>Price</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function renderResultFiles(files) {
  const el = document.getElementById("result-files");
  if (!files.length) {
    el.innerHTML = "<span class=\"message\">No output files.</span>";
    return;
  }
  el.innerHTML = files.map((f) => `
    <div class="file-chip" onclick="viewResultFile('${f.name}')">
      <i class="fa-solid fa-file"></i> ${f.name} <span class="size">${formatBytes(f.size)}</span>
    </div>
  `).join("");
}

async function viewResultFile(name) {
  if (!state.selectedResultJobId) return;
  try {
    const r = await fetch(`${API}/api/v1/jobs/${state.selectedResultJobId}/files/${encodeURIComponent(name)}`);
    const text = await r.text();
    document.getElementById("result-file-content").textContent = text;
  } catch (e) {
    document.getElementById("result-file-content").textContent = "Error: " + e.message;
  }
}

// Resources (configs & data)
async function loadResources() {
  const [agents, envs, datasets] = await Promise.all([
    getJSON("/api/v1/agents"),
    getJSON("/api/v1/envs"),
    getJSON("/api/v1/datasets"),
  ]);
  state.agents = agents;
  state.envs = envs;
  state.datasets = datasets;

  const configList = document.getElementById("config-list");
  configList.innerHTML = "";
  [...agents, ...envs].forEach((c) => {
    const li = document.createElement("li");
    li.textContent = `${c.task} / ${c.name}`;
    li.dataset.path = c.path;
    li.dataset.kind = "config";
    li.addEventListener("click", () => selectResource(li, c.path, "config"));
    configList.appendChild(li);
  });

  const datasetList = document.getElementById("dataset-list");
  datasetList.innerHTML = "";
  datasets.forEach((d) => {
    const li = document.createElement("li");
    li.textContent = `${d.universe} / ${d.name}`;
    li.dataset.path = d.path;
    li.dataset.kind = "dataset";
    li.addEventListener("click", () => selectResource(li, d.path, "dataset"));
    datasetList.appendChild(li);
  });
}

async function selectResource(li, path, kind) {
  document.querySelectorAll(".compact-list li").forEach((l) => l.classList.remove("selected"));
  li.classList.add("selected");

  const preview = document.getElementById("resource-preview");
  try {
    if (kind === "config") {
      const data = await getJSON(`/api/v1/config?path=${encodeURIComponent(path)}`);
      preview.textContent = JSON.stringify(data, null, 2);
      // Also update setup preview
      document.getElementById("config-preview").innerHTML = `<pre style="margin:0;font-size:12px">${JSON.stringify(data, null, 2)}</pre>`;
    } else {
      const data = await getJSON(`/api/v1/datasets/preview?path=${encodeURIComponent(path)}`);
      const head = [data.columns.join(","), ...data.rows.map((r) => data.columns.map((c) => r[c]).join(","))].join("\n");
      preview.textContent = `${data.shape[0]} rows × ${data.shape[1]} cols\n${head}`;
      // Also update setup preview
      document.getElementById("dataset-preview").innerHTML = `<div style="overflow:auto"><p style="color:var(--muted);font-size:12px">${data.shape[0]} rows × ${data.shape[1]} columns</p><table><thead><tr>${data.columns.map((c) => `<th>${c}</th>`).join("")}</tr></thead><tbody>${data.rows.map((r) => `<tr>${data.columns.map((c) => `<td>${r[c]}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
    }
  } catch (e) {
    preview.textContent = `Error loading preview: ${e.message}`;
  }
}

init();
