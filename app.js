const STORAGE_KEY = "signaldesk.buyRules.v1";
const RULE_GROUP_STORAGE_KEY = "signaldesk.ruleGroups.v1";

const FILTER_EXPLANATIONS = {
  adv20_min: [
    "20D Average Volume is the average number of shares traded per day over the last 20 trading sessions.",
    "Use it as a liquidity filter so the app avoids stocks where entry and exit may be difficult.",
  ],
  daily_volume_range: [
    "Daily Volume is the actual traded quantity on the selected signal date.",
    "A minimum value removes very inactive stocks. A maximum can avoid unusual one-day spikes if you want cleaner testing.",
  ],
  relative_volume: [
    "This compares today's volume with the stock's own 20-day average volume.",
    "Example: 1.5x means today's volume is 50% higher than normal, often showing fresh participation.",
  ],
  relative_volume_10d: [
    "This compares today's volume with the faster 10-day average volume.",
    "It reacts quicker than the 20D version and can be useful for short swing trades.",
  ],
  delivery_pct_range: [
    "Delivery percentage estimates how much of the day's traded quantity was carried forward instead of squared off intraday.",
    "Higher delivery can suggest positional buying, but very high delivery alone is not a buy signal.",
  ],
  relative_delivery_qty: [
    "This compares today's delivered quantity with the stock's own 20-day average delivered quantity.",
    "It is useful when absolute delivery buying increases even if delivery percentage does not look very high.",
  ],
  price_momentum_3d: [
    "3-Day Price Momentum measures close-to-close price change over the last 3 trading sessions.",
    "For breakout rules, a small or controlled 3D move can mean the stock paused before a fresh move.",
  ],
  price_change_1d: [
    "1-Day Price Change measures today's close versus previous trading day's close.",
    "A positive threshold finds stocks that already showed price action on the signal day.",
  ],
  multi_period_momentum: [
    "Multi-Period Momentum checks returns across selected windows such as 15D, 1M, 3M, 6M, and 1Y.",
    "Turn on only the periods you want. This helps find stocks where short-term strength agrees with the bigger trend.",
  ],
  range_position_52w: [
    "52W Range Position tells where today's close sits between the 52-week low and 52-week high.",
    "A high value means the stock is near its yearly high; useful for strength and breakout-style rules.",
  ],
  close_near_20d_high: [
    "This checks how close the stock is to its highest price of the last 20 trading sessions.",
    "A small value means price is pressing near a recent breakout zone.",
  ],
  close_position_day_range: [
    "This checks where the close landed within today's high-low range.",
    "A high value means the stock closed near the day's high, showing buyers held control into the close.",
  ],
  range_compression_10d: [
    "10D Range Compression measures how narrow the last 10 trading days' high-low range is compared with price.",
    "Low compression can show a quiet pause. Breakouts after compression can be useful for 2-10 day trades.",
  ],
  rupee_liquidity: [
    "Rupee Liquidity estimates average traded value: close price multiplied by 20D average volume, shown in crore.",
    "It is often better than raw volume when comparing high-price and low-price stocks.",
  ],
  ema_trend: [
    "EMA Trend has 3 checks: close above EMA9, close above EMA20, and EMA20 above SMA50.",
    "Min trend checks decides strictness. 3 is strict; 2 is flexible and may catch earlier moves.",
  ],
  rsi14_rising: [
    "RSI 14 Rising checks whether today's RSI is higher than previous trading day's RSI.",
    "It looks for improving momentum, not just a high RSI value.",
  ],
  ema10_above_ema20: [
    "This checks whether the faster EMA10 is above EMA20.",
    "It suggests the short-term trend is stronger than the medium-term trend.",
  ],
  macd_bullish_momentum: [
    "MACD Bullish Momentum checks whether MACD is above its signal line and the histogram is improving.",
    "It is a trend-momentum confirmation filter, usually better combined with price and volume filters.",
  ],
  atr_risk: [
    "ATR Risk measures average daily volatility over 14 sessions as a percentage of close.",
    "Low ATR may be too slow; very high ATR can be risky. For swing trades, a controlled range is usually better.",
  ],
  obv_accumulation_3d: [
    "OBV Accumulation checks whether volume flow improved while price stayed relatively quiet for 3 days.",
    "It tries to detect accumulation before a possible breakout.",
  ],
  rsi14_range: [
    "RSI 14 Range filters stocks by momentum strength.",
    "High RSI shows strength but can also be overheated, so using a range is safer than only demanding very high RSI.",
  ],
  mfi14_range: [
    "Money Flow Index combines price and volume to estimate buying pressure over 14 sessions.",
    "It behaves like a volume-weighted RSI. High values show strong money flow but may become overheated.",
  ],
  cci14_strong_trend: [
    "CCI 14 compares price with its recent average range.",
    "High CCI can identify strong bursts, but it should be tested with risk controls because bursts can reverse quickly.",
  ],
};

const state = {
  groups: [],
  dates: [],
  stats: null,
  filterLibrary: [],
  rules: [],
  ruleGroups: [],
  activeRuleIndex: 0,
  activeRuleGroupIndex: 0,
  mode: "group",
  view: "analyze",
  applyPriceFilter: false,
  minUniversePrice: 100,
  maxUniversePrice: 1000,
  groupId: "all",
  date: null,
  search: "",
  results: [],
  metrics: {},
  prices: [],
  selectedSymbol: null,
  backtest: null,
  defaultBacktest: null,
  strategySaveTimer: null,
  scanSeq: 0,
  isScanning: false,
  scanLabel: "",
};

const el = {
  viewButtons: Array.from(document.querySelectorAll("[data-view-button]")),
  viewSections: Array.from(document.querySelectorAll("[data-view-section]")),
  analysisModeSelect: document.querySelector("#analysisModeSelect"),
  analysisRuleSelect: document.querySelector("#analysisRuleSelect"),
  analysisRuleGroupSelect: document.querySelector("#analysisRuleGroupSelect"),
  analysisRuleLabel: document.querySelector("#analysisRuleLabel"),
  analysisGroupLabel: document.querySelector("#analysisGroupLabel"),
  applyPriceFilterInput: document.querySelector("#applyPriceFilterInput"),
  minUniversePriceInput: document.querySelector("#minUniversePriceInput"),
  maxUniversePriceInput: document.querySelector("#maxUniversePriceInput"),
  combinedGroupNameInput: document.querySelector("#combinedGroupNameInput"),
  stockGroupSources: document.querySelector("#stockGroupSources"),
  createCombinedGroupButton: document.querySelector("#createCombinedGroupButton"),
  stockGroupStatus: document.querySelector("#stockGroupStatus"),
  ruleSelect: document.querySelector("#ruleSelect"),
  ruleNameInput: document.querySelector("#ruleNameInput"),
  saveRuleButton: document.querySelector("#saveRuleButton"),
  newRuleButton: document.querySelector("#newRuleButton"),
  ruleGroupSelect: document.querySelector("#ruleGroupSelect"),
  ruleGroupNameInput: document.querySelector("#ruleGroupNameInput"),
  minRuleMatchesInput: document.querySelector("#minRuleMatchesInput"),
  ruleGroupMembers: document.querySelector("#ruleGroupMembers"),
  saveRuleGroupButton: document.querySelector("#saveRuleGroupButton"),
  newRuleGroupButton: document.querySelector("#newRuleGroupButton"),
  groupSelect: document.querySelector("#groupSelect"),
  dateSelect: document.querySelector("#dateSelect"),
  searchInput: document.querySelector("#searchInput"),
  filterLibrary: document.querySelector("#filterLibrary"),
  selectedFilters: document.querySelector("#selectedFilters"),
  fromDateInput: document.querySelector("#fromDateInput"),
  toDateInput: document.querySelector("#toDateInput"),
  topNInput: document.querySelector("#topNInput"),
  capitalInput: document.querySelector("#capitalInput"),
  targetInput: document.querySelector("#targetInput"),
  stopInput: document.querySelector("#stopInput"),
  maxHoldInput: document.querySelector("#maxHoldInput"),
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
  state.defaultBacktest = bootstrap.defaultBacktest || {};
  state.rules = loadSavedRules(bootstrap.defaultRule, bootstrap.strategy?.rules);
  state.ruleGroups = loadSavedRuleGroups(bootstrap.strategy?.ruleGroups);
  applyStrategySettings(bootstrap.strategy?.settings);
  state.groupId = state.groups.find((group) => group.id === state.groupId)?.id || state.groups[0]?.id || "all";
  state.date = state.dates[state.dates.length - 1];
  saveStrategySoon();
  renderAll();
  await runScan();
}

