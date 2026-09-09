/* ============================================================================
   dashboard.js · the control room
   Pulls /api/overview/, paints KPIs, SVG charts, the 3D floor, the rail and
   the ledger feed, then re-pulls on a cadence. No framework, no build step.
   ========================================================================== */
(() => {
  "use strict";
  const { $, $$, api, charts, counter, money, int, timeAgo, esc, tilt, toast, clamp } = window.RMS;

  let cadence = 12;
  let timer = null;
  let data = null;
  let firstPaint = true;

  /* ── KPI cards ─────────────────────────────────────────────────────── */
  const kpi = ({ label, value, sub, tone = "gold", spark = "", delta = null, action = "", icon = "" }) => `
    <article class="kpi" data-tilt ${action ? `data-goto="${action}" style="cursor:pointer"` : ""}>
      <span class="kpi__glow"></span>
      <div class="kpi__label"><span class="dot dot--${tone}"></span>${esc(label)}${icon ? ` <span class="faint">${esc(icon)}</span>` : ""}</div>
      <div class="kpi__value num" data-kpi-value>${value}</div>
      <div class="kpi__foot">
        ${delta === null ? "" : deltaChip(delta)}
        <span>${esc(sub || "")}</span>
      </div>
      ${spark}
    </article>`;

  const deltaChip = (delta) => {
    const value = Number(delta || 0);
    const cls = value > 0.5 ? "up" : value < -0.5 ? "down" : "flat";
    const arrow = value > 0.5 ? "▲" : value < -0.5 ? "▼" : "▬";
    return `<span class="delta delta--${cls}">${arrow} ${Math.abs(value).toFixed(0)}%</span>`;
  };

  function paintKpis(m) {
    const host = $("[data-role='kpis']");
    if (!host) return;
    const revSeries = (data.series || []).map((row) => row.revenue);
    const tickSeries = (data.series || []).map((row) => row.tickets);
    const health = m.dishes ? clamp(Math.round(((m.dishes - (data.stock?.low?.length || 0)) / m.dishes) * 100), 0, 100) : 0;
    host.innerHTML = [
      kpi({
        label: "Revenue today", tone: "gold", value: money(m.revenue), delta: m.revenue_delta,
        sub: `${m.tickets} paid tickets`, spark: charts.spark(revSeries, { width: 110, height: 38 }),
      }),
      kpi({
        label: "Average ticket", tone: "info", value: money(m.avg_ticket), delta: m.avg_delta,
        sub: `${int(m.covers)} covers seated`, spark: charts.spark(tickSeries, { width: 110, height: 38, color: "#7aa2ff" }),
      }),
      kpi({
        label: "On the rail", tone: m.late_tickets ? "hot" : "good",
        value: `${int(m.open_tickets)}<small>open</small>`,
        sub: `${m.late_tickets} past the ${m.kitchen_minutes}-min lane`, action: "/orders/",
      }),
      kpi({
        label: "Money in play", tone: "warn", value: money(m.running_value),
        sub: "not yet settled", action: "/orders/",
      }),
      kpi({
        label: "Floor", tone: "good", value: `${int(m.tables_seated)}<small>/${m.tables_total}</small>`,
        sub: `tables occupied`,
      }),
      kpi({
        label: "Menu health", tone: health > 80 ? "good" : "warn", value: `${health}<small>% stocked</small>`,
        sub: `${m.dishes_live}/${m.dishes} live · ${data.stock?.without_photo || 0} need a photo`, action: "/studio/",
      }),
    ].join("");
    $$("[data-kpi-value]", host).forEach((node, index) => {
      const raw = node.textContent;
      const numeric = Number(raw.replace(/[^0-9.]/g, ""));
      if (Number.isFinite(numeric) && numeric > 0) {
        const prefix = raw.trim().startsWith("−") ? "−" : "";
        const isMoney = raw.includes(m.currency || "$");
        node.textContent = "";
        counter(node, numeric, { prefix, decimals: isMoney ? 2 : (numeric % 1 === 0 ? 0 : 1) });
      }
    });
    tilt(host);
    host.querySelectorAll("[data-goto]").forEach((node) => {
      node.addEventListener("click", () => { window.location.href = node.dataset.goto; });
    });
  }

  /* ── charts ────────────────────────────────────────────────────────── */
  function paintCharts() {
    const rev = $("[data-role='revenue-chart']");
    if (rev) {
      rev.innerHTML = charts.line(data.series || [], { width: 760, height: 224 });
      const total = (data.series || []).reduce((sum, row) => sum + row.revenue, 0);
      const best = (data.series || []).reduce((a, b) => (b.revenue > (a?.revenue || 0) ? b : a), null);
      const totalNode = $("[data-role='rev-total']");
      if (totalNode) totalNode.textContent = `14d ${money(total, 0)}`;
      const bestNode = $("[data-role='rev-best']");
      if (bestNode && best) bestNode.innerHTML = `<span class="dot dot--gold"></span>best ${esc(best.label)} ${money(best.revenue, 0)}`;
    }

    const donutHost = $("[data-role='mix-donut']");
    const legendHost = $("[data-role='mix-legend']");
    const mix = (data.mix || []).slice(0, 6);
    if (donutHost && legendHost) {
      const totalMix = mix.reduce((sum, row) => sum + row.revenue, 0) || 1;
      donutHost.innerHTML = charts.donut(mix.map((row) => ({ name: row.name, value: row.revenue, color: row.accent })), { size: 138, thickness: 16 });
      legendHost.innerHTML = mix.map((row) => `
        <div class="legend__row">
          <span class="legend__sw" style="background:${row.accent}"></span>
          <span class="clip">${esc(row.icon)} ${esc(row.name)}</span>
          <span class="legend__val">${money(row.revenue, 0)}</span>
        </div>
        <div class="meter" style="grid-column:1/-1"><i class="meter__fill" style="width:${(row.revenue / totalMix * 100).toFixed(1)}%;background:${row.accent}"></i></div>
      `).join("") || `<div class="empty" style="padding:16px"><span class="empty__mark">◍</span>no sales yet</div>`;
    }

    const hourly = $("[data-role='hourly']");
    if (hourly) hourly.innerHTML = charts.bar(data.hourly || [], { width: 900, height: 168 });
  }

  /* ── lists ─────────────────────────────────────────────────────────── */
  function paintLists() {
    const top = $("[data-role='top']");
    if (top) {
      top.innerHTML = (data.top || []).map((row, index) => `
        <div class="rowline" data-open-dish="${row.id}">
          <span class="rank">${String(index + 1).padStart(2, "0")}</span>
          <span class="row" style="gap:10px;min-width:0">
            ${row.photo
              ? `<img class="rowline__thumb" src="${row.photo}" alt="" loading="lazy">`
              : `<span class="rowline__thumb" style="display:grid;place-items:center;background:radial-gradient(120% 100% at 50% 10%,#22262e,#0d0f12);font-family:var(--font-display);color:rgba(255,255,255,.35)">${esc(row.name[0] || "◆")}</span>`}
            <span style="min-width:0">
              <span style="display:block;font-size:13px;font-weight:500" class="clip">${esc(row.name)}</span>
              <span class="tiny">${esc(row.category)} · ${row.portions} portions · ${row.tickets} tickets</span>
            </span>
          </span>
          <span class="num small" style="color:var(--gold-soft)">${money(row.revenue, 0)}</span>
        </div>`).join("")
        || `<div class="empty"><span class="empty__mark">◍</span>nothing sold yet today</div>`;
      $$("[data-open-dish]", top).forEach((node) => node.addEventListener("click", () => {
        window.location.href = `/studio/?item=${node.dataset.openDish}`;
      }));
    }

    const stock = $("[data-role='stock']");
    if (stock) {
      const rows = data.stock || {};
      stock.innerHTML = (rows.low || []).map((item) => `
        <div class="rowline" data-restock="${item.id}" data-need="${item.needed}" title="Click to top back to par (${item.par})">
          <span class="dot dot--${item.state === "out" ? "bad" : "warn"}"></span>
          <span style="min-width:0">
            <span style="display:block;font-size:13px" class="clip">${esc(item.name)}</span>
            <span class="tiny">${esc(item.category)} · ${item.stock}/${item.par} ${esc(item.unit)}</span>
            <span class="meter" style="margin-top:5px"><i class="meter__fill" style="width:${clamp((item.stock / Math.max(item.par, 1)) * 100, 3, 100)}%;background:${item.state === "out" ? "var(--bad)" : "var(--warn)"}"></i></span>
          </span>
          <span class="btn btn--xs btn--ghost" data-stop>+${item.needed}</span>
        </div>`).join("") || `<div class="empty"><span class="empty__mark" style="color:var(--good)">✓</span>every dish is above its reorder point</div>`;
      $$("[data-restock]", stock).forEach((node) => node.addEventListener("click", async (event) => {
        event.stopPropagation();
        const need = Number(node.dataset.need) || 6;
        const res = await api("/api/menu/restock/", { method: "POST", body: { id: Number(node.dataset.restock), quantity: need } });
        if (res.ok) { toast(res.notice, { tone: "good", title: "Stock moved" }); load(); }
      }));
    }

    const tickets = $("[data-role='tickets']");
    if (tickets) {
      tickets.innerHTML = (data.tickets || []).map((row) => `
        <div class="rowline" data-ticket="${row.id}">
          <span class="mono small" style="color:var(--gold-soft)">${esc(row.number)}</span>
          <span style="min-width:0">
            <span style="display:block;font-size:13px" class="clip">${esc(row.guest)} · ${esc(row.table || row.channel_label)}</span>
            <span class="tiny">${row.items} dishes · ${esc(row.status_label)}${row.late ? ' · <b style="color:var(--bad)">late</b>' : ""}</span>
          </span>
          <span class="row" style="gap:6px">
            <span class="num small">${money(row.total)}</span>
            <button class="btn btn--xs btn--gold" data-advance="${row.id}">advance</button>
          </span>
        </div>`).join("")
        || `<div class="empty"><span class="empty__mark">◍</span>rail is clear — beautiful</div>`;
      $$("[data-advance]", tickets).forEach((node) => node.addEventListener("click", async (event) => {
        event.stopPropagation();
        const res = await api("/api/orders/action/", { method: "POST", body: { id: Number(node.dataset.advance), action: "advance" } });
        if (res.ok) { toast(res.notice, { tone: "good" }); load(); }
      }));
      $$("[data-ticket]", tickets).forEach((node) => node.addEventListener("click", () => {
        window.location.href = `/orders/?ticket=${node.dataset.ticket}`;
      }));
    }

    const feed = $("[data-role='activity']");
    if (feed) {
      feed.innerHTML = (data.activity || []).map((row) => `
        <div class="feed__item">
          <span class="feed__dot" style="background:var(--${levelTone(row.level)});box-shadow:0 0 0 3px color-mix(in srgb, var(--${levelTone(row.level)}) 18%, transparent)"></span>
          <span>
            <span style="display:block">${esc(row.message)}</span>
            <span class="feed__time">${esc(row.actor)} · ${esc(row.ago)} · <span class="mono">${esc(row.verb)}</span></span>
          </span>
        </div>`).join("") || `<div class="empty">ledger is empty</div>`;
    }
  }

  const levelTone = (level) => ({ good: "good", warn: "warn", bad: "bad" }[level] || "info");

  /* ── floor ─────────────────────────────────────────────────────────── */
  function paintFloor() {
    if (window.RMS?.floor) window.RMS.floor.set(data.floor || []);
    window.__floorData = data.floor || [];
  }

  /* ── header stats ──────────────────────────────────────────────────── */
  function paintMeta() {
    const updated = $("[data-role='updated']");
    if (updated) updated.textContent = `updated ${timeAgo(data.generated_at)} · ${data.metrics.tickets} paid`;
    const latency = $("[data-role='latency']");
    if (latency && data.__ms !== undefined) latency.textContent = `${data.__ms}ms`;
    const cycle = $("[data-role='cycle']");
    if (cycle) cycle.textContent = cadence ? `${cadence}s` : "manual";
  }

  /* ── orchestration ─────────────────────────────────────────────────── */
  async function load() {
    const res = await api("/api/overview/", { silent: !firstPaint });
    if (!res || res.ok === false) { firstPaint = false; return; }
    data = res;
    paintKpis(res.metrics || {});
    paintCharts();
    paintLists();
    paintFloor();
    paintMeta();
    firstPaint = false;
    document.dispatchEvent(new CustomEvent("rms:overview", { detail: res }));
  }

  function schedule() {
    clearTimeout(timer);
    if (!cadence) return;
    timer = setTimeout(async () => { await load(); schedule(); }, cadence * 1000);
  }

  const start = async () => {
    await load();
    schedule();
  };

  window.RMS.boot(() => {
    start();

    $$("[data-cadence]").forEach((node) => node.addEventListener("click", () => {
      $$("[data-cadence]").forEach((n) => n.classList.remove("is-active"));
      node.classList.add("is-active");
      cadence = Number(node.dataset.cadence);
      schedule();
      paintMeta();
    }));

    document.querySelector('[data-action="refresh"]')?.addEventListener("click", async (event) => {
      const btn = event.currentTarget;
      btn.classList.add("is-busy");
      await load();
      setTimeout(() => btn.classList.remove("is-busy"), 420);
    });

    document.querySelector('[data-action="floor-reset"]')?.addEventListener("click", () => {
      (window.RMS.floor?.all() || []).forEach((floor) => { floor.targetYaw = -0.42; });
    });

    // keyboard: R refresh, A add dish, O orders, K kitchen
    addEventListener("keydown", (event) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) return;
      const k = event.key.toLowerCase();
      if (k === "r") load();
      if (k === "a") window.location.href = "/studio/";
      if (k === "o") window.location.href = "/orders/";
      if (k === "k") window.location.href = "/kitchen/";
    });

    window.addEventListener("rms:table", (event) => {
      const order = event.detail?.order;
      toast(order ? `${event.detail.label} · ${order.number} · ${order.age}` : `${event.detail?.label || "Table"} is free`,
        { tone: order ? "info" : "good", title: "Floor" });
    });
  });
})();
