(() => {
  const panelDefs = [
    { id: "profit_curve", label: "盈利曲线", live: true },
    { id: "reserved_vpip", label: "入池率 (预留)", live: false },
    { id: "reserved_extra", label: "更多分析 (预留)", live: false },
  ];

  const state = {
    open: new Set(),
    profitChart: null,
    loadedMetrics: new Set(),
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
      const shouldShow = state.open.has(def.id);
      panel.hidden = !shouldShow;
      if (shouldShow && def.live && !state.loadedMetrics.has(def.id)) {
        loadMetric(def.id);
      }
    }
  }

  async function loadSummary() {
    const data = await fetchJSON("/api/summary");
    const range =
      data.date_range?.start && data.date_range?.end
        ? `${data.date_range.start} → ${data.date_range.end}`
        : "无数据";
    $("#summaryText").textContent =
      `已加载 ${data.hand_count} 手 · ${data.file_count} 个文件 · ${range}`;
    return data;
  }

  async function loadMetric(id) {
    if (id === "profit_curve") {
      const data = await fetchJSON("/api/metrics/profit_curve");
      // Prefer dedicated alias too — both work
      renderProfit(data);
      state.loadedMetrics.add(id);
    }
  }

  function renderProfit(data) {
    const stats = $("#profitStats");
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
    // Phase 1: open profit panel by default so first visit is useful
    state.open.add("profit_curve");
    renderToggles();
    syncPanels();

    $("#reloadBtn").addEventListener("click", async () => {
      state.loadedMetrics.clear();
      await fetchJSON("/api/reload", { method: "POST" });
      await loadSummary();
      syncPanels();
      // Force refresh open live panels
      for (const id of state.open) {
        const def = panelDefs.find((d) => d.id === id);
        if (def?.live) {
          state.loadedMetrics.delete(id);
          await loadMetric(id);
          state.loadedMetrics.add(id);
        }
      }
    });
  }

  init().catch((err) => {
    $("#summaryText").textContent = `加载失败: ${err.message}`;
    console.error(err);
  });
})();
