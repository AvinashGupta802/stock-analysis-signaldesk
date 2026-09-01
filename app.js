const STORAGE_KEY = "signaldesk.buyRules.v1";

const state = {
  groups: [],
  dates: [],
  stats: null,
  filterLibrary: [],
  rules: [],
  activeRuleIndex: 0,
  groupId: "all",
  date: null,
  search: "",
  results: [],
  metrics: {},
  prices: [],
  selectedSymbol: null,
  backtest: null,
};

const el = {
  ruleSelect: document.querySelector("#ruleSelect"),
  ruleNameInput: document.querySelector("#ruleNameInput"),
  saveRuleButton: document.querySelector("#saveRuleButton"),
  newRuleButton: document.querySelector("#newRuleButton"),
  groupSelect: document.querySelector("#groupSelect"),
  dateSelect: document.querySelector("#dateSelect"),
  searchInput: document.querySelector("#searchInput"),
  filterLibrary: document.querySelector("#filterLibrary"),
  selectedFilters: document.querySelector("#selectedFilters"),
  topNInput: document.querySelector("#topNInput"),
  capitalInput: document.querySelector("#capitalInput"),
  targetInput: document.querySelector("#targetInput"),
  stopInput: document.querySelector("#stopInput"),
  backtestButton: document.querySelector("#backtestButton"),
  statusText: document.querySelector("#statusText"),
  pageTitle: document.querySelector("#pageTitle"),
  metricsGrid: document.querySelector("#metricsGrid"),
  resultMeta: document.querySelector("#resultMeta"),
  backtestSummary: document.querySelector("#backtestSummary"),
  resultsBody: document.querySelector("#resultsBody"),
  selectedTitle: document.querySelector("#selectedTitle"),
  ruleMeaning: document.querySelector("#ruleMeaning"),
  chart: document.querySelector("#chart"),
  details: document.querySelector("#details"),
};

init();

async function init() {
  bindShell();
  const bootstrap = await fetchJson("/api/bootstrap");
  state.groups = bootstrap.groups || [];
  state.dates = bootstrap.dates || [];
  state.stats = bootstrap.stats;
  state.filterLibrary = bootstrap.filterLibrary || [];
  state.rules = loadSavedRules(bootstrap.defaultRule);
  state.groupId = state.groups[0]?.id || "all";
  state.date = state.dates[state.dates.length - 1];
  renderAll();
  await runRuleScan();
}

function bindShell() {
  el.ruleSelect.addEventListener("change", () => {
    state.activeRuleIndex = Number(el.ruleSelect.value);
    state.backtest = null;
    renderAll();
    runRuleScan();
  });
  el.saveRuleButton.addEventListener("click", () => {
    currentRule().name = el.ruleNameInput.value.trim() || "Untitled Rule";
    saveRules();
    renderAll();
  });
  el.newRuleButton.addEventListener("click", () => {
    state.rules.push({ name: "New Buy Rule", filters: [] });
    state.activeRuleIndex = state.rules.length - 1;
    state.backtest = null;
    saveRules();
    renderAll();
    runRuleScan();
  });
  el.groupSelect.addEventListener("change", () => {
    state.groupId = el.groupSelect.value;
    runRuleScan();
  });
  el.dateSelect.addEventListener("change", () => {
    state.date = el.dateSelect.value;
    state.selectedSymbol = null;
    runRuleScan();
  });
  el.searchInput.addEventListener("input", debounce(() => {
    state.search = el.searchInput.value.trim();
    state.selectedSymbol = null;
    runRuleScan();
  }, 250));
  el.backtestButton.addEventListener("click", runBacktest);
}

function renderAll() {
  renderRuleSelect();
  renderSelectors();
  renderFilterLibrary();
  renderSelectedFilters();
  renderRuleMeaning();
  renderStatus();
  renderMetrics();
  renderTable();
  renderDetails();
  renderBacktest();
}

