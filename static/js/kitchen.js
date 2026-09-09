/* ============================================================================
   kitchen.js · the pass. Big, glanceable fire tickets, tap-a-line-to-done.
   ========================================================================== */
(() => {
  "use strict";
  const { $, $$, api, esc, toast } = window.RMS;
  const node = document.querySelector('[data-role="kds-seed"]');
  let tickets = [];
  try { tickets = JSON.parse(node?.textContent || "[]"); } catch { tickets = []; }
  const LANE = Number(document.querySelector("[data-role='kds-lane']")?.dataset.minutes || 16);

  const toneFor = (age, late) => (late ? "hot" : age > 8 ? "warn" : "good");

  function render() {
    const host = $("[data-kds]");
    const live = tickets.filter((row) => ["new", "fire", "ready"].includes(row.status));
    $("[data-role='kds-count']").textContent = `${live.length} live`;
    if (!live.length) {
      host.innerHTML = `<div class="panel panel--pad empty"><span class="empty__mark" style="color:var(--good)">✓</span>
        Rail is clear. Prep the next service.</div>`;
      return;
    }
    host.innerHTML = live.map((order) => {
      const age = Math.floor(order.age_seconds / 60);
      return `
      <article class="firecard tilt ${order.late ? "is-hot" : ""}" data-ticket="${order.id}">
        <div class="row-between" style="margin-bottom:10px">
          <div>
            <div class="mono small" style="color:var(--gold-soft)">${esc(order.number)}</div>
            <div style="font-size:15px;font-weight:600">${esc(order.guest)}${order.table ? ` · ${esc(order.table)}` : ""}</div>
          </div>
          <div style="text-align:right">
            <div class="num" style="font-size:20px;color:var(--${toneFor(age, order.late)})">${age}′</div>
            <div class="tiny">${esc(order.status_label)}</div>
          </div>
        </div>
        <div class="stack" style="gap:2px">
          ${order.lines.map((line) => `
            <label class="firecard__line" data-line="${line.id}" data-id="${order.id}">
              <input type="checkbox" ${line.state === "served" ? "checked" : ""} data-line-toggle>
              <span class="firecard__qty">${line.quantity}×</span>
              <span class="grow">${esc(line.name)}${line.notes ? `<span class="tiny" style="display:block">${esc(line.notes)}</span>` : ""}</span>
            </label>`).join("")}
        </div>
        ${order.note ? `<p class="tiny" style="margin:8px 0 0;color:var(--warn)">⚑ ${esc(order.note)}</p>` : ""}
        <div class="row" style="margin-top:11px;gap:6px">
          ${order.status === "new" ? `<button class="btn btn--xs btn--gold" data-kds-act="advance" data-id="${order.id}">start firing</button>` : ""}
          ${order.status === "fire" ? `<button class="btn btn--xs btn--gold" data-kds-act="ready" data-id="${order.id}">all up</button>` : ""}
          ${order.status === "ready" ? `<button class="btn btn--xs btn--gold" data-kds-act="advance" data-id="${order.id}">handed off</button>` : ""}
          <span class="faint tiny" style="margin-left:auto">lane ${order.lane || LANE}′</span>
        </div>
      </article>`;
    }).join("");

    $$("[data-kds-act]", host).forEach((btn) => btn.addEventListener("click", async (event) => {
      event.stopPropagation();
      const res = await api("/api/orders/action/", { method: "POST", body: { id: Number(btn.dataset.id), action: btn.dataset.kdsAct } });
      if (res.ok) {
        tickets = tickets.map((row) => (row.id === res.order.id ? res.order : row));
        render();
      }
    }));

    $$("[data-line]", host).forEach((row) => row.addEventListener("change", async (event) => {
      const box = event.target;
      if (!box.matches("[data-line-toggle]")) return;
      const res = await api("/api/orders/action/", {
        method: "POST", body: { id: Number(row.dataset.id), action: "line", line_id: Number(row.dataset.line) },
      });
      if (res.ok) {
        tickets = tickets.map((t) => (t.id === res.order.id ? res.order : t));
        render();
        toast(box.checked ? "Line marked up." : "Line back on the fire.", { tone: box.checked ? "good" : "info" });
      }
    }));
  }

  $("[data-action='advance-all']")?.addEventListener("click", async () => {
    const fireable = tickets.filter((row) => ["new", "fire", "ready"].includes(row.status));
    for (const order of fireable) {
      await api("/api/orders/action/", { method: "POST", body: { id: order.id, action: "advance" }, silent: true });
    }
    await pull();
    toast(`${fireable.length} ticket${fireable.length === 1 ? "" : "s"} advanced.`, { tone: "good" });
  });

  async function pull() {
    const res = await api("/api/orders/?status=open", { silent: true });
    if (res.ok) { tickets = res.orders; render(); }
  }

  window.RMS.boot(() => {
    render();
    setInterval(() => { if (!document.hidden) pull(); }, 9000);
    addEventListener("keydown", (event) => { if (event.key === " " && !event.target.matches("input,textarea")) { event.preventDefault(); $("[data-action='advance-all']")?.click(); } });
  });
})();
