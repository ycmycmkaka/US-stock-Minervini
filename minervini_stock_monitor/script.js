let allRows = [];
let filteredRows = [];
let currentSort = "rs_rating_desc";

const summaryCard = document.getElementById("summaryCard");
const rulesCard = document.getElementById("rulesCard");
const searchInput = document.getElementById("searchInput");
const sortSelect = document.getElementById("sortSelect");
const resultsBody = document.getElementById("resultsBody");
const emptyState = document.getElementById("emptyState");
const countText = document.getElementById("countText");

function formatMarketCap(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "-";
  if (n >= 1_000_000_000_000) return `$${(n / 1_000_000_000_000).toFixed(2)}T`;
  if (n >= 1_000_000_000) return `$${(n / 1_000_000_000).toFixed(2)}B`;
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  return `$${n.toFixed(0)}`;
}

function formatPrice(value) {
  const n = Number(value);
  return Number.isFinite(n) ? `$${n.toFixed(2)}` : "-";
}

function formatPct(value) {
  const n = Number(value);
  return Number.isFinite(n) ? `${n.toFixed(1)}%` : "-";
}

function pctClass(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "neutral";
  if (n > 0) return "positive";
  if (n < 0) return "negative";
  return "neutral";
}

function marketCapBadgeClass(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "badge-marketcap-default";
  if (n >= 100_000_000_000) return "badge-marketcap-red";
  if (n >= 50_000_000_000) return "badge-marketcap-yellow";
  return "badge-marketcap-default";
}

function rsBadgeClass(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "badge-marketcap-default";
  if (n >= 95) return "badge-marketcap-red";
  if (n >= 90) return "badge-marketcap-yellow";
  return "badge-rs";
}

