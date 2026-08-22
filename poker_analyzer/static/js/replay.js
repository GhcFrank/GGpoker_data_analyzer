(() => {
  const SUIT = { s: "♠", h: "♥", d: "♦", c: "♣" };
  const LAYOUT_POS_6 = { UTG: 0, HJ: 1, CO: 2, BTN: 3, SB: 4, BB: 5 };
  const LAYOUT_POS_9 = {
    UTG: 0, UTG1: 1, UTG2: 2, LJ: 3, HJ: 4, CO: 5, BTN: 6, SB: 7, BB: 8,
  };
  const LAYOUT_KEYS_6 = ["UTG", "HJ", "CO", "BTN", "SB", "BB"];
  const LAYOUT_KEYS_9 = ["UTG", "UTG1", "UTG2", "LJ", "HJ", "CO", "BTN", "SB", "BB"];

  const state = {
    open: false,
    source: "",
    getContext: null,
    index: 0,
    total: 0,
    hand: null,
    frame: 0,
    req: 0,
  };

  const $ = (sel) => document.querySelector(sel);

  function cardHtml(code) {
    if (!code || code.length < 2) return `<span class="pcard back">?</span>`;
    const rank = code.slice(0, -1).toUpperCase();
    const suitKey = code.slice(-1).toLowerCase();
    const suit = SUIT[suitKey] || suitKey;
    const red = suitKey === "h" || suitKey === "d" ? " red" : "";
    return `<span class="pcard${red}">${rank}<small>${suit}</small></span>`;
  }

  function holeHtml(player, frame) {
    const folded = (frame.folded || []).includes(player.name);
    if (player.cards && player.cards.length >= 2) {
      return player.cards.map(cardHtml).join("");
    }
    if (folded) return "";
    return `<span class="pcard back"></span><span class="pcard back"></span>`;
  }

  function layoutPosMap(hand) {
    return hand && hand.table_format === "9max" ? LAYOUT_POS_9 : LAYOUT_POS_6;
  }

  function layoutKeys(hand) {
    return hand && hand.table_format === "9max" ? LAYOUT_KEYS_9 : LAYOUT_KEYS_6;
  }

  function layoutClass(player, used, hand) {
    let key = player.layout || "";
    if (key && !used.has(key)) {
      used.add(key);
      return `s-${key}`;
    }
    const leftovers = layoutKeys(hand).filter((p) => !used.has(p));
    key = leftovers[0] || "other";
    used.add(key);
    return `s-${key}`;
  }

  function sortPlayers(players, hand) {
    const layoutPos = layoutPosMap(hand);
    return [...players].sort((a, b) => {
      const pa = layoutPos[a.layout] ?? 90 + (a.seat || 0);
      const pb = layoutPos[b.layout] ?? 90 + (b.seat || 0);
      return pa - pb;
    });
  }

  function renderFrame() {
    const hand = state.hand;
    const stage = $("#replayStage");
    const frames = (hand && hand.frames) || [];
    if (!hand || !frames.length) {
      stage.innerHTML = `<div class="replay-empty">当前条件下没有符合的手牌。</div>`;
      $("#replayCaption").textContent = "";
      $("#replayStepLabel").textContent = "—";
      $("#replayPrevFrame").hidden = true;
      $("#replayNextFrame").hidden = true;
      return;
    }
    const i = Math.max(0, Math.min(state.frame, frames.length - 1));
    state.frame = i;
    const frame = frames[i];
    const used = new Set();
    const seats = sortPlayers(hand.players || [], hand)
      .map((p) => {
        const front = (frame.front_bb || {})[p.name] || 0;
        const folded = (frame.folded || []).includes(p.name);
        const active = frame.actor === p.name;
        const cls = [
          "replay-seat",
          layoutClass(p, used, hand),
          folded ? "is-folded" : "",
          active ? "is-active" : "",
        ]
          .filter(Boolean)
          .join(" ");
        const nameCls = p.is_hero ? "replay-seat-name is-hero" : "replay-seat-name";
        const label = p.is_hero
          ? `${p.position || p.name} · Hero`
          : p.position || p.name;
        const frontText = front > 0 ? `${front}bb` : "";
        return `
          <div class="${cls}">
            <div class="replay-seat-card">
              <div class="${nameCls}">${label}</div>
              <div class="replay-hole">${holeHtml(p, frame)}</div>
            </div>
            <div class="replay-front">${frontText}</div>
          </div>`;
      })
      .join("");
    const board = (frame.board || []).map(cardHtml).join("");
    const tableCls = hand.table_format === "9max" ? "replay-table is-9max" : "replay-table";
    stage.innerHTML = `
      <div class="${tableCls}">
        <div class="replay-felt"></div>
        <div class="replay-pot">
          <span class="pot-label">底池</span>
          <span class="pot-value">${frame.pot_bb || 0}bb</span>
          <div class="replay-board">${board}</div>
        </div>
        ${seats}
      </div>`;
    $("#replayCaption").textContent = frame.caption || "";
    $("#replayStepLabel").textContent = `${i + 1} / ${frames.length}`;
    $("#replayPrevFrame").hidden = i <= 0;
    $("#replayNextFrame").hidden = i >= frames.length - 1;
  }

  function renderChrome() {
    const total = state.total;
    const index = state.index;
    $("#replayPage").textContent = total ? `${index + 1}/${total}` : "0/0";
    $("#replayPrevHand").hidden = !total || index <= 0;
    $("#replayNextHand").hidden = !total || index >= total - 1;
    const hand = state.hand;
    $("#replayMeta").textContent = hand
      ? `${hand.datetime || ""} · ${hand.stakes || ""} · #${hand.hand_id || ""}`
      : "";
  }

  async function loadHand(index) {
    if (!state.getContext) return;
    const req = ++state.req;
    const ctx = state.getContext();
    $("#replayStage").innerHTML = `<div class="replay-loading">加载中…</div>`;
    $("#replayCaption").textContent = "";
    try {
      const res = await fetch("/api/replay/hand", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...ctx.filter,
          source: state.source,
          index,
          options: ctx.options,
        }),
      });
      const data = await res.json();
      if (req !== state.req) return;
      if (!res.ok) throw new Error(data.detail || res.statusText);
      state.index = data.index || 0;
      state.total = data.total || 0;
      state.hand = data.hand;
      state.frame = 0;
      renderChrome();
      renderFrame();
    } catch (err) {
      if (req !== state.req) return;
      $("#replayStage").innerHTML = `<div class="replay-empty">加载失败: ${err.message}</div>`;
      console.error(err);
    }
  }

  function setFrame(next) {
    const frames = (state.hand && state.hand.frames) || [];
    if (!frames.length) return;
    const i = Math.max(0, Math.min(next, frames.length - 1));
    if (i === state.frame) return;
    state.frame = i;
    renderFrame();
  }

  function close() {
    state.open = false;
    $("#replayOverlay").hidden = true;
  }

  function open(source, getContext) {
    state.open = true;
    state.source = source;
    state.getContext = getContext;
    state.index = 0;
    state.hand = null;
    state.frame = 0;
    $("#replayOverlay").hidden = false;
    loadHand(0);
  }

  function bind() {
    const overlay = $("#replayOverlay");
    if (!overlay) return;
    $("#replayClose").addEventListener("click", close);
    overlay.addEventListener("click", (ev) => {
      if (ev.target === overlay) close();
    });
    $("#replayPrevHand").addEventListener("click", () => {
      if (state.index > 0) loadHand(state.index - 1);
    });
    $("#replayNextHand").addEventListener("click", () => {
      if (state.index + 1 < state.total) loadHand(state.index + 1);
    });
    $("#replayPrevFrame").addEventListener("click", () => setFrame(state.frame - 1));
    $("#replayNextFrame").addEventListener("click", () => setFrame(state.frame + 1));
    document.addEventListener("keydown", (ev) => {
      if (!state.open) return;
      if (ev.key === "Escape") {
        close();
        return;
      }
      if (ev.key === "ArrowLeft") {
        ev.preventDefault();
        setFrame(state.frame - 1);
      } else if (ev.key === "ArrowRight") {
        ev.preventDefault();
        setFrame(state.frame + 1);
      }
    });
  }

  bind();
  window.PokerReplay = { open, close };
})();
