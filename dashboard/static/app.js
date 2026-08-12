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
  selectedFileName: null,
  tailLines: 200,
  eventSource: null,
  system: {},
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

function pctClass(v) {
  if (v < 50) return "low";
  if (v < 80) return "mid";
  return "high";
}

function setBar(id, pct) {
  const el = document.getElementById(id);
  if (!el) return;
  el.style.width = `${Math.min(100, Math.max(0, pct))}%`;
  el.className = `bar-fill ${pctClass(pct)}`;
}

// Navigation
function switchTab(name) {
  const btn = document.querySelector(`.nav-item[data-tab="${name}"]`);
  if (!btn) return;
  document.querySelectorAll(".nav-item").forEach((b) => b.classList.remove("active"));
  document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
  btn.classList.add("active");
  document.getElementById(name).classList.add("active");
  document.getElementById("page-title").textContent = btn.querySelector("span").textContent;
  if (name === "jobs") loadJobs();
  if (name === "results") loadResultsJobs();
  if (name === "resources") loadResources();
}

document.querySelectorAll(".nav-item").forEach((btn) => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

// Init
async function init() {
  refreshHealth();
  setInterval(refreshHealth, 5000);
  document.getElementById("refresh-all").addEventListener("click", refreshAll);
  document.getElementById("palette-btn").addEventListener("click", openPalette);
  document.getElementById("run-demo").addEventListener("click", runDemo);
  document.getElementById("run-experiment").addEventListener("click", runExperiment);
  document.getElementById("refresh-jobs").addEventListener("click", loadJobs);
  document.getElementById("result-job").addEventListener("change", (e) => loadResult(e.target.value));
  document.getElementById("tail-50").addEventListener("click", () => { state.tailLines = 50; showLog(); });
  document.getElementById("tail-500").addEventListener("click", () => { state.tailLines = 500; showLog(); });

  initPalette();

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
  state.system = system;

  populateSelect("demo-data", datasets, (d) => `${d.universe} / ${d.name}`, (d) => d.path);
  populateSelect("exp-script", experiments, (e) => `${e.task} / ${e.agent}`, (e) => e.path);

  updateHomeStats(agents, envs, datasets, system);
  setStatus("ok", "online");
  loadMarket();

  setInterval(() => { refreshHealth(); loadMarket(); }, 60000);
  setInterval(() => {
    if (document.getElementById("jobs").classList.contains("active")) loadJobs();
    if (document.getElementById("results").classList.contains("active")) loadResultsJobs();
    loadSystem();
  }, 2000);

  loadSystem();
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
  state.system = system;
  loadSystem();
}

function loadSystem() {
  const system = state.system;
  if (!system || !system.memory_gb) return;

  const mem = system.memory_gb || {};
  const usedMem = Math.max(0, (mem.total_gb || 0) - (mem.available_gb || 0));
  document.getElementById("stat-mem").textContent = `${usedMem.toFixed(1)} / ${mem.total_gb.toFixed(1)} GB`;
  setBar("bar-mem", system.memory_used_pct || 0);

  const load = system.load || {};
  const cpuCount = system.cpu_count || 1;
  const load1m = load["1m"] != null ? load["1m"] : 0;
  const loadPct = Math.min(100, (load1m / cpuCount) * 100);
  document.getElementById("stat-load").textContent = load1m.toFixed(2);
  setBar("bar-load", loadPct);

  const disk = system.disk || {};
  const usedDisk = Math.max(0, (disk.total_gb || 0) - (disk.free_gb || 0));
  document.getElementById("stat-disk").textContent = `${usedDisk.toFixed(1)} / ${disk.total_gb.toFixed(1)} GB`;
  setBar("bar-disk", system.disk_used_pct || 0);

  document.getElementById("stat-uptime").textContent = system.uptime_seconds != null ? Math.round(system.uptime_seconds) : "—";
}

async function loadMarket() {
  const container = document.getElementById("market-monitor");
  try {
    const data = await getJSON("/api/v1/market/snapshot");
    if (!data.quotes || data.quotes.length === 0) {
      container.innerHTML = "<p class='message'>Market data unavailable.</p>";
      return;
    }
    container.innerHTML = data.quotes.map((q) => {
      if (q.error) return `<div class="ticker-card"><div class="symbol">${q.ticker}</div><div class="change">${q.error}</div></div>`;
      const up = q.change_pct >= 0;
      return `
        <div class="ticker-card">
          <div class="symbol">${q.ticker}</div>
          <div class="price">${q.price}</div>
          <div class="change ${up ? "up" : "down"}">${up ? "▲" : "▼"} ${Math.abs(q.change_pct).toFixed(2)}%</div>
        </div>`;
    }).join("");
  } catch (e) {
    container.innerHTML = `<p class='message error'>Market data error: ${e.message}</p>`;
  }
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
  state.system = system;
  updateHomeStats(agents, envs, datasets, system);
  loadMarket();
  if (document.getElementById("jobs").classList.contains("active")) renderJobs(jobs);
  showToast("Dashboard refreshed");
}

// Command palette
function initPalette() {
  const overlay = document.getElementById("palette-overlay");
  const input = document.getElementById("palette-input");
  const list = document.getElementById("palette-list");

  const actions = [
    { name: "Go to Platform Home", icon: "fa-house", action: () => switchTab("home") },
    { name: "New Experiment", icon: "fa-flask", action: () => switchTab("setup") },
    { name: "Jobs & Logs", icon: "fa-server", action: () => switchTab("jobs") },
    { name: "Results", icon: "fa-chart-line", action: () => switchTab("results") },
    { name: "Configs & Data", icon: "fa-database", action: () => switchTab("resources") },
    { name: "Run Q-Learning Demo", icon: "fa-play", action: () => { switchTab("setup"); runDemo(); } },
    { name: "Refresh Dashboard", icon: "fa-rotate", action: refreshAll },
  ];

  function render(filter = "") {
    const term = filter.toLowerCase();
    const filtered = actions.filter((a) => a.name.toLowerCase().includes(term));
    list.innerHTML = filtered.map((a, i) => `<li data-idx="${i}" onclick="paletteAction(${i})"><i class="fa-solid ${a.icon}"></i> ${a.name}</li>`).join("");
  }

  input.addEventListener("input", () => render(input.value));
  input.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closePalette();
    if (e.key === "Enter") {
      const first = list.querySelector("li");
      if (first) {
        const idx = parseInt(first.dataset.idx, 10);
        paletteAction(idx, actions);
      }
    }
  });

  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      openPalette();
    }
  });

  overlay.addEventListener("click", (e) => { if (e.target === overlay) closePalette(); });
  window.paletteActions = actions;
}

