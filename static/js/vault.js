/* ============================================================================
   vault.js · the data vault — live schema explorer + relationship map
   ========================================================================== */
(() => {
  "use strict";
  const { $, $$, api, esc, int } = window.RMS;

  let schema = null;
  let active = null;

  async function boot() {
    const res = await api("/api/vault/", { silent: true });
    if (!res.ok) { $(".vault").innerHTML = `<div class="panel panel--pad empty">Could not read the schema.</div>`; return; }
    schema = res;
    paintDb(res.database);
    paintList(res.tables);
    drawErp(res.tables);
    select(res.tables.find((row) => row.table.startsWith("menu_item")) || res.tables[0]);
  }

  function paintDb(db) {
    const engine = $("[data-role='db-engine']");
    if (engine) engine.innerHTML = `<span class="dot dot--good"></span>${esc(db.engine)} · ${esc(db.name)}`;
    const size = $("[data-role='db-size']");
    if (size) size.textContent = `${(db.size_kb / 1024).toFixed(2)} MB on disk`;
    const journal = $("[data-role='db-journal']");
    if (journal) journal.innerHTML = `<span class="dot dot--info"></span>${int(db.journal_rows)} journal rows`;
    if (db.pragma && Object.keys(db.pragma).length) {
      $(".page-body").insertAdjacentHTML("afterbegin", `
        <section class="panel" style="padding:14px 18px;display:flex;gap:18px;flex-wrap:wrap;align-items:center">
          <span class="panel__title"><span class="dot dot--gold"></span>Engine pragmas</span>
          ${Object.entries(db.pragma).map(([key, value]) => `<span class="chip"><span class="faint tiny">${esc(key)}</span>
            <b class="mono" style="color:var(--gold-soft)">${esc(value)}</b></span>`).join("")}
          <span class="tiny grow">WAL + foreign keys + normal sync — the sane SQLite trio for a single-venue install.</span>
        </section>`);
    }
  }

  function paintList(tables) {
    const host = $("[data-vault-list]");
    let app = "";
    host.innerHTML = tables.map((row) => {
      const header = row.app !== app ? `<div class="tiny" style="margin:10px 6px 2px">${esc(row.app)}</div>` : "";
      app = row.app;
      return `${header}<button class="vault__item" data-table="${row.table}">
        <span class="dot dot--${row.app === "menu" ? "gold" : row.app === "orders" ? "info" : "good"}"></span>
        <span class="clip">${esc(row.plural)}</span><span class="vault__rows">${int(row.rows)}</span>
      </button>`;
    }).join("");
    $$("[data-table]", host).forEach((btn) => btn.addEventListener("click", () => select(tables.find((row) => row.table === btn.dataset.table))));
  }

  function select(row) {
    if (!row) return;
    active = row.table;
    $$("[data-table]").forEach((btn) => btn.classList.toggle("is-active", btn.dataset.table === active));
    $("[data-role='table-name']").textContent = `${row.table}`;
    $("[data-role='table-doc']").textContent = row.doc || "";
    $("[data-role='table-rows']").innerHTML = `<span class="dot dot--gold"></span>${int(row.rows)} rows`;
    $("[data-role='table-app']").textContent = `${row.app} · ${row.fields.length} fields`;
    $("[data-role='table-fields']").innerHTML = `
      <div class="colschema__row" style="background:rgba(255,255,255,.02)">
        <span class="tiny">column</span><span class="tiny">type</span><span class="tiny">notes</span><span class="tiny">flags</span>
      </div>
      ${row.fields.map((field) => `
        <div class="colschema__row">
          <span><span class="colschema__name">${esc(field.name)}</span>
            <span class="tiny" style="display:block">${esc(field.label)}</span></span>
          <span class="kind kind--${esc(field.kind)}">${esc(field.kind)}</span>
          <span class="small muted" style="min-width:0">${field.related ? `<span class="mono" style="color:var(--info)">→ ${esc(field.related)}</span> ` : ""}${esc(field.help || "")}</span>
          <span class="row" style="gap:4px;justify-content:flex-end">
            ${field.required ? '<span class="tag tag--warn">req</span>' : ""}
            ${field.unique ? '<span class="tag tag--info">uniq</span>' : ""}
            ${field.indexed ? '<span class="tag">idx</span>' : ""}
          </span>
        </div>`).join("")}`;
    $("[data-role='table-indexes']").innerHTML = row.indexes.length
      ? `indexes · ${row.indexes.map((name) => `<span class="mono" style="color:var(--text-2)">${esc(name)}</span>`).join(", ")}` : "no explicit indexes";
    $("[data-role='table-constraints']").innerHTML = row.constraints.length
      ? `constraints · ${row.constraints.map((name) => `<span class="mono" style="color:var(--warn)">${esc(name)}</span>`).join(", ")}` : "—";
    $$(".erd .node").forEach((node) => node.classList.toggle("is-active", node.dataset.table === active));
  }

  /* ── the relationship picture, drawn from the schema itself ─────────── */
  function drawErp(tables) {
    const svg = $("[data-role='erd']");
    if (!svg) return;
    const W = 1000, H = 340;
    const groups = { core: [], accounts: [], menu: [], orders: [] };
    tables.forEach((row) => (groups[row.app] || (groups[row.app] = [])).push(row));
    const order = ["core", "accounts", "menu", "orders"];
    const colW = W / order.length;
    const pos = new Map();
    let markup = "";

    order.forEach((app, column) => {
      const rows = groups[app] || [];
      rows.forEach((row, index) => {
        const x = colW * column + colW / 2;
        const y = rows.length === 1 ? H / 2 : 44 + index * ((H - 90) / Math.max(1, rows.length - 1));
        pos.set(row.table, { x, y, row });
        markup += `
          <g class="node" data-table="${row.table}" transform="translate(${x - 74}, ${y - 20})" style="cursor:pointer">
            <rect width="148" height="40" rx="9"></rect>
            <text x="12" y="17" style="fill:var(--text-2)">${esc(row.model)}</text>
            <text x="12" y="31" style="fill:var(--gold)">${int(row.rows)} rows · ${row.fields.length} cols</text>
          </g>`;
      });
    });

    tables.forEach((row) => {
      row.fields.filter((field) => field.related).forEach((field) => {
        const from = pos.get(row.table);
        const to = pos.get(field.related);
        if (!from || !to) return;
        const curve = `M ${from.x} ${from.y} C ${(from.x + to.x) / 2} ${from.y - 26}, ${(from.x + to.x) / 2} ${to.y + 26}, ${to.x} ${to.y}`;
        const special = field.name === "photo" || field.name === "item";
        markup += `<path class="edge" d="${curve}" ${special ? 'style="stroke:rgba(216,178,106,.75);stroke-width:1.7"' : 'stroke-dasharray="3 4"'}></path>`;
      });
    });
    svg.innerHTML = markup;
    svg.querySelectorAll(".node").forEach((node) => node.addEventListener("click", () => {
      select(tables.find((row) => row.table === node.dataset.table));
    }));
  }

  window.RMS.boot(boot);
})();
