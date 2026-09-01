const DEMO_GROUPS = [
  { id: "nifty-core", name: "Demo Watchlist", description: "Fallback demo data", symbols: ["RELIANCE", "HDFCBANK", "INFY", "ICICIBANK", "TCS", "LT"] },
];

const seedCandles = {
  RELIANCE: [2862, 2870, 2894, 2882, 2912, 2928, 2944, 2938, 2965, 2982, 2974, 3008, 3036],
  HDFCBANK: [1594, 1608, 1612, 1601, 1624, 1638, 1645, 1658, 1672, 1664, 1686, 1704, 1712],
  INFY: [1512, 1504, 1492, 1480, 1474, 1488, 1501, 1516, 1538, 1552, 1561, 1584, 1602],
  ICICIBANK: [1110, 1118, 1131, 1126, 1144, 1165, 1172, 1184, 1196, 1188, 1208, 1224, 1232],
  TCS: [3890, 3862, 3844, 3828, 3842, 3866, 3898, 3924, 3912, 3936, 3962, 3984, 3992],
  LT: [3520, 3544, 3568, 3551, 3588, 3614, 3650, 3636, 3678, 3710, 3694, 3738, 3772],
};

const mockDates = ["2026-07-29", "2026-07-30", "2026-07-31", "2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07", "2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14"];

const demoCandles = Object.fromEntries(
  Object.entries(seedCandles).map(([symbol, closes]) => [
    symbol,
    closes.map((close, index) => ({
      date: mockDates[index],
      open: round(index === 0 ? close * 0.996 : closes[index - 1]),
      high: round(close * 1.01),
      low: round(close * 0.99),
      close,
      volume: Math.round(850000 + close * 180 + index * 38000),
    })),
  ])
);

const state = {
  mode: "loading",
  groups: [],
  dates: [],
  stats: null,
  groupId: "liquid",
  date: null,
  threshold: 5,
  selectedSymbol: null,
  results: [],
  metrics: null,
  prices: [],
  filters: [],
  rules: [],
  selectedFilters: [],
  selectedRules: [],
  search: "",
  showHold: false,
  signalView: "long",
  filterConfig: {
    minPrice: 100,
    maxPrice: 500,
    minAdv20: 1000000,
    relVolumeMin: 1.5,
    rsiMin: 50,
    rsiMax: 68,
    ema9DistanceMax: 5,
    quietNearHighPct: 5,
    quietRoc3Min: 1.5,
  },
};

const el = {
  groupSelect: document.querySelector("#groupSelect"),
  dateSelect: document.querySelector("#dateSelect"),
  thresholdInput: document.querySelector("#thresholdInput"),
  thresholdValue: document.querySelector("#thresholdValue"),
  importInput: document.querySelector("#importInput"),
  importStatus: document.querySelector("#importStatus"),
  clearImportsButton: document.querySelector("#clearImportsButton"),
  ruleCount: document.querySelector("#ruleCount"),
  rulesList: document.querySelector("#rulesList"),
  metricsGrid: document.querySelector("#metricsGrid"),
  recommendationMeta: document.querySelector("#recommendationMeta"),
  recommendationsBody: document.querySelector("#recommendationsBody"),
  selectedStockTitle: document.querySelector("#selectedStockTitle"),
  selectedSignalPill: document.querySelector("#selectedSignalPill"),
  stockChart: document.querySelector("#stockChart"),
  stockDetails: document.querySelector("#stockDetails"),
  pageTitle: document.querySelector("#pageTitle"),
  filtersList: document.querySelector("#filtersList"),
  filterCount: document.querySelector("#filterCount"),
  ruleControls: document.querySelector("#ruleControls"),
  selectedRuleCount: document.querySelector("#selectedRuleCount"),
  stockSearchInput: document.querySelector("#stockSearchInput"),
  showHoldInput: document.querySelector("#showHoldInput"),
  signalViewSelect: document.querySelector("#signalViewSelect"),
  customGroupName: document.querySelector("#customGroupName"),
  customGroupSymbols: document.querySelector("#customGroupSymbols"),
  saveGroupButton: document.querySelector("#saveGroupButton"),
  customGroupStatus: document.querySelector("#customGroupStatus"),
  minPriceInput: document.querySelector("#minPriceInput"),
  maxPriceInput: document.querySelector("#maxPriceInput"),
  minAdv20Input: document.querySelector("#minAdv20Input"),
  relVolumeMinInput: document.querySelector("#relVolumeMinInput"),
  rsiMinInput: document.querySelector("#rsiMinInput"),
  rsiMaxInput: document.querySelector("#rsiMaxInput"),
  ema9DistanceMaxInput: document.querySelector("#ema9DistanceMaxInput"),
  quietNearHighPctInput: document.querySelector("#quietNearHighPctInput"),
  quietRoc3MinInput: document.querySelector("#quietRoc3MinInput"),
};

