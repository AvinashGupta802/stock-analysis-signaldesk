const STORAGE_KEY = "signaldesk.buyRules.v1";
const RULE_GROUP_STORAGE_KEY = "signaldesk.ruleGroups.v1";

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
  ignorePriceFilter: false,
  groupId: "all",
  date: null,
  search: "",
  results: [],
  metrics: {},
  prices: [],
  selectedSymbol: null,
  backtest: null,
  defaultBacktest: null,
};

const el = {
  viewButtons: Array.from(document.querySelectorAll("[data-view-button]")),
  viewSections: Array.from(document.querySelectorAll("[data-view-section]")),
  analysisModeSelect: document.querySelector("#analysisModeSelect"),
  analysisRuleSelect: document.querySelector("#analysisRuleSelect"),
  analysisRuleGroupSelect: document.querySelector("#analysisRuleGroupSelect"),
  analysisRuleLabel: document.querySelector("#analysisRuleLabel"),
  analysisGroupLabel: document.querySelector("#analysisGroupLabel"),
  ignorePriceFilterInput: document.querySelector("#ignorePriceFilterInput"),
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
  state.rules = loadSavedRules(bootstrap.defaultRule);
  state.ruleGroups = loadSavedRuleGroups();
  state.groupId = state.groups[0]?.id || "all";
  state.date = state.dates[state.dates.length - 1];
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
    renderAll();
    runScan();
  });
  el.analysisRuleSelect.addEventListener("change", () => {
    state.activeRuleIndex = Number(el.analysisRuleSelect.value);
    state.mode = "rule";
    state.backtest = null;
    renderAll();
    runScan();
  });
  el.analysisRuleGroupSelect.addEventListener("change", () => {
    state.activeRuleGroupIndex = Number(el.analysisRuleGroupSelect.value);
    state.mode = "group";
    state.backtest = null;
    renderAll();
    runScan();
  });
  el.ignorePriceFilterInput.addEventListener("change", () => {
    state.ignorePriceFilter = el.ignorePriceFilterInput.checked;
    state.backtest = null;
    renderAll();
    runScan();
  });
  el.createCombinedGroupButton.addEventListener("click", createCombinedStockGroup);
  el.ruleSelect.addEventListener("change", () => {
    state.activeRuleIndex = Number(el.ruleSelect.value);
    state.mode = "rule";
    state.view = "rules";
    state.backtest = null;
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
  el.groupSelect.addEventListener("change", () => {
    state.groupId = el.groupSelect.value;
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
  el.ignorePriceFilterInput.checked = state.ignorePriceFilter;
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
        ${state.ignorePriceFilter ? "<p>Price Range filters are ignored for this run.</p>" : ""}
        <ul>
          ${selectedRules.map((item) => `<li><strong>${escapeHtml(item.name)}:</strong> ${formatNumber(item.filters.length)} filters</li>`).join("")}
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
      ${state.ignorePriceFilter ? "<p>Price Range filters are ignored for this run.</p>" : ""}
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
    el.resultsBody.innerHTML = `<tr><td colspan="18" class="empty-state">No stocks passed this ${state.mode === "group" ? "rule group" : "rule"}.</td></tr>`;
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
      <td>${formatPlainPct(item.closePositionDay || 0)}</td>
      <td>${formatPlainPct(item.compression10D || 0)}</td>
      <td>${formatPct(item.distanceFrom20DHigh || 0)}</td>
      <td>${formatPlainPct(item.rangePosition52W || 0)}</td>
      <td>${Number(item.obv3D || 0).toFixed(2)}x</td>
      <td>${formatNumber(item.adv20)}</td>
      <td>Rs. ${formatMoney(item.rupeeLiquidityCr || 0)} cr</td>
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
      <p>Volume is ${Number(item.relativeVolume || 0).toFixed(2)}x of its 20-day average.</p>
      <p>20-day rupee liquidity is Rs. ${formatMoney(item.rupeeLiquidityCr || 0)} cr.</p>
      <p>3-day price change is ${formatPct(item.momentum3D || 0)}.</p>
      <p>Close position in today's range is ${formatPlainPct(item.closePositionDay || 0)}.</p>
      <p>10-day range compression is ${formatPlainPct(item.compression10D || 0)}. Lower values mean the stock has been moving in a tighter range.</p>
      <p>Close is ${formatPct(item.distanceFrom20DHigh || 0)} from 20D high Rs. ${formatMoney(item.high20D || 0)}.</p>
      <p>52W position is ${formatPlainPct(item.rangePosition52W || 0)} between low Rs. ${formatMoney(item.low52W || 0)} and high Rs. ${formatMoney(item.high52W || 0)}.</p>
      <p>EMA trend: close Rs. ${formatMoney(item.close)}, EMA9 Rs. ${formatMoney(item.ema9 || 0)}, EMA20 Rs. ${formatMoney(item.ema20 || 0)}, SMA50 Rs. ${formatMoney(item.sma50 || 0)}.</p>
      <p>ATR risk is ${formatPlainPct(item.atrPct || 0)} with ATR14 Rs. ${formatMoney(item.atr14 || 0)}.</p>
      <p>3-day OBV change is ${Number(item.obv3D || 0).toFixed(2)}x of 20-day average volume.</p>
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
  if (state.mode === "group") return runRuleGroupScan();
  return runRuleScan();
}

async function runRuleScan() {
  const payload = {
    rule: ruleForRun(currentRule()),
    group: state.groupId,
    date: state.date,
    search: state.search,
    limit: 200,
  };
  el.resultsBody.innerHTML = `<tr><td colspan="18" class="empty-state">Running rule...</td></tr>`;
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
  const values = Object.fromEntries(definition.fields.map((field) => [field.key, field.default]));
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
  return group.ruleIds.map((id) => state.rules.find((rule) => rule.id === id)).filter(Boolean);
}

async function runRuleGroupScan() {
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
    group: state.groupId,
    date: state.date,
    search: state.search,
    limit: 200,
  };
  el.resultsBody.innerHTML = `<tr><td colspan="18" class="empty-state">Running rule group...</td></tr>`;
  const result = await postJson("/api/rule-group/results", payload);
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

function filterDefinition(filterId) {
  return state.filterLibrary.find((filter) => filter.id === filterId);
}

function ruleForRun(rule) {
  if (!state.ignorePriceFilter) return rule;
  return {
    ...rule,
    filters: rule.filters.filter((filter) => filter.id !== "price_range"),
  };
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
  if (selected.id === "relative_volume") return `Today volume between ${values.minRelativeVolume}x and ${values.maxRelativeVolume}x of 20D average volume`;
  if (selected.id === "delivery_pct_range") return `Delivery percentage between ${values.minDeliveryPct}% and ${values.maxDeliveryPct}%`;
  if (selected.id === "relative_delivery_qty") return `Today delivered quantity between ${values.minRelativeDelivery}x and ${values.maxRelativeDelivery}x of 20D average delivered quantity`;
  if (selected.id === "price_momentum_3d") return `3-day price change between ${values.minMomentum3D}% and ${values.maxMomentum3D}%`;
  if (selected.id === "range_position_52w") return `Close position between ${values.minRangePosition52W}% and ${values.maxRangePosition52W}% of 52-week range`;
  if (selected.id === "close_near_20d_high") return `Close within ${values.maxDistanceFrom20DHigh}% below the 20-day high`;
  if (selected.id === "close_position_day_range") return `Close position between ${values.minClosePositionDay}% and ${values.maxClosePositionDay}% of today's high-low range`;
  if (selected.id === "range_compression_10d") return `10-day high-low range between ${values.minCompression10D}% and ${values.maxCompression10D}% of close`;
  if (selected.id === "rupee_liquidity") return `20D average traded value between Rs. ${values.minRupeeLiquidityCr} cr and Rs. ${values.maxRupeeLiquidityCr} cr`;
  if (selected.id === "ema_trend") return `At least ${values.minEmaTrendChecks} of 3 trend checks pass: close above EMA9, close above EMA20, EMA20 above SMA50`;
  if (selected.id === "atr_risk") return `ATR 14 between ${values.minAtrPct}% and ${values.maxAtrPct}% of close`;
  if (selected.id === "obv_accumulation_3d") return `3-day OBV change at least ${values.minObv3D}x of 20D average volume while 3-day price move stays within +/-${values.maxAbsMomentum3D}%`;
  if (selected.id === "rsi14_range") return `RSI 14 between ${values.rsiMin} and ${values.rsiMax}`;
  return JSON.stringify(values);
}

function loadSavedRules(defaultRule) {
  const starters = starterRules(defaultRule);
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
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
}

function loadSavedRuleGroups() {
  const templates = starterRuleGroups();
  try {
    const saved = JSON.parse(localStorage.getItem(RULE_GROUP_STORAGE_KEY) || "[]");
    if (Array.isArray(saved) && saved.length) {
      const knownRuleIds = new Set(state.rules.map((rule) => rule.id));
      const cleaned = saved.map((group) => ({
        id: group.id || createId("group"),
        name: group.name || "Untitled Rule Group",
        minMatches: Number(group.minMatches) || 1,
        ruleIds: (group.ruleIds || []).filter((id) => knownRuleIds.has(id)),
      })).filter((group) => group.ruleIds.length);
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

function saveRuleGroups() {
  localStorage.setItem(RULE_GROUP_STORAGE_KEY, JSON.stringify(state.ruleGroups));
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
      ...defaultRule,
      id: "rule_price_range",
      name: "Price Range Only",
    },
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
  ];
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
    ]),
    group("group_breakout_watch", "Breakout Watch", 2, [
      "rule_breakout_trend_quality",
      "rule_obv_consolidation",
      "rule_momentum_controlled",
    ]),
    group("group_quiet_trend_watch", "Quiet Trend Watch", 1, [
      "rule_quiet_trend_compression",
    ]),
  ].filter((group) => group.ruleIds.length);
}

function withRuleIds(rules) {
  let changed = false;
  const result = rules.map((rule) => {
    if (rule.id) return rule;
    changed = true;
    return { ...rule, id: createId("rule") };
  });
  if (changed) localStorage.setItem(STORAGE_KEY, JSON.stringify(result));
  return result;
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
