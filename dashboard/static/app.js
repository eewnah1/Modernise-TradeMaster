const API = "";
let chart = null;
let selectedJobId = null;
let pollInterval = null;

// Tab switching
document.querySelectorAll('.nav-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(btn.dataset.tab).classList.add('active');
    if (btn.dataset.tab === 'jobs') loadJobs();
    if (btn.dataset.tab === 'results') loadResultsJobs();
  });
});

async function getJSON(path) {
  const r = await fetch(API + path);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

async function postJSON(path, body) {
  const r = await fetch(API + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const text = await r.text();
  if (!r.ok) throw new Error(text);
  try { return JSON.parse(text); } catch { return { message: text }; }
}

async function init() {
  try {
    const health = await getJSON('/health');
    setStatus('ok', `online · ${health.active_jobs || 0} running`);
  } catch (e) {
    setStatus('error', 'offline');
  }

  const [datasets, agents, envs, experiments] = await Promise.all([
    getJSON('/api/v1/datasets'),
    getJSON('/api/v1/agents'),
    getJSON('/api/v1/envs'),
    getJSON('/api/v1/experiments'),
  ]);

  populateSelect('demo-data', datasets, d => `${d.universe}/${d.name}`, d => d.path);
  populateList('agent-list', agents, a => `${a.task} · ${a.name} (${a.path})`);
  populateList('env-list', envs, e => `${e.task} · ${e.scenario} · ${e.name}`);
  populateSelect('exp-script', experiments, e => `${e.task}/${e.agent}`, e => e.path);
}

function setStatus(cls, text) {
  const el = document.getElementById('status-pill');
  el.className = `status ${cls}`;
  el.textContent = text;
}

function populateSelect(id, items, labelFn, valueFn) {
  const sel = document.getElementById(id);
  sel.innerHTML = '';
  items.forEach(item => {
    const opt = document.createElement('option');
    opt.value = valueFn(item);
    opt.textContent = labelFn(item);
    sel.appendChild(opt);
  });
}

function populateList(id, items, labelFn) {
  const ul = document.getElementById(id);
  ul.innerHTML = '';
  if (items.length === 0) {
    ul.innerHTML = '<li>None found</li>';
    return;
  }
  items.forEach(item => {
    const li = document.createElement('li');
    li.textContent = labelFn(item);
    ul.appendChild(li);
  });
}

// Run demo
document.getElementById('run-demo').addEventListener('click', async () => {
  const msg = document.getElementById('demo-message');
  msg.textContent = 'Starting demo job...';
  msg.className = 'message';
  try {
    const res = await postJSON('/api/v1/jobs/demo', {
      data: document.getElementById('demo-data').value,
      episodes: parseInt(document.getElementById('demo-episodes').value, 10),
      lr: parseFloat(document.getElementById('demo-lr').value),
      eps: parseFloat(document.getElementById('demo-eps').value),
      gamma: parseFloat(document.getElementById('demo-gamma').value),
    });
    msg.textContent = `Demo started: job ${res.job_id}`;
    msg.className = 'message ok';
    switchTab('jobs');
  } catch (e) {
    msg.textContent = 'Error: ' + e.message;
    msg.className = 'message error';
  }
});

// Run experiment
document.getElementById('run-experiment').addEventListener('click', async () => {
  const msg = document.getElementById('exp-message');
  msg.textContent = 'Starting experiment job...';
  msg.className = 'message';
  try {
    const res = await postJSON('/api/v1/jobs/experiment', {
      script: document.getElementById('exp-script').value,
      args: {},
    });
    msg.textContent = `Experiment started: job ${res.job_id}`;
    msg.className = 'message ok';
    switchTab('jobs');
  } catch (e) {
    msg.textContent = 'Error: ' + e.message;
    msg.className = 'message error';
  }
});

function switchTab(name) {
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.id === name));
  if (name === 'jobs') loadJobs();
  if (name === 'results') loadResultsJobs();
}