init();

async function init() {
  el.thresholdInput.value = state.threshold;
  el.thresholdInput.addEventListener("input", () => {
    state.threshold = Number(el.thresholdInput.value);
    loadRecommendations();
  });
  el.groupSelect.addEventListener("change", () => {
    state.groupId = el.groupSelect.value;
    state.selectedSymbol = null;
    loadRecommendations();
  });
  el.dateSelect.addEventListener("change", () => {
    state.date = el.dateSelect.value;
    state.selectedSymbol = null;
    loadRecommendations();
  });

  bindSearchControls();
  bindCustomGroupControls();
  bindFilterValueControls();
  if (el.importInput) el.importInput.disabled = true;
  if (el.clearImportsButton) el.clearImportsButton.disabled = true;
  renderRules();

  try {
    const bootstrap = await fetchJson("/api/bootstrap");
    state.mode = "sqlite";
    state.groups = bootstrap.groups;
    state.dates = bootstrap.dates;
    state.stats = bootstrap.stats;
    state.filters = bootstrap.filters || [];
    state.rules = bootstrap.rules || [];
    state.selectedFilters = bootstrap.defaults?.filters || [];
    state.filterConfig = { ...state.filterConfig, ...(bootstrap.defaults?.filterConfig || {}) };
    state.selectedRules = bootstrap.defaults?.rules || [];
    state.groupId = state.groups[0]?.id || "liquid";
    state.date = state.dates[state.dates.length - 1];
    renderSelectors();
    renderFilterValueControls();
    renderRuleControls();
    await loadRecommendations();
  } catch (error) {
    console.warn("SQLite API unavailable, using demo fallback", error);
    setupDemoMode();
  }
}

function bindSearchControls() {
  if (el.stockSearchInput) {
    el.stockSearchInput.addEventListener("input", debounce(() => {
      state.search = el.stockSearchInput.value;
      state.selectedSymbol = null;
      loadRecommendations();
    }, 250));
  }
  if (el.showHoldInput) {
    el.showHoldInput.addEventListener("change", () => {
      state.showHold = el.showHoldInput.checked;
      state.selectedSymbol = null;
      loadRecommendations();
    });
  }
  if (el.signalViewSelect) {
    el.signalViewSelect.addEventListener("change", () => {
      state.signalView = el.signalViewSelect.value;
      state.selectedSymbol = null;
      loadRecommendations();
    });
  }
}


function bindCustomGroupControls() {
  if (!el.saveGroupButton) return;
  el.saveGroupButton.addEventListener("click", async () => {
    const name = el.customGroupName.value.trim();
    const symbols = el.customGroupSymbols.value.trim();
    if (!name || !symbols) {
      el.customGroupStatus.textContent = "Enter group name and symbols.";
      return;
    }
    el.saveGroupButton.disabled = true;
    el.customGroupStatus.textContent = "Saving group...";
    try {
      const payload = await postJson("/api/groups", { name, symbols });
      if (payload.error) throw new Error(payload.error);
      const bootstrap = await fetchJson("/api/bootstrap");
      state.groups = bootstrap.groups;
      state.groupId = payload.id;
      state.selectedSymbol = null;
      renderSelectors();
      el.customGroupStatus.textContent = `Saved ${payload.added.length} symbols${payload.missing.length ? `, missing: ${payload.missing.join(", ")}` : ""}.`;
      await loadRecommendations();
    } catch (error) {
      el.customGroupStatus.textContent = error.message;
    } finally {
      el.saveGroupButton.disabled = false;
    }
  });
}
function bindFilterValueControls() {
  const bindings = [
    [el.minPriceInput, "minPrice"],
    [el.maxPriceInput, "maxPrice"],
    [el.minAdv20Input, "minAdv20"],
    [el.relVolumeMinInput, "relVolumeMin"],
    [el.rsiMinInput, "rsiMin"],
    [el.rsiMaxInput, "rsiMax"],
    [el.ema9DistanceMaxInput, "ema9DistanceMax"],
    [el.quietNearHighPctInput, "quietNearHighPct"],
    [el.quietRoc3MinInput, "quietRoc3Min"],
  ];
  bindings.forEach(([input, key]) => {
    if (!input) return;
    input.addEventListener("input", debounce(() => {
      state.filterConfig[key] = Number(input.value) || 0;
      state.selectedSymbol = null;
      loadRecommendations();
    }, 350));
  });
}

