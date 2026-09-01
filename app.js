const state = {
  mode: "loading",
  groups: [],
  dates: [],
  stats: null,
  activeStep: null,
  groupId: "all",
  date: null,
  search: "",
  minPrice: 100,
  maxPrice: 500,
  results: [],
  metrics: null,
  prices: [],
  selectedSymbol: null,
};

const el = {
  groupSelect: document.querySelector("#groupSelect"),
  dateSelect: document.querySelector("#dateSelect"),
  searchInput: document.querySelector("#searchInput"),
  minPriceInput: document.querySelector("#minPriceInput"),
  maxPriceInput: document.querySelector("#maxPriceInput"),
  runButton: document.querySelector("#runButton"),
  statusText: document.querySelector("#statusText"),
  stepName: document.querySelector("#stepName"),
  stepMeaning: document.querySelector("#stepMeaning"),
  stepDecision: document.querySelector("#stepDecision"),
  metricsGrid: document.querySelector("#metricsGrid"),
  resultMeta: document.querySelector("#resultMeta"),
  resultsBody: document.querySelector("#resultsBody"),
  selectedTitle: document.querySelector("#selectedTitle"),
  chart: document.querySelector("#chart"),
  details: document.querySelector("#details"),
};

init();

async function init() {
  bindControls();
  try {
    const bootstrap = await fetchJson("/api/bootstrap");
    state.mode = "sqlite";
    state.groups = bootstrap.groups || [];
    state.dates = bootstrap.dates || [];
    state.stats = bootstrap.stats;
    state.activeStep = bootstrap.activeStep;
    state.minPrice = bootstrap.defaults?.minPrice ?? state.minPrice;
    state.maxPrice = bootstrap.defaults?.maxPrice ?? state.maxPrice;
    state.groupId = state.groups[0]?.id || "all";
    state.date = state.dates[state.dates.length - 1];
    renderSelectors();
    renderInputs();
    renderStep();
    await loadResults();
  } catch (error) {
    state.mode = "error";
    el.statusText.textContent = `Could not connect to local SQLite server: ${error.message}`;
  }
}

function bindControls() {
  el.groupSelect.addEventListener("change", () => {
    state.groupId = el.groupSelect.value;
    state.selectedSymbol = null;
    loadResults();
  });
  el.dateSelect.addEventListener("change", () => {
    state.date = el.dateSelect.value;
    state.selectedSymbol = null;
    loadResults();
  });
  el.searchInput.addEventListener("input", debounce(() => {
    state.search = el.searchInput.value.trim();
    state.selectedSymbol = null;
    loadResults();
  }, 250));
  [el.minPriceInput, el.maxPriceInput].forEach((input) => {
    input.addEventListener("input", debounce(() => {
      state.minPrice = Number(el.minPriceInput.value) || 0;
      state.maxPrice = Number(el.maxPriceInput.value) || 0;
      state.selectedSymbol = null;
      loadResults();
    }, 300));
  });
  el.runButton.addEventListener("click", () => loadResults());
}

async function loadResults() {
  if (!state.date) return;
  setLoading();
  const params = new URLSearchParams({
    group: state.groupId,
    date: state.date,
    search: state.search,
    minPrice: state.minPrice,
    maxPrice: state.maxPrice,
    limit: 200,
  });
  const payload = await fetchJson(`/api/recommendations?${params.toString()}`);
  state.results = payload.results || [];
  state.metrics = payload.metrics || {};
  state.selectedSymbol = state.results.find((row) => row.symbol === state.selectedSymbol)?.symbol || state.results[0]?.symbol || null;
  if (state.selectedSymbol) {
    const pricePayload = await fetchJson(`/api/prices?symbol=${encodeURIComponent(state.selectedSymbol)}&date=${encodeURIComponent(state.date)}`);
    state.prices = pricePayload.prices || [];
  } else {
    state.prices = [];
  }
  render();
}

async function selectStock(symbol) {
  state.selectedSymbol = symbol;
  const pricePayload = await fetchJson(`/api/prices?symbol=${encodeURIComponent(symbol)}&date=${encodeURIComponent(state.date)}`);
  state.prices = pricePayload.prices || [];
  render();
}

function render() {
  renderStatus();
  renderMetrics();
  renderTable();
  renderDetails();
}

function renderSelectors() {
  el.groupSelect.innerHTML = state.groups.map((group) => {
    return `<option value="${escapeHtml(group.id)}" title="${escapeHtml(group.description || "")}">${escapeHtml(group.name)}</option>`;
  }).join("");
  el.groupSelect.value = state.groupId;
  el.dateSelect.innerHTML = state.dates.map((date) => `<option value="${date}">${formatDate(date)}</option>`).join("");
  el.dateSelect.value = state.date;
}

function renderInputs() {
  el.minPriceInput.value = state.minPrice;
  el.maxPriceInput.value = state.maxPrice;
}

function renderStep() {
  const step = state.activeStep || {};
  el.stepName.textContent = `Step ${step.step || 1}: ${step.name || "Price Range Filter"}`;
  el.stepMeaning.textContent = step.plainMeaning || "";
  el.stepDecision.textContent = `Current test: pass stocks closing between Rs. ${state.minPrice} and Rs. ${state.maxPrice}.`;
}