function bindShell() {
  el.viewButtons.forEach((button) => {
    button.addEventListener("click", () => {
      state.view = button.dataset.viewButton;
      renderView();
    });
  });
  el.analysisModeSelect.addEventListener("change", () => {
    state.mode = el.analysisModeSelect.value;
    state.backtest = null;
    saveStrategySoon();
    renderAll();
    runScan();
  });
  el.analysisRuleSelect.addEventListener("change", () => {
    state.activeRuleIndex = Number(el.analysisRuleSelect.value);
    state.mode = "rule";
    state.backtest = null;
    saveStrategySoon();
    renderAll();
    runScan();
  });
  el.analysisRuleGroupSelect.addEventListener("change", () => {
    state.activeRuleGroupIndex = Number(el.analysisRuleGroupSelect.value);
    state.mode = "group";
    state.backtest = null;
    saveStrategySoon();
    renderAll();
    runScan();
  });
  el.applyPriceFilterInput.addEventListener("change", () => {
    state.applyPriceFilter = el.applyPriceFilterInput.checked;
    state.backtest = null;
    saveStrategySoon();
    renderAll();
    runScan();
  });
  [el.minUniversePriceInput, el.maxUniversePriceInput].forEach((input) => {
    input.addEventListener("input", debounce(() => {
      state.minUniversePrice = Number(el.minUniversePriceInput.value) || 0;
      state.maxUniversePrice = Number(el.maxUniversePriceInput.value) || 0;
      if (state.maxUniversePrice && state.maxUniversePrice < state.minUniversePrice) {
        state.maxUniversePrice = state.minUniversePrice;
        el.maxUniversePriceInput.value = state.maxUniversePrice;
      }
      saveStrategySoon();
      state.backtest = null;
      runScan();
      renderRuleMeaning();
    }, 300));
  });
  el.groupSelect.addEventListener("change", () => {
    state.groupId = el.groupSelect.value;
    state.backtest = null;
    saveStrategySoon();
    renderAll();
    runScan();
  });
  el.createCombinedGroupButton.addEventListener("click", createCombinedStockGroup);
  el.ruleSelect.addEventListener("change", () => {
    state.activeRuleIndex = Number(el.ruleSelect.value);
    state.mode = "rule";
    state.view = "rules";
    state.backtest = null;
    saveStrategySoon();
    renderAll();
    runScan();
  });
  el.saveRuleButton.addEventListener("click", () => {
    currentRule().name = el.ruleNameInput.value.trim() || "Untitled Rule";
    saveRules();
    syncRuleGroupsWithRules();
    renderAll();
  });
  el.newRuleButton.addEventListener("click", () => {
    state.rules.push({ id: createId("rule"), name: "New Buy Rule", filters: [] });
    state.activeRuleIndex = state.rules.length - 1;
    state.mode = "rule";
    state.view = "rules";
    state.backtest = null;
    saveRules();
    syncRuleGroupsWithRules();
    renderAll();
    runScan();
  });
  el.ruleGroupSelect.addEventListener("change", () => {
    state.activeRuleGroupIndex = Number(el.ruleGroupSelect.value);
    state.mode = "group";
    state.view = "groups";
    state.backtest = null;
    saveStrategySoon();
    renderAll();
    runScan();
  });
  el.saveRuleGroupButton.addEventListener("click", () => {
    saveCurrentRuleGroupFromUi();
    state.mode = "group";
    state.view = "groups";
    saveRuleGroups();
    renderAll();
    runScan();
  });
  el.newRuleGroupButton.addEventListener("click", () => {
    const rule = currentRule();
    state.ruleGroups.push({
      id: createId("group"),
      name: "New Rule Group",
      minMatches: 1,
      ruleIds: rule ? [rule.id] : [],
    });
    state.activeRuleGroupIndex = state.ruleGroups.length - 1;
    state.mode = "group";
    state.view = "groups";
    state.backtest = null;
    saveRuleGroups();
    renderAll();
    runScan();
  });
  el.dateSelect.addEventListener("change", () => {
    state.date = el.dateSelect.value;
    state.selectedSymbol = null;
    runScan();
  });
  el.searchInput.addEventListener("input", debounce(() => {
    state.search = el.searchInput.value.trim();
    state.selectedSymbol = null;
    runScan();
  }, 250));
  el.backtestButton.addEventListener("click", runBacktest);
}

function renderAll() {
  renderView();
  renderAnalysisSelectors();
  renderStockGroupBuilder();
  renderRuleSelect();
  renderRuleGroupSelect();
  renderRuleGroupMembers();
  renderSelectors();
  renderFilterLibrary();
  renderSelectedFilters();
  renderRuleMeaning();
  renderStatus();
  renderBacktestControls();
  renderMetrics();
  renderTable();
  renderDetails();
  renderBacktest();
}

function renderView() {
  el.viewButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.viewButton === state.view);
  });
  el.viewSections.forEach((section) => {
    section.hidden = section.dataset.viewSection !== state.view;
  });
}

function renderAnalysisSelectors() {
  el.analysisModeSelect.value = state.mode;
  el.analysisRuleSelect.innerHTML = state.rules.map((rule, index) => `<option value="${index}">${escapeHtml(rule.name)}</option>`).join("");
  el.analysisRuleSelect.value = state.activeRuleIndex;
  el.analysisRuleGroupSelect.innerHTML = state.ruleGroups.map((group, index) => `<option value="${index}">${escapeHtml(group.name)}</option>`).join("");
  el.analysisRuleGroupSelect.value = state.activeRuleGroupIndex;
  const usingRule = state.mode === "rule";
  el.analysisRuleLabel.hidden = !usingRule;
  el.analysisRuleSelect.hidden = !usingRule;
  el.analysisGroupLabel.hidden = usingRule;
  el.analysisRuleGroupSelect.hidden = usingRule;
  el.applyPriceFilterInput.checked = state.applyPriceFilter;
  el.minUniversePriceInput.value = state.minUniversePrice;
  el.maxUniversePriceInput.value = state.maxUniversePrice;
}

function renderStockGroupBuilder() {
  el.stockGroupSources.innerHTML = state.groups.map((group) => `
    <label class="check-item">
      <input type="checkbox" data-stock-group-source="${escapeHtml(group.id)}" />
      <span>
        <strong>${escapeHtml(group.name)}</strong>
        <small>${escapeHtml(group.description || "Stock group")}</small>
      </span>
    </label>
  `).join("");
}

function renderRuleSelect() {
  el.ruleSelect.innerHTML = state.rules.map((rule, index) => `<option value="${index}">${escapeHtml(rule.name)}</option>`).join("");
  el.ruleSelect.value = state.activeRuleIndex;
  el.ruleNameInput.value = currentRule().name;
  el.pageTitle.textContent = state.mode === "group" ? currentRuleGroup().name : currentRule().name;
}