function renderFilterValueControls() {
  if (el.minPriceInput) el.minPriceInput.value = state.filterConfig.minPrice;
  if (el.maxPriceInput) el.maxPriceInput.value = state.filterConfig.maxPrice;
  if (el.minAdv20Input) el.minAdv20Input.value = state.filterConfig.minAdv20;
  if (el.relVolumeMinInput) el.relVolumeMinInput.value = state.filterConfig.relVolumeMin;
  if (el.rsiMinInput) el.rsiMinInput.value = state.filterConfig.rsiMin;
  if (el.rsiMaxInput) el.rsiMaxInput.value = state.filterConfig.rsiMax;
  if (el.ema9DistanceMaxInput) el.ema9DistanceMaxInput.value = state.filterConfig.ema9DistanceMax;
  if (el.quietNearHighPctInput) el.quietNearHighPctInput.value = state.filterConfig.quietNearHighPct;
  if (el.quietRoc3MinInput) el.quietRoc3MinInput.value = state.filterConfig.quietRoc3Min;
}

function debounce(fn, delay) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
}
function renderSelectors() {
  el.groupSelect.innerHTML = state.groups.map((group) => {
    const suffix = group.kind === "nse_index" ? " (NSE index)" : "";
    return `<option value="${group.id}" title="${escapeHtml(group.description || "")}">${group.name}${suffix}</option>`;
  }).join("");
  el.groupSelect.value = state.groupId;
  el.dateSelect.innerHTML = state.dates.map((date) => `<option value="${date}">${formatDate(date)}</option>`).join("");
  el.dateSelect.value = state.date;
  if (el.signalViewSelect) el.signalViewSelect.value = state.signalView;
}

async function loadRecommendations() {
  if (state.mode === "demo") return renderDemo();
  setLoadingState();
  const filterParam = encodeURIComponent(state.selectedFilters.join(","));
  const ruleParam = encodeURIComponent(state.selectedRules.join(","));
  const searchParam = encodeURIComponent(state.search.trim());
  const includeHoldParam = state.showHold || state.search.trim() ? "1" : "0";
  const valueParams = new URLSearchParams({
    minPrice: state.filterConfig.minPrice,
    maxPrice: state.filterConfig.maxPrice,
    minAdv20: state.filterConfig.minAdv20,
    relVolumeMin: state.filterConfig.relVolumeMin,
    rsiMin: state.filterConfig.rsiMin,
    rsiMax: state.filterConfig.rsiMax,
    ema9DistanceMax: state.filterConfig.ema9DistanceMax,
    quietNearHighPct: state.filterConfig.quietNearHighPct,
    quietRoc3Min: state.filterConfig.quietRoc3Min,
  });
  const payload = await fetchJson(`/api/recommendations?${valueParams.toString()}&group=${encodeURIComponent(state.groupId)}&date=${encodeURIComponent(state.date)}&threshold=${state.threshold}&filters=${filterParam}&rules=${ruleParam}&search=${searchParam}&includeHold=${includeHoldParam}&signalView=${encodeURIComponent(state.signalView)}&limit=200`);
  state.results = payload.results;
  state.metrics = payload.metrics;
  state.selectedSymbol = state.results.find((row) => row.symbol === state.selectedSymbol)?.symbol || state.results[0]?.symbol || null;
  if (state.selectedSymbol) {
    const pricePayload = await fetchJson(`/api/prices?symbol=${encodeURIComponent(state.selectedSymbol)}&date=${encodeURIComponent(state.date)}`);
    state.prices = pricePayload.prices;
  } else {
    state.prices = [];
  }
  render();
}

