(() => {
  const panelDefs = [
    { id: "profit_curve", label: "盈利曲线", live: true },
    { id: "reserved_vpip", label: "入池率 (预留)", live: false },
    { id: "reserved_extra", label: "更多分析 (预留)", live: false },
  ];

  const state = {
    open: new Set(),
    profitChart: null,
    analyzed: false,
    summary: null,
    filterDefaults: null,
  };

  const $ = (sel) => document.querySelector(sel);

  function moneyClass(n) {
    if (n > 0) return "pos";
    if (n < 0) return "neg";
    return "";
  }

  function fmtMoney(n) {
    const sign = n > 0 ? "+" : "";
    return `${sign}${Number(n).toFixed(2)}`;
  }

  async function fetchJSON(url, options) {
    const res = await fetch(url, options);
    if (!res.ok) {
      const detail = await res.text();
      throw new Error(detail || res.statusText);
    }
    return res.json();
  }

  function renderToggles() {
    const host = $("#panelToggles");
    host.innerHTML = "";
    for (const def of panelDefs) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "toggle-btn" + (state.open.has(def.id) ? " active" : "");
      btn.dataset.panel = def.id;
      btn.textContent = def.label;
      btn.addEventListener("click", () => togglePanel(def.id));
      host.appendChild(btn);
    }
  }

  function togglePanel(id) {
    if (state.open.has(id)) {
      state.open.delete(id);
    } else {
      state.open.add(id);
    }
    syncPanels();
    renderToggles();
  }

  function syncPanels() {
    for (const def of panelDefs) {
      const panel = document.getElementById(`panel-${def.id}`);
      if (!panel) continue;
      panel.hidden = !state.open.has(def.id);
    }
  }

  function setupFilter(summary) {
    const filter = summary.filter || {};
    state.filterDefaults = {
      date_from: filter.date_from || "",
      date_to: filter.date_to || "",
      stakes: (filter.stakes_presets || []).map((s) => s.id),
    };

    const dateFrom = $("#dateFrom");
    const dateTo = $("#dateTo");
    dateFrom.min = filter.date_from || "";
    dateFrom.max = filter.date_to || "";
    dateTo.min = filter.date_from || "";
    dateTo.max = filter.date_to || "";
    dateFrom.value = state.filterDefaults.date_from;
    dateTo.value = state.filterDefaults.date_to;

    const host = $("#stakesGroup");
    host.innerHTML = "";
    for (const stake of filter.stakes_presets || []) {
      const label = document.createElement("label");
      label.className = "stake-chip" + (stake.has_data ? " has-data" : "");
      label.innerHTML = `
        <input type="checkbox" value="${stake.id}" checked />
        <span>${stake.label}</span>
        ${stake.has_data ? "" : '<span class="tag">预留</span>'}
      `;
      host.appendChild(label);
    }
  }

  function resetFilter() {
    if (!state.filterDefaults) return;
    $("#dateFrom").value = state.filterDefaults.date_from;
    $("#dateTo").value = state.filterDefaults.date_to;
    for (const input of document.querySelectorAll("#stakesGroup input[type=checkbox]")) {
      input.checked = true;
    }
  }

  function readFilter() {
    const stakes = [...document.querySelectorAll("#stakesGroup input[type=checkbox]:checked")]
      .map((el) => el.value);
    return {
      date_from: $("#dateFrom").value || null,
      date_to: $("#dateTo").value || null,
      stakes,
    };
  }

  async function loadSummary() {
    const data = await fetchJSON("/api/summary");
    state.summary = data;
    const range =
      data.date_range?.start && data.date_range?.end
        ? `${data.date_range.start} → ${data.date_range.end}`
        : "无数据";
    $("#summaryText").textContent =
      `已加载 ${data.hand_count} 手 · ${data.file_count} 个文件 · ${range}`;
    setupFilter(data);
    return data;
  }

  async function analyze() {
    const filter = readFilter();
    if (!filter.stakes.length) {
      $("#filterStatus").textContent = "请至少选择一个游戏级别。";
      return;
    }

    const btn = $("#analyzeBtn");
    btn.disabled = true;
    btn.textContent = "分析中…";
    $("#filterStatus").textContent = "正在按筛选条件计算…";

    try {
      // Refresh every open live panel with the same filter
      for (const def of panelDefs) {
        if (!state.open.has(def.id) || !def.live) continue;
        if (def.id === "profit_curve") {
          const data = await fetchJSON("/api/metrics/profit_curve", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(filter),
          });
          renderProfit(data);
        }
      }

      // If profit panel is closed, still warm-load nothing; user can reopen + re-analyze
      if (!state.open.has("profit_curve")) {
        // Keep analyzed=false for closed live panels until opened+analyzed
      }

      state.analyzed = true;
      const stakesLabel = filter.stakes.join(", ") || "无";
      $("#filterStatus").textContent =
        `已分析：${filter.date_from || "?"} ~ ${filter.date_to || "?"} · 级别 ${stakesLabel}`;
    } catch (err) {
      $("#filterStatus").textContent = `分析失败: ${err.message}`;
      console.error(err);
    } finally {
      btn.disabled = false;
      btn.textContent = "分析";
    }
  }

  function renderProfit(data) {
    const empty = $("#profitEmpty");
    const chartWrap = document.querySelector("#panel-profit_curve .chart-wrap");
    const stats = $("#profitStats");

    if (!data.hand_count) {
      empty.hidden = false;
      if (chartWrap) chartWrap.hidden = true;
      stats.innerHTML = "";
      if (state.profitChart) {
        state.profitChart.destroy();
        state.profitChart = null;
      }
      return;
    }

    empty.hidden = true;
    if (chartWrap) chartWrap.hidden = false;

    const before = data.total_profit_before_rake;
    const after = data.total_profit_after_rake;
    stats.innerHTML = `
      <div class="stat">
        <span class="label">手数</span>
        <span class="value">${data.hand_count}</span>
      </div>
      <div class="stat">
        <span class="label">总计盈利（抽水前）</span>
        <span class="value ${moneyClass(before)}">${fmtMoney(before)}</span>
      </div>
      <div class="stat">
        <span class="label">总计真实盈利（抽水后）</span>
        <span class="value ${moneyClass(after)}">${fmtMoney(after)}</span>
      </div>
      <div class="stat">
        <span class="label">累计抽水</span>
        <span class="value">${fmtMoney(data.total_rake_paid)}</span>
      </div>
    `;

    const ctx = $("#profitChart");
    const labels = data.series.hand_index;
    const datasetCommon = {
      borderWidth: 2,
      pointRadius: 0,
      pointHoverRadius: 3,
      tension: 0.15,
    };

    if (state.profitChart) {
      state.profitChart.destroy();
    }

    state.profitChart = new Chart(ctx, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: "抽水前",
            data: data.series.profit_before_rake,
            borderColor: "#c4a35a",
            backgroundColor: "rgba(196, 163, 90, 0.12)",
            ...datasetCommon,
          },
          {
            label: "抽水后",
            data: data.series.profit_after_rake,
            borderColor: "#3d9b7a",
            backgroundColor: "rgba(61, 155, 122, 0.12)",
            ...datasetCommon,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: {
            labels: { color: "#c5d0db" },
          },
          tooltip: {
            callbacks: {
              title(items) {
                return `第 ${items[0].label} 手`;
              },
              label(ctx) {
                return `${ctx.dataset.label}: ${fmtMoney(ctx.parsed.y)}`;
              },
            },
          },
        },
        scales: {
          x: {
            title: { display: true, text: "手数", color: "#8b9aab" },
            ticks: {
              color: "#8b9aab",
              maxTicksLimit: 12,
            },
            grid: { color: "rgba(44, 58, 74, 0.55)" },
          },
          y: {
            title: { display: true, text: "累计盈利 ($)", color: "#8b9aab" },
            ticks: {
              color: "#8b9aab",
              callback: (v) => Number(v).toFixed(2),
            },
            grid: { color: "rgba(44, 58, 74, 0.55)" },
          },
        },
      },
    });
  }

  async function init() {
    renderToggles();
    await loadSummary();
    state.open.add("profit_curve");
    renderToggles();
    syncPanels();

    $("#analyzeBtn").addEventListener("click", () => analyze());
    $("#resetFilterBtn").addEventListener("click", () => {
      resetFilter();
      $("#filterStatus").textContent = "已重置为全部数据，点击「分析」生效。";
    });

    $("#reloadBtn").addEventListener("click", async () => {
      await fetchJSON("/api/reload", { method: "POST" });
      await loadSummary();
      state.analyzed = false;
      $("#filterStatus").textContent = "数据已重新扫描，请再次点击「分析」。";
    });

    // Default = all data; run once so first visit is useful
    await analyze();
  }

  init().catch((err) => {
    $("#summaryText").textContent = `加载失败: ${err.message}`;
    console.error(err);
  });
})();