function renderRuleGroupSelect() {
  el.ruleGroupSelect.innerHTML = state.ruleGroups.map((group, index) => `<option value="${index}">${escapeHtml(group.name)}</option>`).join("");
  el.ruleGroupSelect.value = state.activeRuleGroupIndex;
  const group = currentRuleGroup();
  el.ruleGroupNameInput.value = group.name;
  el.minRuleMatchesInput.max = Math.max(1, group.ruleIds.length);
  el.minRuleMatchesInput.value = group.minMatches || Math.max(1, group.ruleIds.length);
}

function renderRuleGroupMembers() {
  const group = currentRuleGroup();
  el.ruleGroupMembers.innerHTML = state.rules.map((rule) => `
    <label class="check-item">
      <input type="checkbox" data-rule-group-member="${escapeHtml(rule.id)}" ${group.ruleIds.includes(rule.id) ? "checked" : ""} />
      <span>
        <strong>${escapeHtml(rule.name)}</strong>
        <small>${formatNumber(rule.filters.length)} filters</small>
      </span>
    </label>
  `).join("");
  el.ruleGroupMembers.querySelectorAll("input[data-rule-group-member]").forEach((input) => {
    input.addEventListener("change", () => {
      saveCurrentRuleGroupFromUi();
      saveRuleGroups();
      renderRuleGroupSelect();
      state.mode = "group";
      state.backtest = null;
      runScan();
    });
  });
}

function renderSelectors() {
  el.groupSelect.innerHTML = state.groups.map((group) => `<option value="${escapeHtml(group.id)}">${escapeHtml(group.name)}</option>`).join("");
  el.groupSelect.value = state.groupId;
  el.dateSelect.innerHTML = state.dates.map((date) => `<option value="${date}">${formatDate(date)}</option>`).join("");
  el.dateSelect.value = state.date;
}

