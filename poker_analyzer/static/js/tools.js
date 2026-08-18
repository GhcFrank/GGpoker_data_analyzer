(() => {
  const RANKS = "AKQJT98765432".split("");
  const RANKS_FULL = "AKQJT98765432".split("");
  const SUITS = [
    { id: "s", sym: "♠", red: false },
    { id: "h", sym: "♥", red: true },
    { id: "d", sym: "♦", red: true },
    { id: "c", sym: "♣", red: false },
  ];

  const BATCH_SIZE = 8000;
  const TICK_MS = 400;
  const MAX_SAMPLES = 10_000_000;

  const eqState = {
    hands: { 1: [null, null], 2: [null, null] },
    board: [],
    running: false,
    inFlight: false,
    timer: null,
    totalWins1: 0,
    totalTies: 0,
    totalSamples: 0,
    combos: { p1: 0, p2: 0 },
  };

  const picker = {
    target: null,
    temp: [],
  };

  function $(sel) {
    return document.querySelector(sel);
  }

  function fmtPct(n) {
    return `${Number(n).toFixed(2)}%`;
  }

  function fmtNum(n) {
    return Number(n).toLocaleString();
  }

  function cardId(rank, suit) {
    return `${rank}${suit}`;
  }

  function cardHtml(id, { mini } = {}) {
    if (!id) return `<span class="playing-card empty${mini ? " mini" : ""}">+</span>`;
    const rank = id[0];
    const suitId = id[1];
    const suit = SUITS.find((s) => s.id === suitId);
    const cls = `playing-card${suit.red ? " red" : ""}${mini ? " mini" : ""}`;
    return `<span class="${cls}"><span class="pc-rank">${rank}</span><span class="pc-suit">${suit.sym}</span></span>`;
  }

  function usedCards({ excludeSide, excludeBoard } = {}) {
    const used = new Set();
    for (const side of [1, 2]) {
      if (excludeSide === side) continue;
      for (const c of eqState.hands[side]) if (c) used.add(c);
    }
    if (!excludeBoard) {
      for (const c of eqState.board) if (c) used.add(c);
    }
    return used;
  }

  function calcMdf(betPct) {
    const frac = Math.max(0, Number(betPct) || 0) / 100;
    if (frac === 0) return 100;
    return 100 / (1 + frac);
  }

  function updateMdf() {
    const betPct = Number($("#mdfBetPct").value) || 0;
    const mdf = calcMdf(betPct);
    $("#mdfValue").textContent = fmtPct(mdf);
    const pot = 100;
    const bet = (pot * betPct) / 100;
    $("#mdfExplain").textContent =
      `底池 ${pot}，对手下注 ${bet.toFixed(betPct % 1 ? 1 : 0)}（${betPct}%）→ 需防守 ${mdf.toFixed(1)}% 的范围。`;
  }

  function cellLabel(row, col) {
    const r1 = RANKS[row];
    const r2 = RANKS[col];
    if (row === col) return `${r1}${r2}`;
    if (row < col) return `${r1}${r2}s`;
    return `${r2}${r1}o`;
  }

  function parseRangeTokens(text) {
    const set = new Set();
    const raw = (text || "").trim();
    if (!raw) return set;
    for (const part of raw.split(",")) {
      const t = part.trim();
      if (!t) continue;
      const ranks = t.replace(/[so]$/i, "").toUpperCase();
      const suffix = t.match(/[so]$/i);
      set.add(ranks + (suffix ? suffix[0].toLowerCase() : ""));
    }
    return set;
  }

  function rangeToText(tokens) {
    if (!tokens.size) return "";
    const order = [];
    for (let r = 0; r < 13; r++) {
      for (let c = 0; c < 13; c++) {
        const lbl = cellLabel(r, c);
        if (tokens.has(lbl)) order.push(lbl);
      }
    }
    return order.join(",");
  }

  function getSideMode(side) {
    const el = document.querySelector(`input[name="eq-mode-${side}"]:checked`);
    return el ? el.value : "hand";
  }

  function getSideInput(side) {
    return $(`#eqPlayer${side}`);
  }

  function getSideMatrix(side) {
    return $(`#eqMatrix${side}`);
  }

  function syncSideModeUi(side) {
    const mode = getSideMode(side);
    const handUi = $(`#eqHandUi${side}`);
    const rangeUi = $(`#eqRangeUi${side}`);
    if (handUi) handUi.hidden = mode !== "hand";
    if (rangeUi) rangeUi.hidden = mode !== "range";
    if (mode === "range") syncMatrixFromInput(side);
    else renderHandSlots(side);
  }

  function renderHandSlots(side) {
    const host = $(`#eqHandSlots${side}`);
    if (!host) return;
    const cards = eqState.hands[side];
    host.innerHTML = cards.map((c, i) => {
      const label = c ? cardHtml(c, { mini: true }) : `<span class="playing-card empty mini">+</span>`;
      return `<button type="button" class="card-slot-btn" data-side="${side}" data-slot="${i}">${label}</button>`;
    }).join("");
  }

  function renderBoardDisplay() {
    const host = $("#eqBoardDisplay");
    if (!host) return;
    if (!eqState.board.length) {
      host.innerHTML = `<span class="eq-board-empty">翻前（无公共牌）</span>`;
      return;
    }
    host.innerHTML = eqState.board.map((c) => cardHtml(c, { mini: true })).join("");
  }

  function handToText(side) {
    const cards = eqState.hands[side].filter(Boolean);
    return cards.length === 2 ? cards.join(" ") : "";
  }

  function boardToText() {
    return eqState.board.filter(Boolean).join(" ");
  }

  function getPlayerText(side) {
    if (getSideMode(side) === "hand") return handToText(side);
    return getSideInput(side).value.trim();
  }

  function validateEquityInputs() {
    const p1 = getPlayerText(1);
    const p2 = getPlayerText(2);
    if (!p1 || !p2) {
      return { ok: false, msg: "请为双方选手牌或范围。" };
    }
    if (getSideMode(1) === "hand" && eqState.hands[1].filter(Boolean).length < 2) {
      return { ok: false, msg: "玩家 1 需选择两张手牌。" };
    }
    if (getSideMode(2) === "hand" && eqState.hands[2].filter(Boolean).length < 2) {
      return { ok: false, msg: "玩家 2 需选择两张手牌。" };
    }
    return { ok: true, p1, p2 };
  }

  function buildMatrix(host, side) {
    host.innerHTML = "";
    const table = document.createElement("table");
    table.className = "hand-matrix-table";
    const head = document.createElement("tr");
    head.innerHTML = `<th></th>${RANKS.map((r) => `<th>${r}</th>`).join("")}`;
    table.appendChild(head);
    for (let r = 0; r < 13; r++) {
      const tr = document.createElement("tr");
      tr.innerHTML = `<th>${RANKS[r]}</th>`;
      for (let c = 0; c < 13; c++) {
        const td = document.createElement("td");
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "hand-matrix-cell";
        btn.dataset.label = cellLabel(r, c);
        btn.textContent = cellLabel(r, c);
        btn.addEventListener("click", () => onMatrixClick(side, btn.dataset.label));
        td.appendChild(btn);
        tr.appendChild(td);
      }
      table.appendChild(tr);
    }
    host.appendChild(table);
  }

  function syncMatrixFromInput(side) {
    const matrix = getSideMatrix(side);
    const input = getSideInput(side);
    if (!matrix || !input) return;
    const tokens = parseRangeTokens(input.value);
    matrix.querySelectorAll(".hand-matrix-cell").forEach((btn) => {
      btn.classList.toggle("on", tokens.has(btn.dataset.label));
    });
  }

  function onMatrixClick(side, label) {
    const input = getSideInput(side);
    const tokens = parseRangeTokens(input.value);
    if (tokens.has(label)) tokens.delete(label);
    else tokens.add(label);
    input.value = rangeToText(tokens);
    syncMatrixFromInput(side);
    onEquityInputChanged();
  }

  function setupEquitySide(side) {
    const input = getSideInput(side);
    const matrixHost = getSideMatrix(side);
    buildMatrix(matrixHost, side);
    document.querySelectorAll(`input[name="eq-mode-${side}"]`).forEach((el) => {
      el.addEventListener("change", () => {
        syncSideModeUi(side);
        onEquityInputChanged();
      });
    });
    input.addEventListener("input", () => {
      syncMatrixFromInput(side);
      onEquityInputChanged();
    });
    syncSideModeUi(side);
  }

  function buildCardPickerGrid() {
    const grid = $("#cardPickerGrid");
    grid.innerHTML = "";
    const table = document.createElement("table");
    table.className = "card-picker-table";
    const head = document.createElement("tr");
    head.innerHTML = `<th></th>${RANKS_FULL.map((r) => `<th>${r}</th>`).join("")}`;
    table.appendChild(head);
    for (const suit of SUITS) {
      const tr = document.createElement("tr");
      tr.innerHTML = `<th class="${suit.red ? "red" : ""}">${suit.sym}</th>`;
      for (const rank of RANKS_FULL) {
        const td = document.createElement("td");
        const id = cardId(rank, suit.id);
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = `picker-card${suit.red ? " red" : ""}`;
        btn.dataset.card = id;
        btn.innerHTML = `<span>${rank}</span><span>${suit.sym}</span>`;
        btn.addEventListener("click", () => onPickerCardClick(id));
        td.appendChild(btn);
        tr.appendChild(td);
      }
      table.appendChild(tr);
    }
    grid.appendChild(table);
  }

  function refreshPickerGrid() {
    const used = usedCards({
      excludeSide: picker.target?.type === "hand" ? picker.target.side : null,
      excludeBoard: picker.target?.type === "board",
    });
    const selected = new Set(picker.temp);
    $("#cardPickerGrid").querySelectorAll(".picker-card").forEach((btn) => {
      const id = btn.dataset.card;
      const blocked = used.has(id);
      const on = selected.has(id);
      btn.disabled = blocked && !on;
      btn.classList.toggle("on", on);
      btn.classList.toggle("blocked", blocked && !on);
    });
  }

  function openPicker(target) {
    picker.target = target;
    if (target.type === "hand") {
      picker.temp = eqState.hands[target.side].filter(Boolean).slice();
      $("#cardPickerTitle").textContent = `玩家 ${target.side} 选手牌`;
      $("#cardPickerHint").textContent = "点击选择两张手牌（含花色），选满后自动确认";
      $("#cardPickerFoot").hidden = true;
    } else {
      picker.temp = eqState.board.slice();
      $("#cardPickerTitle").textContent = "选公共牌";
      $("#cardPickerHint").textContent = "点击切换公共牌，最多 5 张，点「完成」确认";
      $("#cardPickerFoot").hidden = false;
    }
    refreshPickerGrid();
    $("#cardPickerOverlay").hidden = false;
  }

  function closePicker() {
    $("#cardPickerOverlay").hidden = true;
    picker.target = null;
    picker.temp = [];
  }

  function applyPicker() {
    if (!picker.target) return;
    if (picker.target.type === "hand") {
      const side = picker.target.side;
      eqState.hands[side] = [picker.temp[0] || null, picker.temp[1] || null];
      renderHandSlots(side);
    } else {
      eqState.board = picker.temp.slice(0, 5);
      renderBoardDisplay();
    }
    closePicker();
    onEquityInputChanged();
  }

  function onPickerCardClick(id) {
    const idx = picker.temp.indexOf(id);
    if (picker.target?.type === "hand") {
      if (idx >= 0) {
        picker.temp.splice(idx, 1);
      } else if (picker.temp.length < 2) {
        picker.temp.push(id);
      } else {
        picker.temp[1] = id;
      }
      refreshPickerGrid();
      if (picker.temp.length === 2) applyPicker();
      return;
    }
    if (idx >= 0) picker.temp.splice(idx, 1);
    else if (picker.temp.length < 5) picker.temp.push(id);
    refreshPickerGrid();
  }

  async function fetchJSON(url, options) {
    const res = await fetch(url, options);
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const payload = await res.json();
        detail = payload.detail || JSON.stringify(payload);
      } catch {
        /* ignore */
      }
      throw new Error(detail || res.statusText);
    }
    return res.json();
  }

  function renderEquityFromTotals() {
    const n = eqState.totalSamples;
    const result = $("#eqResult");
    if (!n) {
      result.hidden = true;
      return;
    }
    const eq1 = ((eqState.totalWins1 + 0.5 * eqState.totalTies) / n) * 100;
    const tie = (eqState.totalTies / n) * 100;
    const eq2 = 100 - eq1;
    const p1w = eq1 - tie / 2;
    const p2w = eq2 - tie / 2;

    $("#eqPct1").textContent = fmtPct(eq1);
    $("#eqPct2").textContent = fmtPct(eq2);
    $("#eqPctTie").textContent = fmtPct(tie);
    $("#eqBarP1").style.width = `${p1w}%`;
    $("#eqBarTie").style.width = `${tie}%`;
    $("#eqBarP2").style.width = `${p2w}%`;

    const board = eqState.board;
    const boardNote = board.length
      ? `公共牌 ${board.join(" ")}，剩余 ${5 - board.length} 张由模拟发出`
      : "翻前：随机发出 5 张公共牌";
    const limitNote = n >= MAX_SAMPLES ? " · 已达 1000 万次上限" : "";
    $("#eqMeta").textContent =
      `${boardNote} · 玩家1 ${eqState.combos.p1} 组合 vs 玩家2 ${eqState.combos.p2} 组合 · 已模拟 ${fmtNum(n)} 次${limitNote}`;
    result.hidden = false;
  }

  function updateRunStatus(msg, isError) {
    const status = $("#eqStatus");
    status.hidden = !msg;
    status.textContent = msg || "";
    status.className = "tool-status" + (isError ? " error" : "");
  }

  function updateCalcButton() {
    const btn = $("#eqCalcBtn");
    if (!btn) return;
    if (eqState.running) {
      btn.textContent = "暂停模拟";
      btn.classList.add("is-running");
    } else {
      btn.textContent = eqState.totalSamples ? "继续模拟" : "开始模拟";
      btn.classList.remove("is-running");
    }
  }

  function resetEquityTotals() {
    eqState.totalWins1 = 0;
    eqState.totalTies = 0;
    eqState.totalSamples = 0;
    eqState.combos = { p1: 0, p2: 0 };
    renderEquityFromTotals();
  }

  function onEquityInputChanged() {
    if (eqState.running) pauseEquity();
    resetEquityTotals();
    updateRunStatus("");
  }

  async function runBatch() {
    if (!eqState.running || eqState.inFlight) return;
    if (eqState.totalSamples >= MAX_SAMPLES) {
      pauseEquity();
      updateRunStatus("已达 1000 万次模拟上限，已自动暂停。");
      return;
    }

    const v = validateEquityInputs();
    if (!v.ok) {
      pauseEquity();
      updateRunStatus(v.msg, true);
      return;
    }

    const batch = Math.min(BATCH_SIZE, MAX_SAMPLES - eqState.totalSamples);
    eqState.inFlight = true;
    updateRunStatus(
      `模拟中… 已 ${fmtNum(eqState.totalSamples)} 次` +
        (eqState.totalSamples ? "" : "（首批结果约 0.5 秒内出现）")
    );

    try {
      const data = await fetchJSON("/api/tools/equity", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          player1: v.p1,
          player2: v.p2,
          board: boardToText(),
          samples: batch,
        }),
      });

      eqState.totalWins1 += data.wins1;
      eqState.totalTies += data.ties;
      eqState.totalSamples += data.samples;
      eqState.combos.p1 = data.player1_combos;
      eqState.combos.p2 = data.player2_combos;
      renderEquityFromTotals();

      if (eqState.totalSamples >= MAX_SAMPLES) {
        pauseEquity();
        updateRunStatus("已达 1000 万次模拟上限，已自动暂停。");
      } else if (eqState.running) {
        updateRunStatus(`模拟中… 已 ${fmtNum(eqState.totalSamples)} 次`);
      }
    } catch (err) {
      pauseEquity();
      updateRunStatus(`计算失败: ${err.message}`, true);
    } finally {
      eqState.inFlight = false;
    }
  }

  function startEquity() {
    const v = validateEquityInputs();
    if (!v.ok) {
      updateRunStatus(v.msg, true);
      return;
    }
    eqState.running = true;
    updateCalcButton();
    runBatch();
    if (!eqState.timer) {
      eqState.timer = setInterval(() => runBatch(), TICK_MS);
    }
  }

  function pauseEquity() {
    eqState.running = false;
    if (eqState.timer) {
      clearInterval(eqState.timer);
      eqState.timer = null;
    }
    updateCalcButton();
  }

  function toggleEquity() {
    if (eqState.running) pauseEquity();
    else startEquity();
  }

  function swapPlayers() {
    const h1 = eqState.hands[1].slice();
    const h2 = eqState.hands[2].slice();
    eqState.hands[1] = h2;
    eqState.hands[2] = h1;
    renderHandSlots(1);
    renderHandSlots(2);

    const a = getSideInput(1);
    const b = getSideInput(2);
    const tmp = a.value;
    a.value = b.value;
    b.value = tmp;

    const m1 = getSideMode(1);
    const m2 = getSideMode(2);
    document.querySelector(`input[name="eq-mode-1"][value="${m2}"]`).checked = true;
    document.querySelector(`input[name="eq-mode-2"][value="${m1}"]`).checked = true;
    syncSideModeUi(1);
    syncSideModeUi(2);
    onEquityInputChanged();
  }

  function clearEquity() {
    pauseEquity();
    eqState.hands = { 1: [null, null], 2: [null, null] };
    eqState.board = [];
    getSideInput(1).value = "";
    getSideInput(2).value = "";
    renderHandSlots(1);
    renderHandSlots(2);
    renderBoardDisplay();
    syncMatrixFromInput(1);
    syncMatrixFromInput(2);
    resetEquityTotals();
    updateRunStatus("");
    updateCalcButton();
  }

  function initTools() {
    const mdfInput = $("#mdfBetPct");
    if (!mdfInput) return;

    mdfInput.addEventListener("input", updateMdf);
    $("#mdfPresets").addEventListener("click", (ev) => {
      const btn = ev.target.closest("[data-pct]");
      if (!btn) return;
      mdfInput.value = btn.dataset.pct;
      updateMdf();
    });
    updateMdf();

    buildCardPickerGrid();
    renderBoardDisplay();
    renderHandSlots(1);
    renderHandSlots(2);
    setupEquitySide(1);
    setupEquitySide(2);

    $("#eqCalcBtn").addEventListener("click", () => toggleEquity());
    $("#eqSwapBtn").addEventListener("click", swapPlayers);
    $("#eqClearBtn").addEventListener("click", clearEquity);

    document.querySelectorAll("[data-pick-hand]").forEach((btn) => {
      btn.addEventListener("click", () => {
        openPicker({ type: "hand", side: Number(btn.dataset.pickHand) });
      });
    });
    $("#eqPickBoard").addEventListener("click", () => openPicker({ type: "board" }));

    document.addEventListener("click", (ev) => {
      const slotBtn = ev.target.closest(".card-slot-btn");
      if (slotBtn) {
        openPicker({ type: "hand", side: Number(slotBtn.dataset.side) });
      }
    });

    $("#cardPickerClose").addEventListener("click", closePicker);
    $("#cardPickerOverlay").addEventListener("click", (ev) => {
      if (ev.target.id === "cardPickerOverlay") closePicker();
    });
    $("#cardPickerClear").addEventListener("click", () => {
      picker.temp = [];
      refreshPickerGrid();
    });
    $("#cardPickerDone").addEventListener("click", applyPicker);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initTools);
  } else {
    initTools();
  }
})();