function renderRuleSelect() {
  el.ruleSelect.innerHTML = state.rules.map((rule, index) => `<option value="${index}">${escapeHtml(rule.name)}</option>`).join("");
  el.ruleSelect.value = state.activeRuleIndex;
  el.ruleNameInput.value = currentRule().name;
  el.pageTitle.textContent = currentRule().name;
}

function renderSelectors() {
  el.groupSelect.innerHTML = state.groups.map((group) => `<option value="${escapeHtml(group.id)}">${escapeHtml(group.name)}</option>`).join("");
  el.groupSelect.value = state.groupId;
  el.dateSelect.innerHTML = state.dates.map((date) => `<option value="${date}">${formatDate(date)}</option>`).join("");
  el.dateSelect.value = state.date;
}

function renderFilterLibrary() {
  el.filterLibrary.innerHTML = state.filterLibrary.map((filter) => `
    <div class="rule-item">
      <strong>${escapeHtml(filter.name)}</strong>
      <span>${escapeHtml(filter.category)}: ${escapeHtml(filter.meaning)}</span>
      <button type="button" data-add-filter="${escapeHtml(filter.id)}">Add filter</button>
    </div>
  `).join("");
  el.filterLibrary.querySelectorAll("button[data-add-filter]").forEach((button) => {
    button.addEventListener("click", () => addFilter(button.dataset.addFilter));
  });
}

function renderSelectedFilters() {
  const rule = currentRule();
  if (!rule.filters.length) {
    el.selectedFilters.innerHTML = `<div class="empty-state">No filters selected. Add one filter to make this rule testable.</div>`;
    return;
  }
  el.selectedFilters.innerHTML = rule.filters.map((selected, index) => {
    const definition = filterDefinition(selected.id);
    const fields = (definition?.fields || []).map((field) => `
      <label>${escapeHtml(field.label)}
        <input type="number" step="${field.step}" value="${selected.values[field.key]}" data-filter-index="${index}" data-field-key="${escapeHtml(field.key)}" />
      </label>
    `).join("");
    return `
      <div class="rule-item selected-rule">
        <strong>${escapeHtml(definition?.name || selected.id)}</strong>
        <span>${escapeHtml(definition?.meaning || "")}</span>
        <div class="input-grid two-col">${fields}</div>
        <button type="button" data-remove-filter="${index}">Remove</button>
      </div>
    `;
  }).join("");
  el.selectedFilters.querySelectorAll("input[data-filter-index]").forEach((input) => {
    input.addEventListener("input", debounce(() => {
      const filter = currentRule().filters[Number(input.dataset.filterIndex)];
      filter.values[input.dataset.fieldKey] = Number(input.value) || 0;
      saveRules();
      runRuleScan();
      renderRuleMeaning();
    }, 300));
  });
  el.selectedFilters.querySelectorAll("button[data-remove-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      currentRule().filters.splice(Number(button.dataset.removeFilter), 1);
      state.backtest = null;
      saveRules();
      renderAll();
      runRuleScan();
    });
  });
}

function renderRuleMeaning() {
  const rule = currentRule();
  if (!rule.filters.length) {
    el.ruleMeaning.innerHTML = `<div class="empty-state">This rule has no filters yet.</div>`;
    return;
  }
  el.ruleMeaning.innerHTML = `
    <div class="detail-block">
      <h3>Rule Logic</h3>
      <p>A stock passes only when all selected filters pass.</p>
      <ul>
        ${rule.filters.map((selected) => {
          const definition = filterDefinition(selected.id);
          return `<li><strong>${escapeHtml(definition?.name || selected.id)}:</strong> ${escapeHtml(humanValues(selected))}</li>`;
        }).join("")}
      </ul>
    </div>
  `;
}