function renderFilterLibrary() {
  el.filterLibrary.innerHTML = state.filterLibrary.filter((filter) => filter.id !== "price_range").map((filter) => `
    <div class="rule-item">
      <strong>${escapeHtml(filter.name)}</strong>
      <span>${escapeHtml(filter.category)}: ${escapeHtml(filter.meaning)}</span>
      ${filterHelpMarkup(filter.id)}
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
    const fields = (definition?.fields || []).map((field) => {
      if (field.type === "checkbox") {
        return `
          <label class="inline-toggle filter-toggle">
            <input type="checkbox" ${selected.values[field.key] ? "checked" : ""} data-filter-index="${index}" data-field-key="${escapeHtml(field.key)}" data-field-type="checkbox" />
            <span>${escapeHtml(field.label)}</span>
          </label>
        `;
      }
      return `
        <label>${escapeHtml(field.label)}
          <input type="number" step="${field.step}" value="${selected.values[field.key]}" data-filter-index="${index}" data-field-key="${escapeHtml(field.key)}" data-field-type="number" />
        </label>
      `;
    }).join("");
    return `
      <div class="rule-item selected-rule">
        <strong>${escapeHtml(definition?.name || selected.id)}</strong>
        <span>${escapeHtml(definition?.meaning || "")}</span>
        ${filterHelpMarkup(selected.id)}
        <div class="input-grid two-col">${fields}</div>
        <button type="button" data-remove-filter="${index}">Remove</button>
      </div>
    `;
  }).join("");
  el.selectedFilters.querySelectorAll("input[data-filter-index]").forEach((input) => {
    const eventName = input.dataset.fieldType === "checkbox" ? "change" : "input";
    input.addEventListener(eventName, debounce(() => {
      const filter = currentRule().filters[Number(input.dataset.filterIndex)];
      filter.values[input.dataset.fieldKey] = input.dataset.fieldType === "checkbox" ? input.checked : Number(input.value) || 0;
      saveRules();
      runScan();
      renderRuleMeaning();
    }, 300));
  });
  el.selectedFilters.querySelectorAll("button[data-remove-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      currentRule().filters.splice(Number(button.dataset.removeFilter), 1);
      state.backtest = null;
      saveRules();
      renderAll();
      runScan();
    });
  });
}

function renderRuleMeaning() {
  const rule = currentRule();
  const group = currentRuleGroup();
  if (state.mode === "group") {
    const selectedRules = rulesForCurrentGroup();
    el.ruleMeaning.innerHTML = `
      <div class="detail-block">
        <h3>Recommendation Group</h3>
        <p>A stock appears when at least ${group.minMatches || 1} selected rules pass. More matching rules means stronger agreement.</p>
        ${universeFilterSummary()}
        <ul>
          ${selectedRules.map((item) => `<li><strong>${escapeHtml(item.name)}:</strong> ${formatNumber(signalFilters(item).length)} signal filters</li>`).join("")}
        </ul>
      </div>
    `;
    return;
  }
  if (!rule.filters.length) {
    el.ruleMeaning.innerHTML = `<div class="empty-state">This rule has no filters yet.</div>`;
    return;
  }
  el.ruleMeaning.innerHTML = `
    <div class="detail-block">
      <h3>Rule Logic</h3>
      <p>A stock passes only when all selected filters pass.</p>
      ${universeFilterSummary()}
      <ul>
        ${signalFilters(rule).map((selected) => {
          const definition = filterDefinition(selected.id);
          return `<li><strong>${escapeHtml(definition?.name || selected.id)}:</strong> ${escapeHtml(humanValues(selected))}</li>`;
        }).join("")}
      </ul>
    </div>
  `;
}

function renderStatus() {
  const baseStatus = state.stats
    ? `SQLite connected: ${formatNumber(state.stats.stock_count)} NSE stocks, ${formatNumber(state.stats.price_count)} EOD rows, ${formatNumber(state.stats.delivery_count || 0)} delivery rows.`
    : "SQLite connected.";
  el.statusText.textContent = state.isScanning ? `${baseStatus} Latest scan running: ${state.scanLabel}.` : baseStatus;
}

function renderBacktestControls() {
  if (!el.fromDateInput.value) el.fromDateInput.value = state.defaultBacktest.fromDate || state.dates[0] || "";
  if (!el.toDateInput.value) el.toDateInput.value = state.defaultBacktest.toDate || state.dates[state.dates.length - 1] || "";
  if (!el.topNInput.value) el.topNInput.value = state.defaultBacktest.topN || 10;
  if (!el.capitalInput.value) el.capitalInput.value = state.defaultBacktest.capitalPerStock || 10000;
  if (!el.targetInput.value) el.targetInput.value = state.defaultBacktest.targetPct || 5;
  if (!el.stopInput.value) el.stopInput.value = state.defaultBacktest.stopPct || 5;
  if (!el.maxHoldInput.value) el.maxHoldInput.value = state.defaultBacktest.maxHoldDays || 5;
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
    el.resultsBody.innerHTML = `<tr><td colspan="20" class="empty-state">No stocks passed this ${state.mode === "group" ? "rule group" : "rule"}.</td></tr>`;
    return;
  }
  el.resultsBody.innerHTML = state.results.map((item) => `
    <tr class="${item.symbol === state.selectedSymbol ? "active" : ""}" data-symbol="${escapeHtml(item.symbol)}">
      <td class="stock-name"><strong>${escapeHtml(item.symbol)}</strong><span>${escapeHtml(item.name)}</span></td>
      <td>${item.totalRules ? `${item.matchCount}/${item.totalRules}` : "-"}</td>
      <td>Rs. ${formatMoney(item.close)}</td>
      <td>${formatNumber(item.volume)}</td>
      <td>${Number(item.relativeVolume || 0).toFixed(2)}x</td>
      <td>${item.deliveryPct == null ? "N/A" : formatPlainPct(item.deliveryPct)}</td>
      <td>${Number(item.relativeDelivery || 0).toFixed(2)}x</td>
      <td class="${item.momentum3D > 0 ? "positive" : item.momentum3D < 0 ? "negative" : "neutral"}">${formatPct(item.momentum3D || 0)}</td>
      <td class="${item.momentum15D > 0 ? "positive" : item.momentum15D < 0 ? "negative" : "neutral"}">${formatPct(item.momentum15D || 0)}</td>
      <td>${formatPlainPct(item.closePositionDay || 0)}</td>
      <td>${formatPlainPct(item.compression10D || 0)}</td>
      <td>${formatPct(item.distanceFrom20DHigh || 0)}</td>
      <td>${formatPlainPct(item.rangePosition52W || 0)}</td>
      <td>${Number(item.obv3D || 0).toFixed(2)}x</td>
      <td>${formatNumber(item.adv20)}</td>
      <td>Rs. ${formatMoney(item.rupeeLiquidityCr || 0)} cr</td>
      <td class="${item.momentum1Y > 0 ? "positive" : item.momentum1Y < 0 ? "negative" : "neutral"}">${formatPct(item.momentum1Y || 0)}</td>
      <td>${Number(item.rsi14).toFixed(2)}</td>
      <td>${formatPlainPct(item.atrPct || 0)}</td>
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
    ${item.totalRules ? `
      <div class="detail-block">
        <h3>Rule Group Match</h3>
        <p>${item.matchCount} of ${item.totalRules} rules passed. Minimum required: ${item.minMatches}.</p>
        <ul>${(item.matchedRules || []).map((rule) => `<li>${escapeHtml(rule.name)}</li>`).join("")}</ul>
      </div>
    ` : ""}
    <div class="detail-block">
      <h3>Delivery</h3>
      <p>Delivery ${item.deliveryPct == null ? "N/A" : formatPlainPct(item.deliveryPct)}${item.deliverableQty == null ? "" : `, delivered quantity ${formatNumber(item.deliverableQty)}`}.</p>
      <p>Delivered quantity is ${Number(item.relativeDelivery || 0).toFixed(2)}x of its 20-day average${item.avgDelivery20 ? ` (${formatNumber(item.avgDelivery20)})` : ""}.</p>
      <p>Volume is ${Number(item.relativeVolume10D || 0).toFixed(2)}x of its 10-day average and ${Number(item.relativeVolume || 0).toFixed(2)}x of its 20-day average.</p>
      <p>20-day rupee liquidity is Rs. ${formatMoney(item.rupeeLiquidityCr || 0)} cr.</p>
      <p>1-day price change is ${formatPct(item.priceChange1D || 0)} versus the previous close.</p>
      <p>3-day price change is ${formatPct(item.momentum3D || 0)}.</p>
      <p>Multi-period momentum: 1W ${formatPct(item.momentum1W || 0)}, 15D ${formatPct(item.momentum15D || 0)}, 1M ${formatPct(item.momentum1M || 0)}, 3M ${formatPct(item.momentum3M || 0)}, 6M ${formatPct(item.momentum6M || 0)}, 1Y ${formatPct(item.momentum1Y || 0)}, 6M-12M ${formatPct(item.momentum6MTo12M || 0)}.</p>
      <p>Close position in today's range is ${formatPlainPct(item.closePositionDay || 0)}.</p>
      <p>10-day range compression is ${formatPlainPct(item.compression10D || 0)}. Lower values mean the stock has been moving in a tighter range.</p>
      <p>Close is ${formatPct(item.distanceFrom20DHigh || 0)} from 20D high Rs. ${formatMoney(item.high20D || 0)}.</p>
      <p>52W position is ${formatPlainPct(item.rangePosition52W || 0)} between low Rs. ${formatMoney(item.low52W || 0)} and high Rs. ${formatMoney(item.high52W || 0)}.</p>
      <p>EMA trend: close Rs. ${formatMoney(item.close)}, EMA9 Rs. ${formatMoney(item.ema9 || 0)}, EMA10 Rs. ${formatMoney(item.ema10 || 0)}, EMA20 Rs. ${formatMoney(item.ema20 || 0)}, SMA50 Rs. ${formatMoney(item.sma50 || 0)}.</p>
      <p>MACD: line ${formatSignedNumber(item.macdLine || 0)}, signal ${formatSignedNumber(item.macdSignal || 0)}, histogram ${formatSignedNumber(item.macdHistogram || 0)}, change ${formatSignedNumber(item.macdHistogramChange || 0)}.</p>
      <p>ATR risk is ${formatPlainPct(item.atrPct || 0)} with ATR14 Rs. ${formatMoney(item.atr14 || 0)}.</p>
      <p>3-day OBV change is ${Number(item.obv3D || 0).toFixed(2)}x of 20-day average volume.</p>
      <p>RSI 14 is ${Number(item.rsi14 || 0).toFixed(2)}, previous RSI was ${Number(item.previousRsi14 || 0).toFixed(2)}, MFI 14 is ${Number(item.mfi14 || 0).toFixed(2)}, and CCI 14 is ${formatSignedNumber(item.cci14 || 0)}.</p>
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

async function runScan() {
  const seq = ++state.scanSeq;
  state.isScanning = true;
  state.scanLabel = scanLabel();
  renderStatus();
  try {
    if (state.mode === "group") {
      await runRuleGroupScan(seq);
    } else {
      await runRuleScan(seq);
    }
  } catch (error) {
    if (seq === state.scanSeq) {
      el.resultsBody.innerHTML = `<tr><td colspan="20" class="empty-state">Scan failed: ${escapeHtml(error.message)}</td></tr>`;
    }
  } finally {
    if (seq === state.scanSeq) {
      state.isScanning = false;
      renderStatus();
    }
  }
}

async function runRuleScan(seq) {
  const payload = {
    rule: ruleForRun(currentRule()),
    universeFilters: universeFiltersForRun(),
    group: state.groupId,
    date: state.date,
    search: state.search,
    limit: 200,
  };
  el.resultsBody.innerHTML = `<tr><td colspan="20" class="empty-state">Running rule...</td></tr>`;
  const result = await postJson("/api/rule/results", payload);
  if (seq !== state.scanSeq) return;
  state.results = result.results || [];
  state.metrics = result.metrics || {};
  state.selectedSymbol = state.results.find((row) => row.symbol === state.selectedSymbol)?.symbol || state.results[0]?.symbol || null;
  if (state.selectedSymbol) {
    const prices = await fetchJson(`/api/prices?symbol=${encodeURIComponent(state.selectedSymbol)}&date=${encodeURIComponent(state.date)}`);
    if (seq !== state.scanSeq) return;
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
    const isGroupMode = state.mode === "group";
    const payload = {
      group: state.groupId,
      fromDate: el.fromDateInput.value || state.defaultBacktest.fromDate,
      toDate: el.toDateInput.value || state.defaultBacktest.toDate,
      topN: Number(el.topNInput.value) || 10,
      capitalPerStock: Number(el.capitalInput.value) || 10000,
      targetPct: Number(el.targetInput.value) || 5,
      stopPct: Number(el.stopInput.value) || 5,
      maxHoldDays: Number(el.maxHoldInput.value) || 5,
      universeFilters: universeFiltersForRun(),
    };
    if (isGroupMode) {
      payload.rules = rulesForCurrentGroup().map(ruleForRun);
      payload.minMatches = currentRuleGroup().minMatches || 1;
      state.backtest = await postJson("/api/rule-group/backtest", payload);
    } else {
      payload.rule = ruleForRun(currentRule());
      state.backtest = await postJson("/api/rule/backtest", payload);
    }
    renderBacktest();
  } catch (error) {
    el.backtestSummary.innerHTML = `<div class="detail-block error"><h3>Backtest Error</h3><p>${escapeHtml(error.message)}</p></div>`;
  } finally {
    el.backtestButton.disabled = false;
    el.backtestButton.textContent = "Backtest selection";
  }
}

async function createCombinedStockGroup() {
  const sourceGroupIds = Array.from(el.stockGroupSources.querySelectorAll("input[data-stock-group-source]:checked")).map((input) => input.dataset.stockGroupSource);
  const name = el.combinedGroupNameInput.value.trim();
  el.createCombinedGroupButton.disabled = true;
  el.stockGroupStatus.textContent = "Creating combined group...";
  try {
    const result = await postJson("/api/groups/combine", { name, sourceGroupIds });
    if (result.error) throw new Error(result.error);
    const bootstrap = await fetchJson("/api/bootstrap");
    state.groups = bootstrap.groups || [];
    state.stats = bootstrap.stats;
    state.groupId = result.id;
    el.combinedGroupNameInput.value = "";
    el.stockGroupStatus.textContent = `${result.name} created with ${formatNumber(result.count)} unique stocks.`;
    state.view = "analyze";
    renderAll();
    runScan();
  } catch (error) {
    el.stockGroupStatus.textContent = error.message;
  } finally {
    el.createCombinedGroupButton.disabled = false;
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
  const values = defaultValuesForFilter(definition);
  currentRule().filters.push({ id: filterId, values });
  state.backtest = null;
  saveRules();
  renderAll();
  runScan();
}

function currentRule() {
  return state.rules[state.activeRuleIndex] || state.rules[0];
}

function currentRuleGroup() {
  return state.ruleGroups[state.activeRuleGroupIndex] || state.ruleGroups[0] || { id: "default", name: "Universal Rule Group", minMatches: 1, ruleIds: [] };
}

function rulesForCurrentGroup() {
  const group = currentRuleGroup();
  return group.ruleIds.map((id) => state.rules.find((rule) => rule.id === id)).filter((rule) => rule && signalFilters(rule).length);
}

async function runRuleGroupScan(seq) {
  const selectedRules = rulesForCurrentGroup();
  if (!selectedRules.length) {
    state.results = [];
    state.metrics = {};
    state.selectedSymbol = null;
    state.prices = [];
    renderAll();
    return;
  }
  const payload = {
    rules: selectedRules.map(ruleForRun),
    minMatches: currentRuleGroup().minMatches || selectedRules.length,
    universeFilters: universeFiltersForRun(),
    group: state.groupId,
    date: state.date,
    search: state.search,
    limit: 200,
  };
  el.resultsBody.innerHTML = `<tr><td colspan="20" class="empty-state">Running rule group...</td></tr>`;
  const result = await postJson("/api/rule-group/results", payload);
  if (seq !== state.scanSeq) return;
  state.results = result.results || [];
  state.metrics = result.metrics || {};
  state.selectedSymbol = state.results.find((row) => row.symbol === state.selectedSymbol)?.symbol || state.results[0]?.symbol || null;
  if (state.selectedSymbol) {
    const prices = await fetchJson(`/api/prices?symbol=${encodeURIComponent(state.selectedSymbol)}&date=${encodeURIComponent(state.date)}`);
    if (seq !== state.scanSeq) return;
    state.prices = prices.prices || [];
  } else {
    state.prices = [];
  }
  renderAll();
}

function scanLabel() {
  const stockGroup = state.groups.find((group) => group.id === state.groupId)?.name || state.groupId;
  const strategy = state.mode === "group" ? currentRuleGroup().name : currentRule().name;
  return `${stockGroup} / ${strategy} / ${formatDate(state.date)}`;
}

function filterDefinition(filterId) {
  return state.filterLibrary.find((filter) => filter.id === filterId);
}

function filterHelpMarkup(filterId) {
  const explanation = FILTER_EXPLANATIONS[filterId];
  if (!explanation?.length) return "";
  return `
    <details class="filter-help">
      <summary>What this means</summary>
      ${explanation.map((line) => `<p>${escapeHtml(line)}</p>`).join("")}
    </details>
  `;
}

function ruleForRun(rule) {
  return {
    ...rule,
    filters: signalFilters(rule),
  };
}

function signalFilters(rule) {
  return (rule?.filters || []).filter((filter) => filter.id !== "price_range");
}

function universeFiltersForRun() {
  if (!state.applyPriceFilter) return [];
  return [{
    id: "price_range",
    values: {
      minPrice: state.minUniversePrice,
      maxPrice: state.maxUniversePrice || 999999,
    },
  }];
}

function universeFilterSummary() {
  if (!state.applyPriceFilter) return "<p>Universe filter: selected stock group only. Price filter is off.</p>";
  return `<p>Universe filter: selected stock group, then close between Rs. ${state.minUniversePrice} and Rs. ${state.maxUniversePrice || 999999}.</p>`;
}

function saveCurrentRuleGroupFromUi() {
  const group = currentRuleGroup();
  group.name = el.ruleGroupNameInput.value.trim() || "Untitled Rule Group";
  group.ruleIds = Array.from(el.ruleGroupMembers.querySelectorAll("input[data-rule-group-member]:checked")).map((input) => input.dataset.ruleGroupMember);
  const requestedMatches = Number(el.minRuleMatchesInput.value) || group.ruleIds.length || 1;
  group.minMatches = Math.max(1, Math.min(requestedMatches, group.ruleIds.length || 1));
  state.backtest = null;
}

function syncRuleGroupsWithRules() {
  const knownRuleIds = new Set(state.rules.map((rule) => rule.id));
  state.ruleGroups.forEach((group) => {
    group.ruleIds = group.ruleIds.filter((id) => knownRuleIds.has(id));
  });
  if (!state.ruleGroups.length) state.ruleGroups = defaultRuleGroups();
  saveRuleGroups();
}

function humanValues(selected) {
  const values = selected.values || {};
  if (selected.id === "price_range") return `Close between Rs. ${values.minPrice} and Rs. ${values.maxPrice}`;
  if (selected.id === "adv20_min") return `20D average volume at least ${formatNumber(values.minAdv20)}`;
  if (selected.id === "daily_volume_range") return `Daily traded volume between ${formatNumber(values.minDailyVolume)} and ${formatNumber(values.maxDailyVolume)} shares`;
  if (selected.id === "relative_volume") return `Today volume between ${values.minRelativeVolume}x and ${values.maxRelativeVolume}x of 20D average volume`;
  if (selected.id === "relative_volume_10d") return `Today volume between ${values.minRelativeVolume10D}x and ${values.maxRelativeVolume10D}x of faster 10D average volume`;
  if (selected.id === "delivery_pct_range") return `Delivery percentage between ${values.minDeliveryPct}% and ${values.maxDeliveryPct}%`;
  if (selected.id === "relative_delivery_qty") return `Today delivered quantity between ${values.minRelativeDelivery}x and ${values.maxRelativeDelivery}x of 20D average delivered quantity`;
  if (selected.id === "price_momentum_3d") return `3-day price change between ${values.minMomentum3D}% and ${values.maxMomentum3D}%`;
  if (selected.id === "price_change_1d") return `Today's close changed between ${values.minPriceChange1D}% and ${values.maxPriceChange1D}% versus previous close`;
  if (selected.id === "multi_period_momentum") {
    const periods = [
      values.useMomentum1W ? `1W ${values.minMomentum1W}% to ${values.maxMomentum1W}%` : null,
      values.useMomentum15D ? `15D ${values.minMomentum15D}% to ${values.maxMomentum15D}%` : null,
      values.useMomentum1M ? `1M ${values.minMomentum1M}% to ${values.maxMomentum1M}%` : null,
      values.useMomentum3M ? `3M ${values.minMomentum3M}% to ${values.maxMomentum3M}%` : null,
      values.useMomentum6M ? `6M ${values.minMomentum6M}% to ${values.maxMomentum6M}%` : null,
      values.useMomentum1Y ? `1Y ${values.minMomentum1Y}% to ${values.maxMomentum1Y}%` : null,
      values.useMomentum6MTo12M ? `6M-12M ${values.minMomentum6MTo12M}% to ${values.maxMomentum6MTo12M}%` : null,
    ].filter(Boolean);
    return periods.length ? periods.join(", ") : "No momentum period selected";
  }
  if (selected.id === "range_position_52w") return `Close position between ${values.minRangePosition52W}% and ${values.maxRangePosition52W}% of 52-week range`;
  if (selected.id === "close_near_20d_high") return `Close within ${values.maxDistanceFrom20DHigh}% below the 20-day high`;
  if (selected.id === "close_position_day_range") return `Close position between ${values.minClosePositionDay}% and ${values.maxClosePositionDay}% of today's high-low range`;
  if (selected.id === "range_compression_10d") return `10-day high-low range between ${values.minCompression10D}% and ${values.maxCompression10D}% of close`;
  if (selected.id === "rupee_liquidity") return `20D average traded value between Rs. ${values.minRupeeLiquidityCr} cr and Rs. ${values.maxRupeeLiquidityCr} cr`;
  if (selected.id === "ema_trend") return `At least ${values.minEmaTrendChecks} of 3 trend checks pass: close above EMA9, close above EMA20, EMA20 above SMA50`;
  if (selected.id === "rsi14_rising") return `RSI 14 must rise by more than ${values.minRsiRise} points versus previous trading day`;
  if (selected.id === "ema10_above_ema20") return `EMA10 must be above EMA20 by at least ${values.minEmaGapPct}%`;
  if (selected.id === "macd_bullish_momentum") return `MACD above signal, MACD line at least ${values.minMacdLine}, histogram at least ${values.minMacdHistogram}, histogram change at least ${values.minMacdHistogramChange}`;
  if (selected.id === "atr_risk") return `ATR 14 between ${values.minAtrPct}% and ${values.maxAtrPct}% of close`;
  if (selected.id === "obv_accumulation_3d") return `3-day OBV change at least ${values.minObv3D}x of 20D average volume while 3-day price move stays within +/-${values.maxAbsMomentum3D}%`;
  if (selected.id === "rsi14_range") return `RSI 14 between ${values.rsiMin} and ${values.rsiMax}`;
  if (selected.id === "mfi14_range") return `Money Flow Index 14 between ${values.mfiMin} and ${values.mfiMax}; higher values show stronger price-volume buying pressure`;
  if (selected.id === "cci14_strong_trend") return `CCI 14 between ${values.minCci14} and ${values.maxCci14}; higher values show stronger price action versus recent range`;
  return JSON.stringify(values);
}

function loadSavedRules(defaultRule, serverRules) {
  const starters = starterRules(defaultRule);
  const localRules = readLocalArray(STORAGE_KEY);
  if (Array.isArray(serverRules) && serverRules.length) {
    const savedRules = withRuleIds(serverRules);
    const ids = new Set(savedRules.map((rule) => rule.id));
    const names = new Set(savedRules.map((rule) => rule.name));
    const localMerged = withRuleIds(localRules).filter((rule) => !ids.has(rule.id) && !names.has(rule.name));
    localMerged.forEach((rule) => {
      ids.add(rule.id);
      names.add(rule.name);
    });
    return [...savedRules, ...localMerged, ...starters.filter((rule) => !ids.has(rule.id) && !names.has(rule.name))];
  }
  try {
    const saved = localRules;
    if (Array.isArray(saved) && saved.length) {
      const savedRules = withRuleIds(saved);
      const names = new Set(savedRules.map((rule) => rule.name));
      const ids = new Set(savedRules.map((rule) => rule.id));
      const merged = [...savedRules, ...starters.filter((rule) => !ids.has(rule.id) && !names.has(rule.name))];
      localStorage.setItem(STORAGE_KEY, JSON.stringify(merged));
      return merged;
    }
  } catch (error) {
    console.warn("Could not load saved rules", error);
  }
  const rules = withRuleIds(starters);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(rules));
  return rules;
}

function saveRules() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state.rules));
  saveStrategySoon();
}