async function selectStock(symbol) {
  state.selectedSymbol = symbol;
  if (state.mode === "sqlite") {
    const pricePayload = await fetchJson(`/api/prices?symbol=${encodeURIComponent(symbol)}&date=${encodeURIComponent(state.date)}`);
    state.prices = pricePayload.prices;
  }
  render();
}

function render() {
  const group = state.groups.find((item) => item.id === state.groupId) || state.groups[0];
  const selected = state.results.find((item) => item.symbol === state.selectedSymbol) || state.results[0];
  el.thresholdValue.textContent = state.threshold;
  el.pageTitle.textContent = `${group?.name || "EOD recommendations"} - ${viewLabel(state.signalView)}`;
  el.recommendationMeta.textContent = `${formatDate(state.date)} close - ${state.results.length.toLocaleString("en-IN")} shown`;
  el.importStatus.textContent = state.mode === "sqlite"
    ? `SQLite connected: ${Number(state.stats.stock_count).toLocaleString("en-IN")} stocks, ${Number(state.stats.price_count).toLocaleString("en-IN")} price rows`
    : "Demo fallback mode. Start the local server to use SQLite.";
  renderMetrics(state.metrics);
  renderTable(state.results);
  renderDetails(selected);
}

function viewLabel(value) {
  if (value === "long") return "Long";
  if (value === "short") return "Short";
  if (value === "hold") return "Hold";
  return "All";
}
function renderRuleControls() {
  if (!el.filtersList || !el.ruleControls) return;
  el.filtersList.innerHTML = state.filters.map((filter) => checkboxTemplate("filter", filter, state.selectedFilters.includes(filter.id))).join("");
  el.ruleControls.innerHTML = state.rules.map((rule) => checkboxTemplate("rule", rule, state.selectedRules.includes(rule.id))).join("");
  el.filtersList.querySelectorAll("input[data-id]").forEach((input) => {
    input.addEventListener("change", () => {
      state.selectedFilters = toggleSelection(state.selectedFilters, input.dataset.id, input.checked);
      loadRecommendations();
    });
  });
  el.ruleControls.querySelectorAll("input[data-id]").forEach((input) => {
    input.addEventListener("change", () => {
      state.selectedRules = toggleSelection(state.selectedRules, input.dataset.id, input.checked);
      loadRecommendations();
    });
  });
  renderSelectionCounts();
}

function checkboxTemplate(kind, item, checked) {
  const meta = item.side ? `${item.side.toUpperCase()} - Weight ${item.weight}. ${item.description}` : item.description;
  return `
    <label class="check-item">
      <input type="checkbox" data-kind="${kind}" data-id="${item.id}" ${checked ? "checked" : ""} />
      <span><strong>${item.name}</strong><small>${meta}</small></span>
    </label>
  `;
}

function toggleSelection(values, id, checked) {
  const next = new Set(values);
  if (checked) next.add(id);
  else next.delete(id);
  return Array.from(next);
}

function renderSelectionCounts() {
  if (el.filterCount) el.filterCount.textContent = `${state.selectedFilters.length} on`;
  if (el.selectedRuleCount) el.selectedRuleCount.textContent = `${state.selectedRules.length} on`;
}
function renderRules() {
  const rules = [
    ["Base filters", "NSE stock must pass price, ADV, RSI, EMA9 distance, and one-day move limits."],
    ["Volume breakout", "Buy setup when current volume is above the relative-volume value and price closes positive."],
    ["Quiet pre-breakout", "Buy setup when close is near the 20-day high and 3-day ROC is improving."],
    ["Trend and momentum score", "Extra points for close above 5/20 DMA, recent momentum, and strong daily close."],
  ];
  el.ruleCount.textContent = `${rules.length} rules`;
  el.rulesList.innerHTML = rules.map(([name, text]) => `<div class="rule-item"><strong>${name}</strong><span>${text}</span></div>`).join("");
}