function renderStatus() {
  el.statusText.textContent = state.stats
    ? `SQLite connected: ${formatNumber(state.stats.stock_count)} NSE stocks, ${formatNumber(state.stats.price_count)} EOD rows, ${formatNumber(state.stats.delivery_count || 0)} delivery rows.`
    : "SQLite connected.";
}

function renderMetrics() {
  const rows = [
    ["Passed stocks", state.metrics.passedStocks ?? 0],
    ["Avg next-day", formatPct(state.metrics.avgNextDayMove ?? 0)],
    ["Next-day positive", formatPct(state.metrics.nextDayPositiveRate ?? 0)],
    ["Pending", state.metrics.pendingOutcomes ?? 0],
  ];
  el.metricsGrid.innerHTML = rows.map(([label, value]) => `<div class="metric"><span>${label}</span><strong>${value}</strong></div>`).join("");
}

function renderTable() {
  el.resultMeta.textContent = `${formatDate(state.date)} close - ${formatNumber(state.results.length)} shown`;
  if (!state.results.length) {
    el.resultsBody.innerHTML = `<tr><td colspan="8" class="empty-state">No stocks passed this rule.</td></tr>`;
    return;
  }
  el.resultsBody.innerHTML = state.results.map((item) => `
    <tr class="${item.symbol === state.selectedSymbol ? "active" : ""}" data-symbol="${escapeHtml(item.symbol)}">
      <td class="stock-name"><strong>${escapeHtml(item.symbol)}</strong><span>${escapeHtml(item.name)}</span></td>
      <td>Rs. ${formatMoney(item.close)}</td>
      <td>${formatNumber(item.volume)}</td>
      <td>${Number(item.relativeVolume || 0).toFixed(2)}x</td>
      <td>${item.deliveryPct == null ? "N/A" : formatPlainPct(item.deliveryPct)}</td>
      <td>${formatNumber(item.adv20)}</td>
      <td>${Number(item.rsi14).toFixed(2)}</td>
      <td class="${item.nextDayReturn > 0 ? "positive" : item.nextDayReturn < 0 ? "negative" : "neutral"}">${item.nextDayReturn == null ? "Pending" : formatPct(item.nextDayReturn)}</td>
    </tr>
  `).join("");
  el.resultsBody.querySelectorAll("tr[data-symbol]").forEach((row) => {
    row.addEventListener("click", () => selectStock(row.dataset.symbol));
  });
}

function renderDetails() {
  const item = state.results.find((row) => row.symbol === state.selectedSymbol);
  if (!item) {
    el.selectedTitle.textContent = "Stock detail";
    el.chart.innerHTML = "";
    el.details.innerHTML = `<div class="empty-state">Select a stock to see why it passed.</div>`;
    return;
  }
  el.selectedTitle.textContent = `${item.symbol} - ${item.name}`;
  el.chart.innerHTML = lineChart(state.prices);
  el.details.innerHTML = `
    <div class="detail-block">
      <h3>Delivery</h3>
      <p>Delivery ${item.deliveryPct == null ? "N/A" : formatPlainPct(item.deliveryPct)}${item.deliverableQty == null ? "" : `, delivered quantity ${formatNumber(item.deliverableQty)}`}.</p>
      <p>Volume is ${Number(item.relativeVolume || 0).toFixed(2)}x of its 20-day average.</p>
    </div>
    <div class="detail-block">
      <h3>Filter Results</h3>
      <ul>${item.reasons.map((reason) => `<li>${escapeHtml(reason.filter)}: ${reason.passed ? "Pass" : "Fail"} - ${escapeHtml(reason.reason)}</li>`).join("")}</ul>
    </div>
  `;
}

function renderBacktest() {
  if (!state.backtest) {
    el.backtestSummary.innerHTML = "";
    return;
  }
  const summary = state.backtest.summary;
  el.backtestSummary.innerHTML = `
    <div class="detail-block">
      <h3>Backtest Result</h3>
      <p>${formatNumber(summary.trades)} trades, P/L Rs. ${formatMoney(summary.netPnl)}, return on turnover ${formatPct(summary.returnOnTurnoverPct)}.</p>
      <p>Win ${formatPct(summary.winRatePct)}, target hit ${formatPct(summary.targetHitPct)}, stop hit ${formatPct(summary.stopHitPct)}.</p>
    </div>
  `;
}