function loadSavedRuleGroups(serverGroups) {
  const templates = starterRuleGroups();
  const localGroups = readLocalArray(RULE_GROUP_STORAGE_KEY);
  if (Array.isArray(serverGroups) && serverGroups.length) {
    const knownRuleIds = new Set(state.rules.map((rule) => rule.id));
    const cleaned = serverGroups.map((group) => ({
      id: group.id || createId("group"),
      name: group.name || "Untitled Rule Group",
      minMatches: Number(group.minMatches) || 1,
      ruleIds: (group.ruleIds || []).filter((id) => knownRuleIds.has(id)),
    })).filter((group) => group.ruleIds.length);
    if (cleaned.length) {
      const ids = new Set(cleaned.map((group) => group.id));
      const names = new Set(cleaned.map((group) => group.name));
      const localMerged = cleanRuleGroups(localGroups, knownRuleIds).filter((group) => !ids.has(group.id) && !names.has(group.name));
      localMerged.forEach((group) => {
        ids.add(group.id);
        names.add(group.name);
      });
      return [...cleaned, ...localMerged, ...templates.filter((group) => !ids.has(group.id) && !names.has(group.name) && group.ruleIds.length)];
    }
  }
  try {
    const saved = localGroups;
    if (Array.isArray(saved) && saved.length) {
      const knownRuleIds = new Set(state.rules.map((rule) => rule.id));
      const cleaned = cleanRuleGroups(saved, knownRuleIds);
      if (cleaned.length) {
        const ids = new Set(cleaned.map((group) => group.id));
        const names = new Set(cleaned.map((group) => group.name));
        const merged = [...cleaned, ...templates.filter((group) => !ids.has(group.id) && !names.has(group.name) && group.ruleIds.length)];
        localStorage.setItem(RULE_GROUP_STORAGE_KEY, JSON.stringify(merged));
        return merged;
      }
    }
  } catch (error) {
    console.warn("Could not load saved rule groups", error);
  }
  const groups = templates;
  localStorage.setItem(RULE_GROUP_STORAGE_KEY, JSON.stringify(groups));
  return groups;
}