function renderMetrics(metrics = {}) {
  const rows = [
    ["Buy candidates", metrics.buyCandidates ?? 0],
    ["Filtered signals", metrics.totalSignals ?? 0],
    ["Avg next-day move", formatPct(metrics.avgNextDayMove ?? 0)],
    ["Signal hit rate", formatPct((metrics.hitRate ?? 0) * 100)],
  ];
  el.metricsGrid.innerHTML = rows.map(([label, value]) => `<div class="metric"><span>${label}</span><strong>${value}</strong></div>`).join("");
}

function renderTable(results) {
  if (!results.length) {
    el.recommendationsBody.innerHTML = `<tr><td colspan="6" class="empty-state">No database rows match this date and group.</td></tr>`;
    return;
  }
  el.recommendationsBody.innerHTML = results.map((item) => {
    const nextClass = item.nextDayReturn > 0 ? "positive" : item.nextDayReturn < 0 ? "negative" : "neutral";
    const nextText = item.nextDayReturn === null || item.nextDayReturn === undefined ? "Pending" : formatPct(item.nextDayReturn);
    return `
      <tr class="${item.symbol === state.selectedSymbol ? "active" : ""}" data-symbol="${item.symbol}">
        <td class="stock-name"><strong>${item.symbol}</strong><span>${item.sector || "Imported"}</span></td>
        <td>${signalPill(item.signal)}</td>
        <td class="score">${item.score > 0 ? "+" : ""}${item.score}</td>
        <td>${item.buyRules}B / ${item.sellRules}S / ${item.holdRules}H</td>
        <td class="${nextClass}">${nextText}</td>
        <td>Rs. ${formatMoney(item.close)}</td>
      </tr>`;
  }).join("");
  el.recommendationsBody.querySelectorAll("tr[data-symbol]").forEach((row) => {
    row.addEventListener("click", () => selectStock(row.dataset.symbol));
  });
}

function renderDetails(item) {
  if (!item) {
    el.selectedStockTitle.textContent = "Stock detail";
    el.selectedSignalPill.innerHTML = "";
    el.stockChart.innerHTML = "";
    el.stockDetails.innerHTML = `<div class="empty-state">No stock selected.</div>`;
    return;
  }
  el.selectedStockTitle.textContent = `${item.symbol} - ${item.name || item.symbol}`;
  el.selectedSignalPill.innerHTML = signalPill(item.signal);
  el.stockChart.innerHTML = lineChart(state.prices);
  const rules = item.ruleResults.map((result) => `<li>${result.rule}: <strong>${result.signal}</strong> (${result.reason})</li>`).join("");
  const nextCloseText = item.nextClose === null || item.nextClose === undefined ? "Pending" : "Rs. " + formatMoney(item.nextClose) + " (" + formatPct(item.nextDayReturn) + ")";
  el.stockDetails.innerHTML = `
    <div class="detail-block">
      <h3>Context</h3>
      <ul>
        <li>Source: ${item.source || "SQLite"}</li>
        <li>Signal close: Rs. ${formatMoney(item.close)}</li>
        <li>20D ADV: ${formatNumber(item.avgVolume20 || 0)}</li>
        <li>Relative volume: ${Number(item.relativeVolume || 0).toFixed(2)}x</li>
        <li>RSI 14: ${Number(item.rsi14 || 0).toFixed(2)}</li>
        <li>EMA9 distance: ${formatPct(item.ema9Distance || 0)}</li>
        <li>From 20D high: ${Number(item.nearHigh20Pct || 0).toFixed(2)}%</li>
        <li>3D ROC: ${formatPct(item.roc3 || 0)}</li>
        <li>Next date: ${formatDate(item.nextDate)}</li>
        <li>Next close: ${nextCloseText}</li>
      </ul>
    </div>
    <div class="detail-block"><h3>Rule explanation</h3><ul>${rules}</ul></div>`;
}

function setLoadingState() {
  el.recommendationsBody.innerHTML = `<tr><td colspan="6" class="empty-state">Loading SQLite recommendations...</td></tr>`;
}

function setupDemoMode() {
  state.mode = "demo";
  state.groups = DEMO_GROUPS;
  state.dates = mockDates.slice(5, -1);
  state.groupId = DEMO_GROUPS[0].id;
  state.date = state.dates[state.dates.length - 1];
  renderSelectors();
  renderDemo();
}