function renderStatus() {
  el.statusText.textContent = state.stats
    ? `SQLite connected: ${formatNumber(state.stats.stock_count)} NSE stocks, ${formatNumber(state.stats.price_count)} EOD rows.`
    : "SQLite connected.";
  renderStep();
}

function renderMetrics() {
  const metrics = state.metrics || {};
  const rows = [
    ["Eligible stocks", metrics.eligibleStocks ?? 0],
    ["Avg next-day move", formatPct(metrics.avgNextDayMove ?? 0)],
    ["Next-day positive", formatPct((metrics.nextDayPositiveRate ?? 0) * 100)],
    ["Pending outcomes", metrics.pendingOutcomes ?? 0],
  ];
  el.metricsGrid.innerHTML = rows.map(([label, value]) => `
    <div class="metric">
      <span>${label}</span>
      <strong>${value}</strong>
    </div>
  `).join("");
}

function renderTable() {
  el.resultMeta.textContent = `${formatDate(state.date)} close - ${formatNumber(state.results.length)} shown`;
  if (!state.results.length) {
    el.resultsBody.innerHTML = `<tr><td colspan="6" class="empty-state">No NSE stocks passed this price range.</td></tr>`;
    return;
  }
  el.resultsBody.innerHTML = state.results.map((item) => {
    const nextClass = item.nextDayReturn > 0 ? "positive" : item.nextDayReturn < 0 ? "negative" : "neutral";
    return `
      <tr class="${item.symbol === state.selectedSymbol ? "active" : ""}" data-symbol="${escapeHtml(item.symbol)}">
        <td class="stock-name"><strong>${escapeHtml(item.symbol)}</strong><span>${escapeHtml(item.name || item.symbol)}</span></td>
        <td>${escapeHtml(item.status)}</td>
        <td>Rs. ${formatMoney(item.close)}</td>
        <td>${formatNumber(item.volume)}</td>
        <td class="${nextClass}">${item.nextDayReturn == null ? "Pending" : formatPct(item.nextDayReturn)}</td>
        <td>${escapeHtml(item.reason)}</td>
      </tr>
    `;
  }).join("");
  el.resultsBody.querySelectorAll("tr[data-symbol]").forEach((row) => {
    row.addEventListener("click", () => selectStock(row.dataset.symbol));
  });
}

function renderDetails() {
  const item = state.results.find((row) => row.symbol === state.selectedSymbol);
  if (!item) {
    el.selectedTitle.textContent = "Stock detail";
    el.chart.innerHTML = "";
    el.details.innerHTML = `<div class="empty-state">Select a stock to inspect price history.</div>`;
    return;
  }
  el.selectedTitle.textContent = `${item.symbol} - ${item.name || item.symbol}`;
  el.chart.innerHTML = lineChart(state.prices);
  const nextClose = item.nextClose == null ? "Pending" : `Rs. ${formatMoney(item.nextClose)} (${formatPct(item.nextDayReturn)})`;
  el.details.innerHTML = `
    <div class="detail-block">
      <h3>Why It Passed</h3>
      <ul>
        <li>${escapeHtml(item.reason)}</li>
        <li>This is not a buy recommendation yet. It is only Step 1 universe filtering.</li>
      </ul>
    </div>
    <div class="detail-block">
      <h3>Outcome Check</h3>
      <ul>
        <li>Signal date close: Rs. ${formatMoney(item.close)}</li>
        <li>Next trading date: ${formatDate(item.nextDate)}</li>
        <li>Next close: ${nextClose}</li>
      </ul>
    </div>
  `;
}

function setLoading() {
  el.resultsBody.innerHTML = `<tr><td colspan="6" class="empty-state">Applying price range filter...</td></tr>`;
}

function lineChart(series) {
  if (!series?.length) return "";
  const width = 640;
  const height = 220;
  const padding = 28;
  const values = series.map((item) => item.close);
  const min = Math.min(...values) * 0.995;
  const max = Math.max(...values) * 1.005;
  const points = series.map((item, index) => {
    const x = padding + (index / Math.max(1, series.length - 1)) * (width - padding * 2);
    const y = height - padding - ((item.close - min) / Math.max(1, max - min)) * (height - padding * 2);
    return [x, y];
  });
  const path = points.map(([x, y], index) => `${index === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const last = points[points.length - 1];
  return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Recent closing price chart">
    <line x1="${padding}" x2="${width - padding}" y1="${height - padding}" y2="${height - padding}" stroke="#dbe1d8" />
    <path d="${path}" fill="none" stroke="#255f91" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" />
    <circle cx="${last[0]}" cy="${last[1]}" r="6" fill="#17211b" />
    <text x="${padding}" y="24" fill="#637064" font-size="13">Last ${series.length} closes</text>
    <text x="${width - padding}" y="${height - 8}" fill="#637064" font-size="12" text-anchor="end">${formatDate(series[series.length - 1].date)}</text>
  </svg>`;
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `${response.status} ${response.statusText}`);
  return data;
}

function debounce(fn, delay) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;" }[char]));
}

function formatDate(value) {
  if (!value) return "Pending";
  return new Date(`${value}T00:00:00`).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

function formatMoney(value) {
  return Number(value).toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

function formatNumber(value) {
  return Number(value).toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

function formatPct(value) {
  return `${value > 0 ? "+" : ""}${Number(value).toFixed(2)}%`;
}