function readLocalArray(key) {
  try {
    const value = JSON.parse(localStorage.getItem(key) || "[]");
    return Array.isArray(value) ? value : [];
  } catch (error) {
    console.warn(`Could not read ${key}`, error);
    return [];
  }
}

function cleanRuleGroups(groups, knownRuleIds) {
  return groups.map((group) => ({
    id: group.id || createId("group"),
    name: group.name || "Untitled Rule Group",
    minMatches: Number(group.minMatches) || 1,
    ruleIds: (group.ruleIds || []).filter((id) => knownRuleIds.has(id)),
  })).filter((group) => group.ruleIds.length);
}

function saveRuleGroups() {
  localStorage.setItem(RULE_GROUP_STORAGE_KEY, JSON.stringify(state.ruleGroups));
  saveStrategySoon();
}

function applyStrategySettings(settings = {}) {
  state.mode = settings.mode === "rule" ? "rule" : "group";
  state.groupId = settings.groupId || state.groupId;
  state.activeRuleIndex = clampIndex(Number(settings.activeRuleIndex) || 0, state.rules.length);
  state.activeRuleGroupIndex = clampIndex(Number(settings.activeRuleGroupIndex) || 0, state.ruleGroups.length);
  state.applyPriceFilter = Boolean(settings.applyPriceFilter);
  state.minUniversePrice = Number(settings.minUniversePrice) || 100;
  state.maxUniversePrice = Number(settings.maxUniversePrice) || 1000;
}