// Jobs tab
async function loadJobs() {
  const container = document.getElementById('jobs-container');
  try {
    const jobs = await getJSON('/api/v1/jobs');
    container.innerHTML = '';
    if (jobs.length === 0) {
      container.innerHTML = '<p>No jobs yet.</p>';
      return;
    }
    jobs.forEach(job => {
      const div = document.createElement('div');
      div.className = 'job-card';
      div.innerHTML = `
        <div class="info">
          <div class="job-id">${job.id} · ${job.type}</div>
          <div class="job-type">${job.command}</div>
          <div style="font-size:12px;color:#8b9bb4;margin-top:4px">${job.status} · ${new Date(job.created).toLocaleString()}</div>
        </div>
        <div style="display:flex;gap:8px;align-items:center">
          <span class="status-badge ${job.status}">${job.status}</span>
          <button class="secondary" data-view="${job.id}">View</button>
          ${job.status === 'running' ? `<button class="secondary" data-stop="${job.id}">Stop</button>` : ''}
          <button class="secondary" data-delete="${job.id}">Delete</button>
        </div>
      `;
      container.appendChild(div);
    });

    container.querySelectorAll('button[data-view]').forEach(btn => {
      btn.addEventListener('click', () => { selectedJobId = btn.dataset.view; showLog(); });
    });
    container.querySelectorAll('button[data-stop]').forEach(btn => {
      btn.addEventListener('click', async () => {
        await fetch(`${API}/api/v1/jobs/${btn.dataset.stop}/stop`, { method: 'POST' });
        loadJobs();
      });
    });
    container.querySelectorAll('button[data-delete]').forEach(btn => {
      btn.addEventListener('click', async () => {
        await fetch(`${API}/api/v1/jobs/${btn.dataset.delete}`, { method: 'DELETE' });
        loadJobs();
      });
    });

    if (selectedJobId) showLog();
  } catch (e) {
    container.innerHTML = `<p class="message error">Could not load jobs: ${e.message}</p>`;
  }
}

document.getElementById('refresh-jobs').addEventListener('click', loadJobs);

async function showLog() {
  if (!selectedJobId) return;
  try {
    const job = await getJSON(`/api/v1/jobs/${selectedJobId}`);
    const pre = document.getElementById('job-log');
    pre.textContent = `[${job.id}] ${job.status}\n${job.log || '(no output)'}`;
    pre.scrollTop = pre.scrollHeight;
  } catch (e) {
    document.getElementById('job-log').textContent = 'Error loading log: ' + e.message;
  }
}

// Results tab
async function loadResultsJobs() {
  const sel = document.getElementById('result-job');
  sel.innerHTML = '<option value="">-- choose a job --</option>';
  try {
    const jobs = await getJSON('/api/v1/jobs');
    jobs.filter(j => j.type === 'demo' && j.status === 'success').forEach(j => {
      const opt = document.createElement('option');
      opt.value = j.id;
      opt.textContent = `${j.id} · ${new Date(j.created).toLocaleString()}`;
      sel.appendChild(opt);
    });
  } catch (e) { /* ignore */ }
}

document.getElementById('result-job').addEventListener('change', async (e) => {
  const jobId = e.target.value;
  if (!jobId) return;
  try {
    const data = await getJSON(`/api/v1/jobs/${jobId}/results`);
    renderMetrics(data.metrics || {});
    renderEquity(data.equity || []);
    renderTrades(data.trades || []);
  } catch (err) {
    document.getElementById('metrics').innerHTML = `<p class="message error">${err.message}</p>`;
  }
});

function renderMetrics(metrics) {
  const names = {
    total_return_pct: 'Total Return %',
    sharpe: 'Sharpe',
    max_drawdown_pct: 'Max Drawdown %',
    final_equity: 'Final Equity',
    num_trades: '# Trades',
    data_points: 'Data Points',
  };
  const keys = Object.keys(metrics);
  const container = document.getElementById('metrics');
  container.innerHTML = '';
  keys.forEach(k => {
    const div = document.createElement('div');
    div.className = 'metric';
    div.innerHTML = `<div class="value">${metrics[k]}</div><div class="label">${names[k] || k}</div>`;
    container.appendChild(div);
  });
}

function renderEquity(equity) {
  const ctx = document.getElementById('equity-chart').getContext('2d');
  if (chart) chart.destroy();
  const labels = equity.map((_, i) => i);
  const data = equity.map(r => r.equity);
  chart = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label: 'Equity Curve',
        data,
        borderColor: '#3b82f6',
        backgroundColor: 'rgba(59, 130, 246, 0.1)',
        fill: true,
        tension: 0.2,
        pointRadius: 0,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: true, labels: { color: '#e8eef8' } } },
      scales: {
        x: { ticks: { color: '#8b9bb4' }, grid: { color: '#243047' } },
        y: { ticks: { color: '#8b9bb4' }, grid: { color: '#243047' } },
      },
    },
  });
}

function renderTrades(trades) {
  const tbody = document.querySelector('#trade-table tbody');
  tbody.innerHTML = '';
  trades.forEach(t => {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${t.step}</td><td>${t.action}</td><td>${t.price?.toFixed ? t.price.toFixed(2) : t.price}</td>`;
    tbody.appendChild(tr);
  });
}

// Poll jobs while on jobs tab
setInterval(() => {
  if (document.getElementById('jobs').classList.contains('active')) loadJobs();
}, 2000);

init();
