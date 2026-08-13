(() => {
  const panelDefs = [
    { id: "profit_curve", label: "盈利曲线", live: true },
    { id: "when_i_raise", label: "When I Raise", live: true },
    { id: "reserved_extra", label: "更多分析 (预留)", live: false },
  ];

  const wirStreetOpts = [
    { id: "ALL", label: "ALL" },
    { id: "preflop", label: "Preflop" },
    { id: "flop", label: "Flop" },
    { id: "turn", label: "Turn" },
    { id: "river", label: "River" },
  ];
  const wirPlayerOpts = [
    { id: "2", label: "2人" },
    { id: "3+", label: "2人以上" },
  ];
  const wirSizeOpts = [
    { id: "33", label: "33% pot" },
    { id: "66", label: "66% pot" },
    { id: "110", label: "110% pot" },
  ];
  const wirPositionOpts = [
    { id: "IP", label: "IP" },
    { id: "OOP", label: "OOP" },
    { id: "OTHER", label: "OTHER" },
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

  function fmtPct(n) {
    if (n === null || n === undefined) return "—";
    return `${Number(n).toFixed(2)}%`;
  }

  async function fetchJSON(url, options) {
    const res = await fetch(url, options);
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const payload = await res.json();
        detail = payload.detail || JSON.stringify(payload);
      } catch {
        try {
          detail = await res.text();
        } catch {
          /* ignore */
        }
      }
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
    if (state.open.has(id) && state.analyzed) {
      analyze();
    }
  }

  function syncPanels() {
    for (const def of panelDefs) {
      const panel = document.getElementById(`panel-${def.id}`);
      if (!panel) continue;
      panel.hidden = !state.open.has(def.id);
    }
  }

  function fillChipGroup(host, opts, { multi, name, checkedIds }) {
    host.innerHTML = "";
    for (const opt of opts) {
      const label = document.createElement("label");
      label.className = "stake-chip has-data";
      const checked = checkedIds.has(opt.id) ? "checked" : "";
      const type = multi ? "checkbox" : "radio";
      label.innerHTML = `
        <input type="${type}" name="${name}" value="${opt.id}" ${checked} />
        <span>${opt.label}</span>
      `;
      host.appendChild(label);
    }
  }

  function setupWhenIRaiseFilters() {
    fillChipGroup($("#wirStreetGroup"), wirStreetOpts, {
      multi: false,
      name: "wir-street",
      checkedIds: new Set(["ALL"]),
    });
    fillChipGroup($("#wirPlayersGroup"), wirPlayerOpts, {
      multi: true,
      name: "wir-players",
      checkedIds: new Set(wirPlayerOpts.map((o) => o.id)),
    });
    fillChipGroup($("#wirSizeGroup"), wirSizeOpts, {
      multi: true,
      name: "wir-size",
      checkedIds: new Set(wirSizeOpts.map((o) => o.id)),
    });
    fillChipGroup($("#wirPositionGroup"), wirPositionOpts, {
      multi: true,
      name: "wir-position",
      checkedIds: new Set(wirPositionOpts.map((o) => o.id)),
    });

    const host = $("#whenIRaiseFilters");
    host.addEventListener("change", () => {
      if (state.open.has("when_i_raise")) {
        analyzeWhenIRaise().catch((err) => {
          $("#filterStatus").textContent = `分析失败: ${err.message}`;
          console.error(err);
        });
      }
    });
  }

  function readWhenIRaiseOptions() {
    const streetEl = document.querySelector("#wirStreetGroup input:checked");
    const player_counts = [...document.querySelectorAll("#wirPlayersGroup input:checked")].map(
      (el) => el.value
    );
    const sizes = [...document.querySelectorAll("#wirSizeGroup input:checked")].map(
      (el) => el.value
    );
    const positions = [...document.querySelectorAll("#wirPositionGroup input:checked")].map(
      (el) => el.value
    );
    return {
      street: streetEl ? streetEl.value : "ALL",
      player_counts,
      sizes,
      positions,
    };
  }

  function setupFilter(summary) {
    const filter = summary.filter || {};
    state.filterDefaults = {
      date_from: filter.date_from || "",
      date_to: filter.date_to || "",
      stakes: (filter.stakes_presets || []).map((s) => s.id),
      game_types: (filter.game_types_presets || []).map((g) => g.id),
    };

    const dateFrom = $("#dateFrom");
    const dateTo = $("#dateTo");
    dateFrom.min = filter.date_from || "";
    dateFrom.max = filter.date_to || "";
    dateTo.min = filter.date_from || "";
    dateTo.max = filter.date_to || "";
    dateFrom.value = state.filterDefaults.date_from;
    dateTo.value = state.filterDefaults.date_to;

    const gameHost = $("#gameTypeGroup");
    gameHost.innerHTML = "";
    for (const gt of filter.game_types_presets || []) {
      const label = document.createElement("label");
      label.className = "stake-chip" + (gt.has_data ? " has-data" : "");
      label.innerHTML = `
        <input type="checkbox" value="${gt.id}" checked />
        <span>${gt.label}</span>
        ${gt.has_data ? "" : '<span class="tag">预留</span>'}
      `;
      gameHost.appendChild(label);
    }

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
    for (const input of document.querySelectorAll("#gameTypeGroup input[type=checkbox]")) {
      input.checked = true;
    }
  }

  function readFilter() {
    const stakes = [...document.querySelectorAll("#stakesGroup input[type=checkbox]:checked")]
      .map((el) => el.value);
    const game_types = [...document.querySelectorAll("#gameTypeGroup input[type=checkbox]:checked")]
      .map((el) => el.value);
    return {
      date_from: $("#dateFrom").value || null,
      date_to: $("#dateTo").value || null,
      stakes,
      game_types,
    };
  }

  function applySummary(data) {
    state.summary = data;
    if (data.data_dir) {
      $("#dataDirInput").value = data.data_dir;
      $("#dataDirStatus").textContent = `当前: ${data.data_dir}`;
    }
    if (data.error) {
      $("#summaryText").textContent = `目录无法读取: ${data.error}`;
      setupFilter(data);
      return data;
    }
    const range =
      data.date_range?.start && data.date_range?.end
        ? `${data.date_range.start} → ${data.date_range.end}`
        : "无数据";
    $("#summaryText").textContent =
      `已加载 ${data.hand_count} 手 · ${data.file_count} 个文件 · ${range}`;
    setupFilter(data);
    return data;
  }

  async function loadSummary() {
    const data = await fetchJSON("/api/summary");
    return applySummary(data);
  }

  async function applyDataDir() {
    const path = $("#dataDirInput").value.trim();
    if (!path) {
      $("#dataDirStatus").textContent = "请先填写或浏览选择目录。";
      return;
    }
    const btn = $("#applyDirBtn");
    btn.disabled = true;
    btn.textContent = "加载中…";
    $("#dataDirStatus").textContent = "正在切换数据目录…";
    try {
      const result = await fetchJSON("/api/data-dir", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      });
      if (result.summary) {
        applySummary(result.summary);
      } else {
        $("#dataDirInput").value = result.data_dir || path;
        $("#dataDirStatus").textContent = result.warning
          ? `已切换，但加载失败: ${result.warning}`
          : `已切换到: ${result.data_dir}`;
      }
      state.analyzed = false;
      $("#filterStatus").textContent = "数据目录已更新，请点击「分析」。";
      if (result.summary && result.summary.hand_count >= 0) {
        await analyze();
      }
    } catch (err) {
      $("#dataDirStatus").textContent = `切换失败: ${err.message}`;
      console.error(err);
    } finally {
      btn.disabled = false;
      btn.textContent = "加载";
    }
  }

  async function browseDataDir() {
    const btn = $("#browseDirBtn");
    btn.disabled = true;
    $("#dataDirStatus").textContent = "正在打开文件夹窗口，请看任务栏或桌面弹窗…";
    try {
      const started = await fetchJSON("/api/browse-dir", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initial: $("#dataDirInput").value.trim() || null }),
      });
      if (started.message) {
        $("#dataDirStatus").textContent = started.message;
      }

      const deadline = Date.now() + 10 * 60 * 1000;
      while (Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, 400));
        const status = await fetchJSON("/api/browse-dir/status");
        if (status.status === "pending") continue;
        if (status.status === "cancelled") {
          $("#dataDirStatus").textContent = "已取消选择。";
          return;
        }
        if (status.status === "error") {
          throw new Error(status.error || "未知错误");
        }
        if (status.status === "done" && status.path) {
          $("#dataDirInput").value = status.path;
          $("#dataDirStatus").textContent = `已选择: ${status.path}（点击「加载」生效）`;
          return;
        }
        $("#dataDirStatus").textContent = "未选择目录。";
        return;
      }
      $("#dataDirStatus").textContent = "选择超时。也可直接粘贴路径后点「加载」。";
    } catch (err) {
      $("#dataDirStatus").textContent =
        `浏览失败: ${err.message}（也可直接粘贴路径后点「加载」）`;
      console.error(err);
    } finally {
      btn.disabled = false;
    }
  }

  async function analyzeWhenIRaise() {
    const filter = readFilter();
    const options = readWhenIRaiseOptions();
    const data = await fetchJSON("/api/metrics/when_i_raise", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...filter, options }),
    });
    renderWhenIRaise(data);
  }

  async function analyze() {
    const filter = readFilter();
    if (!filter.game_types.length) {
      $("#filterStatus").textContent = "请至少选择一种游戏类型。";
      return;
    }
    if (!filter.stakes.length) {
      $("#filterStatus").textContent = "请至少选择一个游戏级别。";
      return;
    }

    const btn = $("#analyzeBtn");
    btn.disabled = true;
    btn.textContent = "分析中…";
    $("#filterStatus").textContent = "正在按筛选条件计算…";

    try {
      for (const def of panelDefs) {
        if (!state.open.has(def.id) || !def.live) continue;
        if (def.id === "profit_curve") {
          const data = await fetchJSON("/api/metrics/profit_curve", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(filter),
          });
          renderProfit(data);
        } else if (def.id === "when_i_raise") {
          await analyzeWhenIRaise();
        }
      }

      state.analyzed = true;
      const stakesLabel = filter.stakes.join(", ") || "无";
      const gameTypeLabels = {
        nlh: "普通桌",
        rush: "极速桌",
      };
      const gameLabel =
        filter.game_types.map((id) => gameTypeLabels[id] || id).join(", ") || "无";
      $("#filterStatus").textContent =
        `已分析：${filter.date_from || "?"} ~ ${filter.date_to || "?"} · ${gameLabel} · 级别 ${stakesLabel}`;
    } catch (err) {
      $("#filterStatus").textContent = `分析失败: ${err.message}`;
      console.error(err);
    } finally {
      btn.disabled = false;
      btn.textContent = "分析";
    }
  }

  function renderWhenIRaise(data) {
    const empty = $("#whenIRaiseEmpty");
    const stats = $("#whenIRaiseStats");

    if (!data.spot_count) {
      empty.hidden = false;
      stats.innerHTML = `
        <div class="stat">
          <span class="label">样本数</span>
          <span class="value">0</span>
        </div>
      `;
      return;
    }

    empty.hidden = true;
    const allFold = data.all_fold || {};
    const call = data.call || {};
    const reraise = data.reraise || {};
    stats.innerHTML = `
      <div class="stat">
        <span class="label">样本数</span>
        <span class="value">${data.spot_count}</span>
      </div>
      <div class="stat">
        <span class="label">涉及手数</span>
        <span class="value">${data.hand_count}</span>
      </div>
      <div class="stat">
        <span class="label">All Fold</span>
        <span class="value">${fmtPct(allFold.pct)} <span style="color:var(--muted);font-weight:500;font-size:0.85rem">(${allFold.count || 0})</span></span>
      </div>
      <div class="stat">
        <span class="label">Call</span>
        <span class="value">${fmtPct(call.pct)} <span style="color:var(--muted);font-weight:500;font-size:0.85rem">(${call.count || 0})</span></span>
      </div>
      <div class="stat">
        <span class="label">Reraise</span>
        <span class="value">${fmtPct(reraise.pct)} <span style="color:var(--muted);font-weight:500;font-size:0.85rem">(${reraise.count || 0})</span></span>
      </div>
    `;
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
    const fees = data.total_rake_paid;
    const rakeOnly = data.total_rake_only;
    const jackpot = data.total_jackpot_share;
    stats.innerHTML = `
      <div class="stat">
        <span class="label">手数</span>
        <span class="value">${data.hand_count}</span>
      </div>
      <div class="stat">
        <span class="label">总计盈利（费用前）</span>
        <span class="value ${moneyClass(before)}">${fmtMoney(before)}</span>
      </div>
      <div class="stat">
        <span class="label">总计真实盈利（费用后）</span>
        <span class="value ${moneyClass(after)}">${fmtMoney(after)}</span>
      </div>
      <div class="stat">
        <span class="label">累计费用（Rake+JP）</span>
        <span class="value">${fmtMoney(fees)}</span>
      </div>
      <div class="stat">
        <span class="label">其中 Rake / Jackpot</span>
        <span class="value">${fmtMoney(rakeOnly ?? 0)} / ${fmtMoney(jackpot ?? 0)}</span>
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
            label: "费用前",
            data: data.series.profit_before_rake,
            borderColor: "#c4a35a",
            backgroundColor: "rgba(196, 163, 90, 0.12)",
            ...datasetCommon,
          },
          {
            label: "费用后",
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
    setupWhenIRaiseFilters();
    await loadSummary();
    state.open.add("profit_curve");
    state.open.add("when_i_raise");
    renderToggles();
    syncPanels();

    $("#analyzeBtn").addEventListener("click", () => analyze());
    $("#resetFilterBtn").addEventListener("click", () => {
      resetFilter();
      $("#filterStatus").textContent = "已重置为全部数据，点击「分析」生效。";
    });
    $("#browseDirBtn").addEventListener("click", () => browseDataDir());
    $("#applyDirBtn").addEventListener("click", () => applyDataDir());
    $("#dataDirInput").addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") {
        ev.preventDefault();
        applyDataDir();
      }
    });

    $("#reloadBtn").addEventListener("click", async () => {
      await fetchJSON("/api/reload", { method: "POST" });
      await loadSummary();
      state.analyzed = false;
      $("#filterStatus").textContent = "数据已重新扫描，请再次点击「分析」。";
    });

    await analyze();
  }

  init().catch((err) => {
    $("#summaryText").textContent = `加载失败: ${err.message}`;
    console.error(err);
  });
})();