function currentStrategyPayload() {
  return {
    rules: state.rules,
    ruleGroups: state.ruleGroups,
    settings: {
      mode: state.mode,
      groupId: state.groupId,
      activeRuleIndex: state.activeRuleIndex,
      activeRuleGroupIndex: state.activeRuleGroupIndex,
      applyPriceFilter: state.applyPriceFilter,
      minUniversePrice: state.minUniversePrice,
      maxUniversePrice: state.maxUniversePrice,
    },
  };
}

function saveStrategySoon() {
  clearTimeout(state.strategySaveTimer);
  state.strategySaveTimer = setTimeout(saveStrategyNow, 350);
}

async function saveStrategyNow() {
  try {
    await postJson("/api/strategy", currentStrategyPayload());
  } catch (error) {
    console.warn("Could not save strategy to SQLite", error);
  }
}

function clampIndex(index, length) {
  if (!length) return 0;
  return Math.max(0, Math.min(index, length - 1));
}

function defaultRuleGroups() {
  return [{
    id: "universal",
    name: "All Rules Agreement",
    minMatches: Math.min(2, Math.max(1, state.rules.length)),
    ruleIds: state.rules.map((rule) => rule.id),
  }];
}

function starterRules(defaultRule) {
  return [
    {
      id: "rule_volume_delivery_core",
      name: "Volume Delivery Core",
      filters: [
        { id: "price_range", values: { minPrice: 100, maxPrice: 500 } },
        { id: "relative_volume", values: { minRelativeVolume: 1.5, maxRelativeVolume: 999 } },
        { id: "delivery_pct_range", values: { minDeliveryPct: 60, maxDeliveryPct: 100 } },
      ],
    },
    {
      id: "rule_breakout_trend_quality",
      name: "Breakout Trend Quality",
      filters: [
        { id: "price_range", values: { minPrice: 100, maxPrice: 500 } },
        { id: "close_near_20d_high", values: { maxDistanceFrom20DHigh: 2 } },
        { id: "ema_trend", values: { minEmaTrendChecks: 3 } },
        { id: "atr_risk", values: { minAtrPct: 0, maxAtrPct: 8 } },
      ],
    },
    {
      id: "rule_delivery_accumulation",
      name: "Delivery Accumulation",
      filters: [
        { id: "price_range", values: { minPrice: 100, maxPrice: 500 } },
        { id: "delivery_pct_range", values: { minDeliveryPct: 60, maxDeliveryPct: 100 } },
        { id: "relative_delivery_qty", values: { minRelativeDelivery: 1.5, maxRelativeDelivery: 999 } },
      ],
    },
    {
      id: "rule_obv_consolidation",
      name: "OBV Consolidation Breakout",
      filters: [
        { id: "price_range", values: { minPrice: 100, maxPrice: 500 } },
        { id: "range_compression_10d", values: { minCompression10D: 0, maxCompression10D: 12 } },
        { id: "obv_accumulation_3d", values: { minObv3D: 0.5, maxAbsMomentum3D: 2 } },
        { id: "atr_risk", values: { minAtrPct: 0, maxAtrPct: 8 } },
      ],
    },
    {
      id: "rule_momentum_controlled",
      name: "Momentum Controlled",
      filters: [
        { id: "price_range", values: { minPrice: 100, maxPrice: 500 } },
        { id: "price_momentum_3d", values: { minMomentum3D: 2, maxMomentum3D: 8 } },
        { id: "rsi14_range", values: { rsiMin: 50, rsiMax: 68 } },
        { id: "atr_risk", values: { minAtrPct: 0, maxAtrPct: 8 } },
      ],
    },
    {
      id: "rule_multi_period_trend",
      name: "Multi-Period Trend",
      filters: [
        { id: "price_range", values: { minPrice: 100, maxPrice: 500 } },
        {
          id: "multi_period_momentum",
          values: {
            useMomentum1W: false,
            minMomentum1W: 0,
            maxMomentum1W: 15,
            useMomentum15D: true,
            minMomentum15D: 2,
            maxMomentum15D: 25,
            useMomentum1M: false,
            minMomentum1M: 5,
            maxMomentum1M: 30,
            useMomentum3M: true,
            minMomentum3M: 10,
            maxMomentum3M: 60,
            useMomentum6M: false,
            minMomentum6M: 15,
            maxMomentum6M: 120,
            useMomentum1Y: false,
            minMomentum1Y: 20,
            maxMomentum1Y: 250,
            useMomentum6MTo12M: false,
            minMomentum6MTo12M: -20,
            maxMomentum6MTo12M: 80,
          },
        },
        { id: "atr_risk", values: { minAtrPct: 0, maxAtrPct: 8 } },
      ],
    },
    {
      id: "rule_quiet_trend_compression",
      name: "Quiet Trend Compression",
      filters: [
        { id: "price_range", values: { minPrice: 100, maxPrice: 500 } },
        { id: "range_compression_10d", values: { minCompression10D: 0, maxCompression10D: 12 } },
        { id: "close_near_20d_high", values: { maxDistanceFrom20DHigh: 3 } },
        { id: "ema_trend", values: { minEmaTrendChecks: 3 } },
        { id: "atr_risk", values: { minAtrPct: 3, maxAtrPct: 6 } },
        { id: "rsi14_range", values: { rsiMin: 50, rsiMax: 68 } },
        { id: "obv_accumulation_3d", values: { minObv3D: 0.5, maxAbsMomentum3D: 8 } },
      ],
    },
    {
      id: "rule_discovered_high_rsi_long_momentum_delivery",
      name: "Discovered: High RSI Long Momentum Delivery",
      filters: [
        { id: "price_range", values: { minPrice: 100, maxPrice: 1000 } },
        { id: "rsi14_range", values: { rsiMin: 70, rsiMax: 100 } },
        { id: "multi_period_momentum", values: momentumValues({ useMomentum3M: true, useMomentum6M: true }) },
        { id: "delivery_pct_range", values: { minDeliveryPct: 40, maxDeliveryPct: 100 } },
      ],
    },
    {
      id: "rule_discovered_long_momentum_cci_delivery",
      name: "Discovered: Long Momentum CCI Delivery",
      filters: [
        { id: "price_range", values: { minPrice: 100, maxPrice: 1000 } },
        { id: "multi_period_momentum", values: momentumValues({ useMomentum15D: true, useMomentum1Y: true }) },
        { id: "delivery_pct_range", values: { minDeliveryPct: 40, maxDeliveryPct: 100 } },
        { id: "cci14_strong_trend", values: { minCci14: 200, maxCci14: 999 } },
      ],
    },
    {
      id: "rule_discovered_52w_volume_rsi",
      name: "Discovered: 52W High Volume RSI",
      filters: [
        { id: "price_range", values: { minPrice: 100, maxPrice: 1000 } },
        { id: "range_position_52w", values: { minRangePosition52W: 70, maxRangePosition52W: 100 } },
        { id: "relative_volume", values: { minRelativeVolume: 1.5, maxRelativeVolume: 999 } },
        { id: "rsi14_range", values: { rsiMin: 60, rsiMax: 80 } },
      ],
    },
    {
      id: "rule_discovered_pause_breakout_volume",
      name: "Discovered: Pause Breakout Volume",
      filters: [
        { id: "price_range", values: { minPrice: 100, maxPrice: 1000 } },
        { id: "price_change_1d", values: { minPriceChange1D: 5, maxPriceChange1D: 999 } },
        { id: "price_momentum_3d", values: { minMomentum3D: -3, maxMomentum3D: 3 } },
        { id: "relative_volume", values: { minRelativeVolume: 3, maxRelativeVolume: 999 } },
      ],
    },
    {
      id: "rule_deep_compression_ema_launch",
      name: "Deep: Compression EMA Launch",
      filters: [
        { id: "price_range", values: { minPrice: 100, maxPrice: 1000 } },
        { id: "price_change_1d", values: { minPriceChange1D: 5, maxPriceChange1D: 999 } },
        { id: "range_compression_10d", values: { minCompression10D: 0, maxCompression10D: 8 } },
        { id: "ema_trend", values: { minEmaTrendChecks: 3 } },
      ],
    },
    {
      id: "rule_deep_10d_volume_near_high",
      name: "Deep: 10D Volume Near High",
      filters: [
        { id: "price_range", values: { minPrice: 100, maxPrice: 1000 } },
        { id: "relative_volume_10d", values: { minRelativeVolume10D: 3, maxRelativeVolume10D: 999 } },
        { id: "price_momentum_3d", values: { minMomentum3D: -3, maxMomentum3D: 3 } },
        { id: "range_position_52w", values: { minRangePosition52W: 80, maxRangePosition52W: 100 } },
      ],
    },
    {
      id: "rule_deep_mfi_cci_long_momentum",
      name: "Deep: MFI CCI Long Momentum",
      filters: [
        { id: "price_range", values: { minPrice: 100, maxPrice: 1000 } },
        { id: "multi_period_momentum", values: momentumValues({ useMomentum15D: true, useMomentum1Y: true }) },
        { id: "mfi14_range", values: { mfiMin: 40, mfiMax: 70 } },
        { id: "cci14_strong_trend", values: { minCci14: 200, maxCci14: 999 } },
      ],
    },
    {
      id: "rule_screenshot_momentum_proxy",
      name: "Screenshot: Momentum Stocks Proxy",
      filters: [
        { id: "price_range", values: { minPrice: 100, maxPrice: 999999 } },
        { id: "price_change_1d", values: { minPriceChange1D: 5, maxPriceChange1D: 999 } },
        { id: "rsi14_range", values: { rsiMin: 70, rsiMax: 100 } },
        { id: "rsi14_rising", values: { minRsiRise: 0 } },
        { id: "daily_volume_range", values: { minDailyVolume: 20000, maxDailyVolume: 999999999 } },
        { id: "ema10_above_ema20", values: { minEmaGapPct: 0 } },
        { id: "cci14_strong_trend", values: { minCci14: 200, maxCci14: 999 } },
      ],
    },
  ];
}

