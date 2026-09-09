/* ============================================================================
   orders.js · the four-lane ticket board + staff ticket composer
   ========================================================================== */
(() => {
  "use strict";
  const { $, $$, api, esc, money, toast, debounce, counter } = window.RMS;

  const seedNode = document.querySelector('[data-role="orders-seed"]');
  const seed = (() => { try { return JSON.parse(seedNode?.textContent || "{}"); } catch { return {}; } })();
  const LANES = [
    { key: "new", title: "Order in", tone: "info", hint: "not yet fired" },
    { key: "fire", title: "Firing", tone: "hot", hint: "on the fire" },
    { key: "ready", title: "Ready", tone: "good", hint: "at the pass" },
    { key: "served", title: "Settling", tone: "warn", hint: "served, awaiting payment" },
  ];
  let orders = seed.orders || [];
  let lines = [];          // composer lines
  let dishes = [];
  let tables = seed.floor || [];

  /* ── board ─────────────────────────────────────────────────────────── */
  function render() {
    const board = $("[data-board]");
    const groups = { new: [], fire: [], ready: [], served: [] };
    orders.forEach((order) => { if (groups[order.status]) groups[order.status].push(order); });
    board.innerHTML = LANES.map((lane) => `
      <section class="lane" data-lane="${lane.key}">
        <header class="lane__head">
          <span class="dot dot--${lane.tone}"></span>
          <span class="panel__title">${lane.title}</span>
          <span class="lane__count">${(groups[lane.key] || []).length}</span>
        </header>
        ${(groups[lane.key] || []).map(ticket).join("") || `<div class="empty" style="padding:22px 8px"><span class="faint tiny">${lane.hint}</span></div>`}
      </section>`).join("");

    $$("[data-act]", board).forEach((btn) => btn.addEventListener("click", async (event) => {
      event.stopPropagation();
      const res = await api("/api/orders/action/", {
        method: "POST", body: { id: Number(btn.dataset.id), action: btn.dataset.act, line_id: Number(btn.dataset.line || 0) || undefined },
      });
      if (res.ok) {
        orders = orders.map((row) => (row.id === res.order.id ? res.order : row));
        toast(res.notice, { tone: "good", title: res.order.number });
        render();
        if (window.RMS?.floor && res.overview?.floor) window.RMS.floor.set(res.overview.floor);
      }
    }));
    $$("[data-ticket]", board).forEach((node) => node.addEventListener("click", () => {
      const order = orders.find((row) => row.id === Number(node.dataset.ticket));
      if (order) openOrder(order);
    }));
    const open = Object.values(groups).flat();
    const value = open.reduce((sum, row) => sum + Number(row.total || 0), 0);
    const chip = $("[data-role='open-value']");
    if (chip) chip.innerHTML = `<span class="dot dot--warn"></span>${open.length} open · ${money(value)} on the floor`;
  }

  const ticket = (order) => `
    <article class="ticket ${order.late ? "is-late" : ""}" data-ticket="${order.id}">
      <header class="ticket__top">
        <span class="ticket__no">${esc(order.number)}</span>
        <span class="tag">${esc(order.channel_label)}</span>
        ${order.priority === "rush" ? '<span class="tag tag--bad">rush</span>' : ""}
        <span class="ticket__age" style="${order.late ? "color:var(--bad)" : ""}">${esc(order.age)}</span>
      </header>
      <div class="ticket__guest">${esc(order.guest)} <span class="faint tiny">· ${order.party} covers · ${esc(order.table || "no table")}</span></div>
      ${order.note ? `<p class="tiny" style="margin:0 0 6px;color:var(--warn)">“${esc(order.note)}”</p>` : ""}
      <div class="lines">
        ${order.lines.map((line) => `
          <div class="line">
            <span class="line__q">${line.quantity}×</span>
            <span class="line__n clip">${esc(line.name)}${line.notes ? ` <s class="line__note">${esc(line.notes)}</s>` : ""}</span>
            <span class="line__p">${money(line.unit_price)}</span>
          </div>`).join("")}
      </div>
      <footer class="ticket__foot">
        ${order.status === "new" ? `<button class="btn btn--xs btn--gold" data-act="advance" data-id="${order.id}">fire</button>` : ""}
        ${order.status === "fire" ? `<button class="btn btn--xs btn--gold" data-act="advance" data-id="${order.id}">ready</button>` : ""}
        ${order.status === "ready" ? `<button class="btn btn--xs btn--gold" data-act="advance" data-id="${order.id}">serve</button>` : ""}
        ${order.status === "served" ? `<button class="btn btn--xs btn--gold" data-act="advance" data-id="${order.id}">settle</button>` : ""}
        ${order.status !== "paid" ? `<button class="btn btn--xs btn--ghost" data-act="hold" data-id="${order.id}">${order.priority === "rush" ? "unflag" : "rush"}</button>` : ""}
        <span class="num" style="margin-left:auto;font-size:12px;color:var(--gold-soft)">${money(order.total)}</span>
      </footer>
      <span class="progress"><i style="width:${order.progress}%"></i></span>
    </article>`;

  function openOrder(order) {
    RMS.drawer(`
      <div class="kv">
        <dt>ticket</dt><dd class="mono">${esc(order.number)} · ${esc(order.status_label)}</dd>
        <dt>guest</dt><dd>${esc(order.guest)} · ${order.party} covers</dd>
        <dt>channel</dt><dd>${esc(order.channel_label)}${order.table ? ` · ${esc(order.table)}` : ""}</dd>
        <dt>floor</dt><dd>${esc(order.waiter || "unassigned")} · chef ${esc(order.chef || "unassigned")}</dd>
        <dt>opened</dt><dd>${esc(order.opened)}</dd>
      </div>
      <div class="divider"></div>
      <span class="tiny">lines</span>
      <div class="rows" style="margin-top:8px">${order.lines.map((line) => `
        <div class="rowline">
          <span class="dot dot--${line.tone}"></span>
          <span>${line.quantity}× ${esc(line.name)}${line.notes ? `<span class="tiny" style="display:block">${esc(line.notes)}</span>` : ""}</span>
          <span class="num small">${money(line.line_total)}</span>
        </div>`).join("")}</div>
      <div class="divider"></div>
      <div class="kv">
        <dt>subtotal</dt><dd class="mono">${money(order.subtotal)}</dd>
        <dt>service</dt><dd class="mono">${money(order.service)}</dd>
        <dt>tax</dt><dd class="mono">${money(order.tax)}</dd>
        <dt>total</dt><dd class="mono" style="color:var(--gold-soft);font-size:15px">${money(order.total)}</dd>
      </div>`,
      {
        title: order.number,
        sub: `${order.guest} · ${order.status_label} · ${order.age}`,
        avatar: order.table ? order.table.replace(/[^0-9]/g, "") || "◆" : "◆",
        foot: order.status !== "paid"
          ? `<button class="btn btn--sm btn--danger" data-drawer-cancel="${order.id}">cancel</button>
             <button class="btn btn--sm btn--gold" data-drawer-settle="${order.id}">settle &amp; drain stock</button>`
          : `<span class="tiny">settled — stock already drained through the ledger</span>`,
      });
    const node = $("[data-drawer]");
    node.querySelector("[data-drawer-settle]")?.addEventListener("click", async () => {
      const res = await api("/api/orders/action/", { method: "POST", body: { id: order.id, action: "settle" } });
      if (res.ok) { toast(res.notice, { tone: "good", title: "Settled" }); await refresh(); RMS.drawer.close(); }
    });
    node.querySelector("[data-drawer-cancel]")?.addEventListener("click", async () => {
      if (!confirm(`Cancel ${order.number}? No stock was consumed yet.`)) return;
      const res = await api("/api/orders/action/", { method: "POST", body: { id: order.id, action: "cancel" } });
      if (res.ok) { toast(res.notice, { tone: "bad" }); await refresh(); RMS.drawer.close(); }
    });
  }

  async function refresh() {
    const res = await api("/api/orders/?status=open", { silent: true });
    if (res.ok) { orders = res.orders.concat(orders.filter((row) => !res.orders.find((r) => r.id === row.id))); render(); }
  }

  /* ── composer ──────────────────────────────────────────────────────── */
  const lineHost = $("[data-order-lines]");
  function paintLines() {
    lineHost.innerHTML = lines.length ? lines.map((row, index) => `
      <div class="rowline">
        <span class="rank">${index + 1}</span>
        <span>${row.quantity}× ${esc(row.name)}${row.notes ? ` <s class="tiny">${esc(row.notes)}</s>` : ""}</span>
        <span class="row" style="gap:6px">
          <button class="btn btn--xs btn--ghost" data-line-dec="${index}">−</button>
          <span class="num small">${money(row.price * row.quantity)}</span>
          <button class="btn btn--xs btn--ghost" data-line-inc="${index}">+</button>
          <button class="btn btn--xs btn--ghost" data-line-rm="${index}">✕</button>
        </span>
      </div>`).join("") : `<div class="empty" style="padding:14px"><span class="tiny">nothing on the ticket yet</span></div>`;
    const total = lines.reduce((sum, row) => sum + row.price * row.quantity, 0);
    $("[data-role='order-total']").textContent = money(total);
    $("[data-role='cart-count']").textContent = lines.length ? `${lines.length} line${lines.length > 1 ? "s" : ""}` : "nothing added";
    $$("[data-line-inc], [data-line-dec], [data-line-rm]", lineHost).forEach((btn) => btn.addEventListener("click", () => {
      const inc = btn.dataset.lineInc, dec = btn.dataset.lineDec, rm = btn.dataset.lineRm;
      const index = Number(inc ?? dec ?? rm);
      if (rm !== undefined) lines.splice(index, 1);
      else if (inc !== undefined) lines[index].quantity += 1;
      else if (lines[index].quantity > 1) lines[index].quantity -= 1;
      else lines.splice(index, 1);
      paintLines();
    }));
  }

  async function loadDishes() {
    const res = await api("/api/menu/items/?view=live", { silent: true });
    if (res.ok) dishes = res.items;
    const tableHost = $("#o-table");
    if (tableHost && tables.length) {
      tableHost.innerHTML = `<option value="">no table</option>` + tables.map((row) =>
        `<option value="${row.id}">${esc(row.label)} · ${row.seats} seats · ${esc(row.status)}</option>`).join("");
    }
  }

  const search = $("[data-order-search]");
  search.addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); addByName(); }
  });
  search.addEventListener("input", debounce(() => {
    const term = search.value.trim().toLowerCase();
    if (term.length < 2) return;
    const match = dishes.find((row) => row.name.toLowerCase().includes(term));
    if (match) search.title = `Enter adds ${match.name} (${money(match.price)})`;
  }, 120));
  $("[data-action='order-add']").addEventListener("click", addByName);

  function addByName() {
    const term = search.value.trim().toLowerCase();
    const match = dishes.find((row) => row.name.toLowerCase().includes(term));
    if (!match) { toast("No live dish matches that.", { tone: "warn" }); return; }
    const existing = lines.find((row) => row.item === match.id);
    if (existing) existing.quantity += 1;
    else lines.push({ item: match.id, name: match.name, price: Number(match.price), quantity: 1, notes: "" });
    search.value = "";
    paintLines();
  }

  $("[data-new-order]").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!lines.length) { toast("Add at least one dish.", { tone: "warn" }); return; }
    const form = event.currentTarget;
    const res = await api("/api/orders/create/", {
      method: "POST",
      body: {
        guest: form.guest.value || "Walk-in", party: Number(form.party.value) || 2,
        channel: form.channel.value, table: form.table.value || null, lines,
      },
    });
    if (res.ok) {
      orders.unshift(res.order);
      render();
      paintLines();
      form.reset();
      toast(`${res.order.number} is on the rail.`, { tone: "good", title: "Ticket fired" });
    }
  });

  window.addEventListener("rms:table", (event) => {
    const detail = event.detail;
    if (!detail?.order) return;
    const order = orders.find((row) => row.id === detail.order.id);
    if (order) openOrder(order);
  });

  /* ── boot ──────────────────────────────────────────────────────────── */
  window.RMS.boot(async () => {
    await loadDishes();
    render();
    paintLines();
    if (window.RMS.floor?.set) window.RMS.floor.set(tables);
    const focus = new URLSearchParams(location.search).get("ticket");
    if (focus) {
      const order = orders.find((row) => String(row.id) === focus);
      if (order) openOrder(order);
    }
    setInterval(() => { if (!document.hidden) refresh(); }, 14000);
  });
})();