function escapeHtml(text) {
  return String(text ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderSummary(data) {
  const updated = data.generated_at || "Unknown";
  const count = Array.isArray(data.results) ? data.results.length : 0;
  const stats = data.scan_stats || {};

  const pipeline = [
    Number.isFinite(Number(stats.market_cap_eligible)) ? `市值合格 ${stats.market_cap_eligible}` : null,
    Number.isFinite(Number(stats.trend_template_8_of_8)) ? `Trend 8/8 ${stats.trend_template_8_of_8}` : null
  ].filter(Boolean).join(" ｜ ");

  summaryCard.innerHTML = `
    <div class="summary-label">今日符合最終條件</div>
    <div class="summary-count">${count} 隻</div>
    <div class="summary-updated">最後更新：${escapeHtml(updated)}</div>
    <div class="summary-updated">${escapeHtml(pipeline)}</div>
  `;
}

function renderRules(data) {
  const rules = data.rules || {};
  const benchmark = rules.benchmark_symbol || "SPY";

  const chips = [
    "只限美股普通股",
    `市值 ≥ ${formatMarketCap(rules.market_cap_min || 0)}`,
    `Minervini Trend Template = ${Number(rules.trend_template_required_score ?? 8)}/8`,
    `自製 RS Rating ≥ ${Number(rules.min_rs_rating ?? 80).toFixed(0)}`,
    `20日跑贏 ${benchmark} ≥ ${Number(rules.min_rs_20d_vs_spy_pct ?? 0).toFixed(1)}%`,
    `60日跑贏 ${benchmark} ≥ ${Number(rules.min_rs_60d_vs_spy_pct ?? 0).toFixed(1)}%`,
    `距52週高位 ≤ ${Number(rules.max_dist_from_52w_high_pct ?? 15).toFixed(1)}%`
  ];

  const extra = [];
  if (Number.isFinite(Number(rules.spy_twenty_day_return_pct))) {
    extra.push(`${benchmark} 20D：${formatPct(rules.spy_twenty_day_return_pct)}`);
  }
  if (Number.isFinite(Number(rules.spy_sixty_day_return_pct))) {
    extra.push(`${benchmark} 60D：${formatPct(rules.spy_sixty_day_return_pct)}`);
  }
  extra.push("RS Rating 為自製全市場百分位，並非 IBD 官方 proprietary RS Rating");

  rulesCard.innerHTML = `
    <div class="rules-title">目前篩選條件</div>
    <div class="rule-chips">
      ${chips.map(chip => `<span class="rule-chip">${escapeHtml(chip)}</span>`).join("")}
    </div>
    <div class="rules-extra">${extra.map(escapeHtml).join(" ｜ ")}</div>
  `;
}

function sortRows(rows, sortKey) {
  const cloned = [...rows];
  const num = (v, fallback = -Infinity) => Number.isFinite(Number(v)) ? Number(v) : fallback;

  switch (sortKey) {
    case "rs_rating_desc":
      cloned.sort((a, b) => num(b.rs_rating) - num(a.rs_rating));
      break;
    case "rs_60d_vs_spy_pct_desc":
      cloned.sort((a, b) => num(b.rs_60d_vs_spy_pct) - num(a.rs_60d_vs_spy_pct));
      break;
    case "rs_20d_vs_spy_pct_desc":
      cloned.sort((a, b) => num(b.rs_20d_vs_spy_pct) - num(a.rs_20d_vs_spy_pct));
      break;
    case "dist_from_52w_high_pct_desc":
      cloned.sort((a, b) => num(b.dist_from_52w_high_pct) - num(a.dist_from_52w_high_pct));
      break;
    case "market_cap_desc":
      cloned.sort((a, b) => num(b.market_cap) - num(a.market_cap));
      break;
    case "symbol_asc":
      cloned.sort((a, b) => String(a.symbol || "").localeCompare(String(b.symbol || "")));
      break;
    default:
      cloned.sort((a, b) => num(b.rs_rating) - num(a.rs_rating));
  }

  return cloned;
}

function renderTable(rows) {
  resultsBody.innerHTML = "";

  if (!rows.length) {
    emptyState.classList.remove("hidden");
    countText.textContent = "顯示 0 隻";
    return;
  }

  emptyState.classList.add("hidden");
  countText.textContent = `顯示 ${rows.length} 隻`;

  const html = rows.map((row) => `
    <tr>
      <td class="symbol-cell">${escapeHtml(row.symbol || "")}</td>
      <td class="company-cell">${escapeHtml(row.company || "")}</td>
      <td>
        <span class="badge ${marketCapBadgeClass(row.market_cap)}">${formatMarketCap(row.market_cap)}</span>
      </td>
      <td><span class="badge badge-price">${formatPrice(row.recent_close)}</span></td>
      <td><span class="badge badge-template">${Number(row.trend_template_score ?? 0)}/8</span></td>
      <td><span class="badge ${rsBadgeClass(row.rs_rating)}">${Number(row.rs_rating ?? 0).toFixed(0)}</span></td>
      <td class="${pctClass(row.rs_20d_vs_spy_pct)}">${formatPct(row.rs_20d_vs_spy_pct)}</td>
      <td class="${pctClass(row.rs_60d_vs_spy_pct)}">${formatPct(row.rs_60d_vs_spy_pct)}</td>
      <td class="${pctClass(row.dist_from_52w_high_pct)}">${formatPct(row.dist_from_52w_high_pct)}</td>
      <td class="positive">+${formatPct(row.pct_above_52w_low).replace("+", "")}</td>
    </tr>
  `).join("");

  resultsBody.innerHTML = html;
}

function applySearchAndSort() {
  const keyword = (searchInput.value || "").trim().toLowerCase();

  filteredRows = allRows.filter((row) => {
    if (!keyword) return true;
    const symbol = String(row.symbol || "").toLowerCase();
    const company = String(row.company || "").toLowerCase();
    return symbol.includes(keyword) || company.includes(keyword);
  });

  filteredRows = sortRows(filteredRows, currentSort);
  renderTable(filteredRows);
}

async function loadData() {
  try {
    const response = await fetch(`results.json?t=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    const data = await response.json();
    renderSummary(data);
    renderRules(data);

    allRows = Array.isArray(data.results) ? data.results : [];
    currentSort = sortSelect.value || "rs_rating_desc";
    applySearchAndSort();
  } catch (error) {
    console.error(error);
    summaryCard.innerHTML = `
      <div class="summary-label">載入失敗</div>
      <div class="summary-updated">請稍後再試</div>
    `;
    rulesCard.innerHTML = `
      <div class="rules-title">目前篩選條件</div>
      <div class="rules-extra">未能讀取 results.json</div>
    `;
    resultsBody.innerHTML = "";
    emptyState.classList.remove("hidden");
    countText.textContent = "顯示 0 隻";
  }
}

searchInput.addEventListener("input", applySearchAndSort);
sortSelect.addEventListener("change", () => {
  currentSort = sortSelect.value;
  applySearchAndSort();
});

loadData();