function renderDemo() {
  const symbols = DEMO_GROUPS[0].symbols;
  state.results = symbols.map((symbol) => evaluateDemo(symbol)).filter(Boolean).sort((a, b) => Math.abs(b.score) - Math.abs(a.score));
  state.metrics = {
    totalSignals: state.results.length,
    buyCandidates: state.results.filter((row) => row.score > 0).length,
    sellCandidates: state.results.filter((row) => row.score < 0).length,
    avgNextDayMove: avg(state.results.map((row) => row.nextDayReturn)),
    hitRate: avg(state.results.map((row) => (row.score > 0 && row.nextDayReturn > 0 ? 1 : 0))),
  };
  state.selectedSymbol = state.selectedSymbol || state.results[0]?.symbol;
  state.prices = demoCandles[state.selectedSymbol] || [];
  render();
}

function evaluateDemo(symbol) {
  const series = demoCandles[symbol];
  const index = mockDates.indexOf(state.date);
  if (!series || index < 5 || index >= series.length - 1) return null;
  const close = series[index].close;
  const avg5 = avg(series.slice(index - 5, index).map((row) => row.close));
  const score = close > avg5 ? 5 : -5;
  return {
    symbol,
    name: symbol,
    sector: "Demo",
    source: "Demo fallback",
    close,
    nextClose: series[index + 1].close,
    nextDate: series[index + 1].date,
    nextDayReturn: pct(series[index + 1].close, close),
    score,
    buyRules: score > 0 ? 1 : 0,
    sellRules: score < 0 ? 1 : 0,
    holdRules: 5,
    signal: score > 0 ? "Strong Buy" : "Strong Sell",
    ruleResults: [{ rule: "Demo 5-day trend", signal: score > 0 ? "Buy" : "Sell", reason: `Close vs average ${formatPct(pct(close, avg5))}` }],
  };
}

function lineChart(series) {
  if (!series?.length) return "";
  const width = 640;
  const height = 220;
  const padding = 28;
  const visible = series.slice(-60);
  const values = visible.map((item) => item.close);
  const min = Math.min(...values) * 0.995;
  const max = Math.max(...values) * 1.005;
  const points = visible.map((item, index) => {
    const x = padding + (index / Math.max(1, visible.length - 1)) * (width - padding * 2);
    const y = height - padding - ((item.close - min) / Math.max(1, max - min)) * (height - padding * 2);
    return [x, y];
  });
  const path = points.map(([x, y], index) => `${index === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const last = points[points.length - 1];
  return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Recent closing price chart">
    <line x1="${padding}" x2="${width - padding}" y1="${height - padding}" y2="${height - padding}" stroke="#dbe1d8" />
    <path d="${path}" fill="none" stroke="#255f91" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" />
    <circle cx="${last[0]}" cy="${last[1]}" r="6" fill="#17211b" />
    <text x="${padding}" y="24" fill="#637064" font-size="13">Last ${visible.length} closes from SQLite</text>
    <text x="${width - padding}" y="${height - 8}" fill="#637064" font-size="12" text-anchor="end">${formatDate(visible[visible.length - 1].date)}</text>
  </svg>`;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;" }[char]));
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
async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

function signalPill(signal) {
  const className = signal.includes("Buy") ? "buy" : signal.includes("Sell") ? "sell" : signal === "Watch" ? "watch" : "hold";
  return `<span class="pill ${className}">${signal}</span>`;
}

function pct(value, base) {
  return base ? ((value - base) / base) * 100 : 0;
}

function avg(values) {
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
}

function round(value) {
  return Math.round(value * 100) / 100;
}

function formatPct(value) {
  return `${value > 0 ? "+" : ""}${Number(value).toFixed(2)}%`;
}

function formatMoney(value) {
  return Number(value).toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

function formatNumber(value) {
  return Number(value).toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

function formatDate(value) {
  if (!value) return "-";
  return new Intl.DateTimeFormat("en-IN", { day: "2-digit", month: "short", year: "numeric" }).format(new Date(`${value}T00:00:00+05:30`));
}