function openPalette() {
  document.getElementById("palette-overlay").classList.add("open");
  document.getElementById("palette-input").value = "";
  document.getElementById("palette-input").focus();
  renderPalette();
}

function closePalette() {
  document.getElementById("palette-overlay").classList.remove("open");
}

function renderPalette() {
  const list = document.getElementById("palette-list");
  list.innerHTML = window.paletteActions.map((a, i) => `<li data-idx="${i}" onclick="paletteAction(${i})"><i class="fa-solid ${a.icon}"></i> ${a.name}</li>`).join("");
}

function paletteAction(idx, actions = window.paletteActions) {
  if (actions[idx]) {
    actions[idx].action();
    closePalette();
  }
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
    selectJob(res.job_id);
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
    selectJob(res.job_id);
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
    "<table><thead><tr><th>ID</th><th>Type</th><th>Status</th><th>Progress</th><th>Created</th><th>Duration</th><th>Actions</th></tr></thead><tbody>",
  ];
  jobs.forEach((job) => {
    const duration = job.finished ? `${((job.finished - job.started) / 60).toFixed(1)} min` : "running";
    const selected = job.id === state.selectedJobId ? "class='selected'" : "";
    const liveMetrics = job.liveMetrics || {};
    const progress = liveMetrics.progress_pct || 0;
    const progressBar = `<div class="progress-bar"><div class="progress-fill" style="width:${progress}%"></div></div>`;
    html.push(`
      <tr ${selected}>
        <td><strong>${job.id}</strong></td>
        <td>${job.type}</td>
        <td><span class="status-badge ${job.status}">${job.status}</span></td>
        <td>${job.status === "running" ? progressBar : "—"}</td>
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
  document.getElementById("job-log").textContent = "Connecting to live log stream...";
  showLog();
  loadJobs();
  subscribeJobStream(id);
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
  if (state.selectedJobId === id) {
    state.selectedJobId = null;
    closeEventSource();
    document.getElementById("selected-job-id").textContent = "";
    document.getElementById("job-log").textContent = "Select a job to view its live log.";
  }
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

// SSE live stream
function subscribeJobStream(jobId) {
  closeEventSource();
  const indicator = document.getElementById("live-indicator");
  indicator.style.display = "inline";

  if (typeof EventSource === "undefined") {
    indicator.style.display = "none";
    return;
  }

  const es = new EventSource(`${API}/api/v1/jobs/${jobId}/stream`);
  state.eventSource = es;

  es.addEventListener("update", (e) => {
    try {
      const data = JSON.parse(e.data);
      const pre = document.getElementById("job-log");
      pre.textContent = `[${jobId}] ${data.status}\n${data.log || "(no output)"}`;
      pre.scrollTop = pre.scrollHeight;
      if (data.status !== "running") indicator.style.display = "none";
    } catch (_) {}
  });

  es.addEventListener("close", () => {
    indicator.style.display = "none";
    loadJobs();
  });

  es.onerror = () => {
    indicator.style.display = "none";
  };
}

function closeEventSource() {
  if (state.eventSource) {
    state.eventSource.close();
    state.eventSource = null;
  }
  const indicator = document.getElementById("live-indicator");
  if (indicator) indicator.style.display = "none";
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
  state.selectedFileName = null;
  const analyticsEl = document.getElementById("analytics");
  const metricsEl = document.getElementById("metrics");
  const tradeWrap = document.getElementById("trade-table-wrap");
  const filesEl = document.getElementById("result-files");
  try {
    const data = await getJSON(`/api/v1/jobs/${jobId}/results`);
    renderAnalytics(data.analytics);
    renderMetrics(data.metrics || {});
    renderEquity(data.equity || [], data.analytics?.benchmark || {});
    renderDrawdown(data.drawdown || [], data.analytics?.rolling?.drawdown || []);
    renderRolling(data.analytics?.rolling?.sharpe || []);
    renderTradeDistribution(data.analytics?.trades || {});
    renderTrades(data.analytics?.trades?.trades || []);
    renderResultFiles(data.files || []);
  } catch (err) {
    analyticsEl.innerHTML = `<p class="message error">${err.message}</p>`;
    metricsEl.innerHTML = "";
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

function renderAnalytics(a) {
  const container = document.getElementById("analytics");
  container.innerHTML = "";
  const m = a.metrics || {};
  const t = a.trades || {};
  const alpha = a.alpha_vs_benchmark_pct;

  const cards = [
    { label: "Total Return %", value: m.total_return_pct, suffix: "%", pos: (v) => v >= 0 },
    { label: "CAGR %", value: m.cagr_pct, suffix: "%", pos: (v) => v >= 0 },
    { label: "Volatility %", value: m.volatility_pct, suffix: "%" },
    { label: "Sharpe", value: m.sharpe, pos: (v) => v >= 1 },
    { label: "Sortino", value: m.sortino, pos: (v) => v >= 1 },
    { label: "Max DD %", value: m.max_drawdown_pct, suffix: "%", pos: (v) => v >= -10 },
    { label: "Calmar", value: m.calmar, pos: (v) => v >= 0.5 },
    { label: "Win Rate", value: t.win_rate, suffix: "%", pos: (v) => v >= 50 },
    { label: "Profit Factor", value: t.profit_factor, pos: (v) => v >= 1 },
    { label: "Avg Trade %", value: t.avg_trade_pct, suffix: "%", pos: (v) => v >= 0 },
    { label: "Benchmark %", value: (a.benchmark || {}).total_return_pct, suffix: "%", pos: (v) => v >= 0 },
    { label: "Alpha vs BH %", value: alpha, suffix: "%", pos: (v) => v >= 0 },
  ];

  cards.forEach((c) => {
    if (c.value == null || (typeof c.value === "number" && !Number.isFinite(c.value))) return;
    const v = typeof c.value === "number" ? c.value.toFixed(4) : c.value;
    const cls = c.pos ? (c.pos(c.value) ? "positive" : "negative") : "";
    const div = document.createElement("div");
    div.className = `metric ${cls}`;
    div.innerHTML = `<div class="value">${v}${c.suffix || ""}</div><div class="label">${c.label}</div>`;
    container.appendChild(div);
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

function labelsFor(n) {
  return Array.from({ length: n }, (_, i) => i);
}

function renderEquity(equity, benchmark) {
  const labels = labelsFor(equity.length);
  const data = equity.map((r) => r.equity);
  destroyChart("equity");

  const datasets = [{
    label: "Strategy Equity",
    data,
    borderColor: "#3b82f6",
    backgroundColor: "rgba(59, 130, 246, 0.1)",
    fill: true,
    tension: 0.2,
    pointRadius: 0,
  }];

  if (benchmark.equity && benchmark.equity.length >= data.length) {
    datasets.push({
      label: "Buy & Hold",
      data: benchmark.equity.slice(-data.length),
      borderColor: "#8b5cf6",
      backgroundColor: "transparent",
      fill: false,
      tension: 0.2,
      pointRadius: 0,
      borderDash: [6, 4],
    });
  }

  charts.equity = new Chart(document.getElementById("equity-chart"), {
    type: "line",
    data: { labels, datasets },
    options: commonChartOptions(),
  });
}

function renderDrawdown(drawdown, rollingDrawdown) {
  const labels = labelsFor(drawdown.length || rollingDrawdown.length || 0);
  destroyChart("drawdown");
  const dd = drawdown.length ? drawdown : rollingDrawdown;
  if (!dd.length) return;

  charts.drawdown = new Chart(document.getElementById("drawdown-chart"), {
    type: "line",
    data: {
      labels,
      datasets: [{
        label: "Drawdown %",
        data: dd,
        borderColor: "#ef4444",
        backgroundColor: "rgba(239, 68, 68, 0.12)",
        fill: true,
        tension: 0.2,
        pointRadius: 0,
      }],
    },
    options: commonChartOptions(),
  });
}

function renderRolling(rollingSharpe) {
  destroyChart("rolling");
  if (!rollingSharpe.length) {
    document.getElementById("rolling-chart").parentElement.innerHTML = "<p class='message'>Not enough data for rolling Sharpe.</p>";
    return;
  }
  const labels = labelsFor(rollingSharpe.length);
  charts.rolling = new Chart(document.getElementById("rolling-chart"), {
    type: "line",
    data: {
      labels,
      datasets: [{
        label: "Rolling Sharpe (20 periods)",
        data: rollingSharpe,
        borderColor: "#10b981",
        backgroundColor: "rgba(16, 185, 129, 0.08)",
        fill: true,
        tension: 0.2,
        pointRadius: 0,
      }],
    },
    options: commonChartOptions(),
  });
}

function renderTradeDistribution(tradeStats) {
  destroyChart("trade");
  const trades = tradeStats.trades || [];
  if (!trades.length) {
    document.getElementById("trade-chart").parentElement.innerHTML = "<p class='message'>No closed trades to display.</p>";
    return;
  }

  // Build histogram of PnL % into 10 bins
  const pnls = trades.map((t) => t.pnl_pct);
  const min = Math.min(...pnls);
  const max = Math.max(...pnls);
  const bins = 10;
  const step = (max - min) / bins || 1;
  const counts = new Array(bins).fill(0);
  pnls.forEach((v) => {
    const idx = Math.min(bins - 1, Math.max(0, Math.floor((v - min) / step)));
    counts[idx]++;
  });
  const labels = counts.map((_, i) => `${(min + i * step).toFixed(1)}%`);

  charts.trade = new Chart(document.getElementById("trade-chart"), {
    type: "bar",
    data: {
      labels,
      datasets: [{
        label: "Trade PnL % distribution",
        data: counts,
        backgroundColor: pnls.map((v) => v >= 0 ? "rgba(16,185,129,0.6)" : "rgba(239,68,68,0.6)"),
        borderColor: pnls.map((v) => v >= 0 ? "#10b981" : "#ef4444"),
        borderWidth: 1,
      }],
    },
    options: commonChartOptions(),
  });
}

function renderTrades(trades) {
  const wrap = document.getElementById("trade-table-wrap");
  if (!trades.length) {
    wrap.innerHTML = "<p class=\"message\">No trades recorded.</p>";
    return;
  }
  const rows = trades.map((t) => `
    <tr>
      <td><span class="status-badge ${t.side}">${t.side}</span></td>
      <td>${t.entry_step}</td>
      <td>${t.exit_step != null ? t.exit_step : "—"}</td>
      <td>${t.entry_price?.toFixed ? t.entry_price.toFixed(2) : t.entry_price}</td>
      <td>${t.exit_price?.toFixed ? t.exit_price.toFixed(2) : t.exit_price}</td>
      <td class="${t.pnl_pct >= 0 ? "positive" : "negative"}" style="color:${t.pnl_pct >= 0 ? "#10b981" : "#ef4444"}">${t.pnl_pct?.toFixed ? t.pnl_pct.toFixed(2) : t.pnl_pct}%</td>
      <td>${t.holding_periods != null ? t.holding_periods : "—"}</td>
    </tr>
  `).join("");
  wrap.innerHTML = `<table><thead><tr><th>Side</th><th>Entry Step</th><th>Exit Step</th><th>Entry</th><th>Exit</th><th>PnL %</th><th>Periods</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function renderResultFiles(files) {
  const el = document.getElementById("result-files");
  if (!files.length) {
    el.innerHTML = "<span class=\"message\">No output files.</span>";
    return;
  }
  el.innerHTML = files.map((f) => `
    <div class="file-chip ${f.name === state.selectedFileName ? "active" : ""}" onclick="viewResultFile('${f.name}')">
      <i class="fa-solid fa-file"></i> ${f.name} <span class="size">${formatBytes(f.size)}</span>
    </div>
  `).join("");
}

async function viewResultFile(name) {
  if (!state.selectedResultJobId) return;
  state.selectedFileName = name;
  renderResultFiles(await getJSON(`/api/v1/jobs/${state.selectedResultJobId}/files`).then(d => d.files).catch(() => []));
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
    li.innerHTML = `<span>${c.task} / ${c.name}</span><i class="fa-solid fa-chevron-right" style="font-size:10px;color:var(--muted)"></i>`;
    li.dataset.path = c.path;
    li.dataset.kind = "config";
    li.addEventListener("click", () => selectResource(li, c.path, "config"));
    configList.appendChild(li);
  });

  const datasetList = document.getElementById("dataset-list");
  datasetList.innerHTML = "";
  datasets.forEach((d) => {
    const li = document.createElement("li");
    li.innerHTML = `<span>${d.universe} / ${d.name}</span><i class="fa-solid fa-chevron-right" style="font-size:10px;color:var(--muted)"></i>`;
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
      preview.innerHTML = `<pre>${JSON.stringify(data, null, 2)}</pre>`;
      document.getElementById("config-preview").innerHTML = `<pre style="margin:0;font-size:12px">${JSON.stringify(data, null, 2)}</pre>`;
    } else {
      const data = await getJSON(`/api/v1/datasets/preview?path=${encodeURIComponent(path)}`);
      const stats = computeColumnStats(data.rows, data.columns);
      const head = [data.columns.join(","), ...data.rows.map((r) => data.columns.map((c) => r[c]).join(","))].join("\n");
      preview.innerHTML = `
        <p style="color:var(--muted);font-size:12px;margin:0 0 10px">${data.shape[0]} rows × ${data.shape[1]} columns</p>
        <h4>Column Stats</h4>
        <div style="overflow:auto;margin-bottom:14px">${stats}</div>
        <h4>Preview</h4>
        <table><thead><tr>${data.columns.map((c) => `<th>${c}</th>`).join("")}</tr></thead><tbody>${data.rows.map((r) => `<tr>${data.columns.map((c) => `<td>${r[c]}</td>`).join("")}</tr>`).join("")}</tbody></table>
      `;
      document.getElementById("dataset-preview").innerHTML = `
        <p style="color:var(--muted);font-size:12px">${data.shape[0]} rows × ${data.shape[1]} columns</p>
        <div style="overflow:auto">${stats}</div>
      `;
    }
  } catch (e) {
    preview.innerHTML = `<p class="message error">Error loading preview: ${e.message}</p>`;
  }
}

function computeColumnStats(rows, columns) {
  if (!rows.length) return "";
  const numericCols = columns.filter((c) => rows.every((r) => r[c] === "" || !isNaN(parseFloat(r[c]))));
  if (!numericCols.length) return "<p class='message'>No numeric columns for statistics.</p>";

  const header = `<tr><th>Column</th><th>Mean</th><th>Std</th><th>Min</th><th>Max</th></tr>`;
  const body = numericCols.map((c) => {
    const vals = rows.map((r) => parseFloat(r[c])).filter((v) => !isNaN(v));
    if (!vals.length) return "";
    const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
    const min = Math.min(...vals);
    const max = Math.max(...vals);
    const std = Math.sqrt(vals.reduce((sq, n) => sq + Math.pow(n - mean, 2), 0) / vals.length);
    return `<tr><td>${c}</td><td>${mean.toFixed(4)}</td><td>${std.toFixed(4)}</td><td>${min.toFixed(4)}</td><td>${max.toFixed(4)}</td></tr>`;
  }).join("");
  return `<table>${header}${body}</table>`;
}

init();