function momentumValues(overrides = {}) {
  return {
    useMomentum1W: false,
    minMomentum1W: 0,
    maxMomentum1W: 15,
    useMomentum15D: false,
    minMomentum15D: 2,
    maxMomentum15D: 25,
    useMomentum1M: false,
    minMomentum1M: 5,
    maxMomentum1M: 30,
    useMomentum3M: false,
    minMomentum3M: 10,
    maxMomentum3M: 60,
    useMomentum6M: false,
    minMomentum6M: 15,
    maxMomentum6M: 120,
    useMomentum1Y: false,
    minMomentum1Y: 20,
    maxMomentum1Y: 250,
    useMomentum6MTo12M: false,
    minMomentum6MTo12M: -20,
    maxMomentum6MTo12M: 80,
    ...overrides,
  };
}

function starterRuleGroups() {
  const availableIds = new Set(state.rules.map((rule) => rule.id));
  const group = (id, name, minMatches, ruleIds) => ({
    id,
    name,
    minMatches,
    ruleIds: ruleIds.filter((ruleId) => availableIds.has(ruleId)),
  });
  return [
    ...defaultRuleGroups(),
    group("group_core_agreement", "Core Agreement", 2, [
      "rule_volume_delivery_core",
      "rule_breakout_trend_quality",
    ]),
    group("group_swing_quality", "Swing Quality Basket", 2, [
      "rule_volume_delivery_core",
      "rule_breakout_trend_quality",
      "rule_delivery_accumulation",
      "rule_momentum_controlled",
      "rule_multi_period_trend",
    ]),
    group("group_breakout_watch", "Breakout Watch", 2, [
      "rule_breakout_trend_quality",
      "rule_obv_consolidation",
      "rule_momentum_controlled",
    ]),
    group("group_quiet_trend_watch", "Quiet Trend Watch", 1, [
      "rule_quiet_trend_compression",
    ]),
    group("group_discovered_trend_strength", "Discovered: Trend Strength Group", 1, [
      "rule_discovered_high_rsi_long_momentum_delivery",
      "rule_discovered_52w_volume_rsi",
    ]),
    group("group_discovered_strict_trend_agreement", "Discovered: Strict Trend Agreement", 2, [
      "rule_discovered_high_rsi_long_momentum_delivery",
      "rule_discovered_52w_volume_rsi",
    ]),
    group("group_discovered_momentum_burst", "Discovered: Momentum Burst Group", 1, [
      "rule_discovered_long_momentum_cci_delivery",
      "rule_discovered_pause_breakout_volume",
    ]),
    group("group_discovered_high_conviction_swing", "Discovered: High Conviction Swing", 2, [
      "rule_discovered_high_rsi_long_momentum_delivery",
      "rule_discovered_long_momentum_cci_delivery",
      "rule_discovered_52w_volume_rsi",
    ]),
    group("group_deep_compression_breakout", "Deep: Compression Breakout Group", 1, [
      "rule_deep_compression_ema_launch",
      "rule_deep_10d_volume_near_high",
    ]),
    group("group_deep_mfi_momentum", "Deep: MFI Momentum Group", 1, [
      "rule_deep_mfi_cci_long_momentum",
      "rule_discovered_long_momentum_cci_delivery",
    ]),
    group("group_deep_high_conviction_research", "Deep: High Conviction Research", 2, [
      "rule_deep_compression_ema_launch",
      "rule_deep_10d_volume_near_high",
      "rule_deep_mfi_cci_long_momentum",
    ]),
    group("group_screenshot_momentum_proxy", "Screenshot: Momentum Stocks Proxy", 1, [
      "rule_screenshot_momentum_proxy",
    ]),
  ].filter((group) => group.ruleIds.length);
}

function withRuleIds(rules) {
  let changed = false;
  const result = rules.map((rule) => {
    const nextRule = {
      ...rule,
      filters: (rule.filters || []).map((filter) => {
        if (filter.id === "price_range") {
          changed = true;
          return null;
        }
        const definition = filterDefinition(filter.id);
        if (!definition) return filter;
        const defaults = defaultValuesForFilter(definition);
        const values = { ...defaults, ...(filter.values || {}) };
        Object.keys(defaults).forEach((key) => {
          if (filter.values?.[key] === undefined) changed = true;
        });
        return { ...filter, values };
      }).filter(Boolean),
    };
    if (rule.id) return nextRule;
    changed = true;
    return { ...nextRule, id: createId("rule") };
  }).filter((rule) => rule.filters.length);
  if (changed) localStorage.setItem(STORAGE_KEY, JSON.stringify(result));
  return result;
}

function defaultValuesForFilter(definition) {
  return Object.fromEntries((definition.fields || []).map((field) => [field.key, field.default]));
}

function createId(prefix) {
  return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
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

function formatSignedNumber(value) {
  const number = Number(value);
  return `${number > 0 ? "+" : ""}${number.toFixed(2)}`;
}