async function runRuleScan() {
  const payload = {
    rule: currentRule(),
    group: state.groupId,
    date: state.date,
    search: state.search,
    limit: 200,
  };
  el.resultsBody.innerHTML = `<tr><td colspan="8" class="empty-state">Running rule...</td></tr>`;
  const result = await postJson("/api/rule/results", payload);
  state.results = result.results || [];
  state.metrics = result.metrics || {};
  state.selectedSymbol = state.results.find((row) => row.symbol === state.selectedSymbol)?.symbol || state.results[0]?.symbol || null;
  if (state.selectedSymbol) {
    const prices = await fetchJson(`/api/prices?symbol=${encodeURIComponent(state.selectedSymbol)}&date=${encodeURIComponent(state.date)}`);
    state.prices = prices.prices || [];
  } else {
    state.prices = [];
  }
  renderAll();
}

async function runBacktest() {
  el.backtestButton.disabled = true;
  el.backtestButton.textContent = "Backtesting...";
  try {
    state.backtest = await postJson("/api/rule/backtest", {
      rule: currentRule(),
      group: state.groupId,
      fromDate: "2024-08-15",
      toDate: "2026-08-24",
      topN: Number(el.topNInput.value) || 10,
      capitalPerStock: Number(el.capitalInput.value) || 10000,
      targetPct: Number(el.targetInput.value) || 5,
      stopPct: Number(el.stopInput.value) || 5,
      maxHoldDays: 5,
    });
    renderBacktest();
  } finally {
    el.backtestButton.disabled = false;
    el.backtestButton.textContent = "Backtest rule";
  }
}

async function selectStock(symbol) {
  state.selectedSymbol = symbol;
  const prices = await fetchJson(`/api/prices?symbol=${encodeURIComponent(symbol)}&date=${encodeURIComponent(state.date)}`);
  state.prices = prices.prices || [];
  renderTable();
  renderDetails();
}

function addFilter(filterId) {
  const definition = filterDefinition(filterId);
  if (!definition) return;
  const values = Object.fromEntries(definition.fields.map((field) => [field.key, field.default]));
  currentRule().filters.push({ id: filterId, values });
  state.backtest = null;
  saveRules();
  renderAll();
  runRuleScan();
}

function currentRule() {
  return state.rules[state.activeRuleIndex] || state.rules[0];
}

function filterDefinition(filterId) {
  return state.filterLibrary.find((filter) => filter.id === filterId);
}

function humanValues(selected) {
  const values = selected.values || {};
  if (selected.id === "price_range") return `Close between Rs. ${values.minPrice} and Rs. ${values.maxPrice}`;
  if (selected.id === "adv20_min") return `20D average volume at least ${formatNumber(values.minAdv20)}`;
  if (selected.id === "relative_volume") return `Today volume between ${values.minRelativeVolume}x and ${values.maxRelativeVolume}x of 20D average volume`;
  if (selected.id === "delivery_pct_range") return `Delivery percentage between ${values.minDeliveryPct}% and ${values.maxDeliveryPct}%`;
  if (selected.id === "rsi14_range") return `RSI 14 between ${values.rsiMin} and ${values.rsiMax}`;
  return JSON.stringify(values);
}

function loadSavedRules(defaultRule) {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
    if (Array.isArray(saved) && saved.length) return saved;
  } catch (error) {
    console.warn("Could not load saved rules", error);
  }
  return [defaultRule];
}

function saveRules() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state.rules));
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
  </svg>`;
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

function formatPlainPct(value) {
  return `${Number(value).toFixed(2)}%`;
}
