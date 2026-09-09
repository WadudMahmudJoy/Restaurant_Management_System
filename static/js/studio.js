/* ============================================================================
   studio.js · the smart menu composer
   ---------------------------------------------------------------------------
   Three required fields (name, price, stock). Everything else is inferred:
   • the name is matched against every dish ever stored — a twin means the
     photo, the price history and the par level are already known, so we offer
     a restock instead of a duplicate row;
   • a photo is hashed in the browser (SHA-1) and matched against the library's
     checksums, so an identical file is re-linked instead of re-uploaded;
   • price and stock pre-fill from that dish's own history.
   ========================================================================== */
(() => {
  "use strict";
  const { $, $$, api, esc, money, toast, debounce, clamp } = window.RMS;

  const seedNode = document.querySelector('[data-role="studio-seed"]');
  const seed = (() => { try { return JSON.parse(seedNode?.textContent || "{}"); } catch { return {}; } })();
  const state = {
    items: seed.items || [],
    photos: seed.photos || [],
    categories: seed.categories || [],
    currency: seed.currency || "$",
    pending: null,        // {kind:'file', file, url} | {kind:'library', id} | {kind:'twin', id}
    twin: null,
    suggestion: null,
    selected: null,
    view: "all",
    query: "",
    touched: { price: false, stock: false, chapter: false },
    byChecksum: new Map(),
  };
  window.RMS.state.currency = state.currency;
  state.photos.forEach((photo) => { if (photo.checksum) state.byChecksum.set(photo.checksum, photo); });

  const form = $("[data-composer-form]");
  const nameInput = $("#f-name");
  const priceInput = $("#f-price");
  const stockInput = $("#f-stock");
  const chapterSelect = $("#f-category");
  const fileInput = $("[data-file]");
  const drop = $("[data-drop]");
  const dropImg = $("[data-drop-img]");
  const dropBadge = $("[data-drop-badge]");
  const dropActions = $("[data-drop-actions]");
  const smart = $("[data-smart]");
  const smartText = $("[data-smart-text]");
  const footNote = $("[data-foot-note]");
  const saveBtn = $("#composer-submit");

  /* ── chapter select ────────────────────────────────────────────────── */
  chapterSelect.innerHTML = `<option value="">Let the studio decide</option>` + state.categories.map(
    (row) => `<option value="${row.id}">${esc(row.icon)} ${esc(row.name)} <span style="color:#666">· ${row.items}</span></option>`,
  ).join("");

  /* ── sha-1 in the browser: never upload a file we already own ──────── */
  async function sha1(file) {
    try {
      if (!(crypto?.subtle?.digest && file.arrayBuffer)) return "";
      const buffer = await file.arrayBuffer();
      const digest = await crypto.subtle.digest("SHA-1", buffer);
      return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, "0")).join("");
    } catch { return ""; }
  }

  /* ── photo preview ─────────────────────────────────────────────────── */
  function showPhoto({ url, label, tone = "gold", id = null, file = null, reuse = null }) {
    if (url) {
      dropImg.src = url;
      dropImg.hidden = false;
    } else {
      dropImg.hidden = true;
      dropImg.removeAttribute("src");
    }
    dropBadge.hidden = !label;
    dropBadge.innerHTML = label ? `<span class="dot dot--${tone}"></span>${esc(label)}` : "";
    dropActions.hidden = !url;
    $("[data-photo-state]").textContent = url ? "ready" : "optional";
    $("[data-photo-id]").value = id || "";
    state.pending = file ? { kind: "file", file, url, id: null } : (id ? { kind: "library", id } : null);
    if (reuse !== null) {
      footNote.innerHTML = `<span class="dot dot--good"></span>${esc(reuse)}`;
    }
  }

  /* ── the suggestion engine ─────────────────────────────────────────── */
  const ask = debounce(async () => {
    const name = nameInput.value.trim();
    if (name.length < 2) {
      smart.classList.add("is-off");
      $("[data-name-state]").textContent = "";
      state.twin = null;
      setMode("auto", "New dish");
      if (!state.pending) showPhoto({});
      return;
    }
    const params = new URLSearchParams({ name });
    if (chapterSelect.value) params.set("category", chapterSelect.value);
    if (priceInput.value && state.touched.price) params.set("price", priceInput.value);
    const res = await api(`/api/menu/suggest/?${params}`, { silent: true });
    const s = res.suggestion;
    if (!s) return;
    state.suggestion = s;
    state.twin = s.twin || null;

    // 1 · smart bar
    const headline = s.status === "twin"
      ? `Twin found — “${s.twin.name}” is already on ${s.twin.category_name}. We'll restock it, not duplicate it.`
      : (s.flags[0] || (s.photo ? s.photo_basis : "Fresh dish — we'll infer chapter, par level and station."));
    smartText.innerHTML = esc(headline) + (s.flags.length > 1 ? ` <span class="faint">· ${esc(s.flags[1])}</span>` : "");
    smart.classList.toggle("is-off", false);

    // 2 · chapter
    if (s.chapter && !state.touched.chapter) {
      chapterSelect.value = String(s.chapter.id);
      $("[data-chapter-basis]").textContent = `guessed from “${s.status === "twin" ? s.twin.name : (s.donor?.name || "your words")}”`;
    }
    // 3 · money + stock, only when untouched
    if (s.price && !state.touched.price) {
      priceInput.value = s.price;
      $("[data-price-basis]").textContent = s.price_basis ? `· ${s.price_basis}` : "";
    }
    if (s.stock_basis && !state.touched.stock) {
      stockInput.value = s.stock;
      $("[data-stock-hint]").innerHTML = `<span class="hint--smart">${esc(s.stock_basis)}</span>`;
    }
    // 4 · the photo — the whole point
    if (!state.pending && s.photo) {
      showPhoto({
        url: s.photo.url, id: s.photo.id, label: s.photo.label,
        tone: s.photo.basis === "twin" ? "good" : "info",
        reuse: s.photo_basis,
      });
      $("[data-photo-state]").textContent = "inherited";
    } else if (!state.pending && !s.photo) {
      $("[data-photo-state]").textContent = "no twin photo — one upload fixes it forever";
    }

    // 5 · mode + button label
    if (s.status === "twin") {
      setMode("auto", `Restock “${s.twin.name}”`);
      $("[data-twin-id]").value = s.twin.id;
      const need = s.restock?.needed ?? 0;
      footNote.innerHTML = `<span class="dot dot--warn"></span>currently ${s.twin.stock} ${esc(s.twin.unit)} · par ${s.twin.par_level}
        · <button type="button" class="btn btn--xs btn--ghost" data-action="fill-par">fill to par (+${need})</button>
        <button type="button" class="btn btn--xs btn--ghost" data-action="force-new">create anyway</button>`;
    } else {
      setMode("create", "New dish");
      $("[data-twin-id]").value = "";
      footNote.innerHTML = `<span class="dot dot--good"></span>${s.photo ? "photo will be linked from the library" : "add a photo, or skip it — twins inherit the first one you do add"}`;
    }
    $("[data-name-state]").innerHTML = s.match_score
      ? `<span class="tone-good">${s.match_score}% like “${esc((s.donor || s.twin)?.name || "")}”</span>` : "";
  }, 240);

  function setMode(mode, title) {
    $("[data-mode]").value = mode;
    $("[data-composer-mode-title]").textContent = title;
    saveBtn.textContent = mode === "restock" ? "Restock dish" : (mode === "create" && $("[data-twin-id]").value ? "Create as new" : "Save dish");
  }

  /* ── save ──────────────────────────────────────────────────────────── */
  async function save() {
    const name = nameInput.value.trim();
    if (name.length < 2) { nameInput.focus(); toast("A dish needs a name — that's the only hard rule.", { tone: "warn" }); return; }
    saveBtn.classList.add("is-busy");
    let res;
    const useMultipart = state.pending?.kind === "file";
    const payload = {
      name,
      price: priceInput.value || null,
      stock: stockInput.value || 0,
      category: chapterSelect.value || null,
      mode: $("[data-mode]").value,
      photo_id: state.pending?.kind === "library" ? state.pending.id : ($("[data-photo-id]").value || null),
      subtitle: form.querySelector('[name="subtitle"]')?.value || "",
      description: form.querySelector('[name="description"]')?.value || "",
      cost: form.querySelector('[name="cost"]')?.value || "",
      heat: form.querySelector('[name="heat"]')?.value || 0,
      is_veg: form.querySelector('[name="is_veg"]')?.checked ? "true" : "",
      is_signature: form.querySelector('[name="is_signature"]')?.checked ? "true" : "",
    };
    if (useMultipart) {
      const fd = new FormData(form);
      fd.set("photo_id", "");
      res = await api("/api/menu/save/", { method: "POST", form: fd });
    } else {
      res = await api("/api/menu/save/", { method: "POST", body: payload });
    }
    saveBtn.classList.remove("is-busy");
    if (!res.ok) {
      const first = (res.errors || [])[0];
      if (first) toast(first.message, { tone: "bad", title: first.field });
      return;
    }
    const item = res.item;
    if (item) {
      const index = state.items.findIndex((row) => row.id === item.id);
      if (index >= 0) state.items[index] = item; else state.items.unshift(item);
      paintList();
      const row = $(`[data-row="${item.id}"]`);
      row?.classList.add("flash");
      setTimeout(() => row?.classList.remove("flash"), 1200);
    }
    toast(res.notice || "Saved.", { tone: "good", title: res.action === "restocked" ? "Restocked, not duplicated" : "Dish saved" });
    resetForm();
  }

  function resetForm() {
    form.reset();
    state.pending = null;
    state.twin = null;
    state.touched = { price: false, stock: false, chapter: false };
    showPhoto({});
    smart.classList.add("is-off");
    $("[data-price-basis]").textContent = "";
    $("[data-stock-hint]").textContent = "";
    $("[data-name-state]").textContent = "";
    $("[data-chapter-basis]").textContent = "optional — we'll pick one";
    $("[data-twin-id]").value = "";
    setMode("auto", "New dish");
    footNote.innerHTML = '<span class="dot dot--good"></span>Nothing typed yet — the studio is listening.';
    nameInput.focus();
  }

  /* ── the menu ledger list ──────────────────────────────────────────── */
  function itemRow(item) {
    const tone = item.stock_state === "out" ? "bad" : item.stock_state === "low" ? "warn" : item.stock_state === "steady" ? "info" : "good";
    const photo = item.photo
      ? `<img src="${item.photo.url}" alt="" loading="lazy">`
      : `<span class="dishrow__mini">${esc((item.name || "?")[0])}</span>`;
    const share = item.photo?.reuse > 1 ? `<span class="tag tag--gold">shared ×${item.photo.reuse}</span>` : "";
    const photoNote = item.photo_source === "inherited" ? '<span class="tag tag--good">inherited</span>'
      : item.photo ? '<span class="tag">library</span>' : '<span class="tag tag--warn">no photo</span>';
    return `
      <div class="dishrow" data-row="${item.id}" tabindex="0">
        <span class="dishrow__thumb">${photo}</span>
        <span style="min-width:0">
          <span class="dishrow__name">${esc(item.name)} ${item.is_signature ? '<span class="tag tag--gold">signature</span>' : ""}
            ${item.is_available ? "" : '<span class="tag tag--bad">86’d</span>'}</span>
          <span class="dishrow__meta">
            <span style="color:${item.accent}">◆</span>${esc(item.category_name)} · ${esc(item.station)} · ${item.prep_minutes}′
            ${photoNote} ${share}
          </span>
          <span class="stockbar" style="margin-top:6px"><span class="stockbar__track">
            <i class="stockbar__fill" style="width:${clamp(item.stock / Math.max(item.par_level, 1) * 100, 2, 100)}%;background:var(--${tone})"></i>
          </span></span>
        </span>
        <span style="text-align:right">
          <span class="dishrow__num" style="color:var(--gold-soft)">${money(item.price)}</span>
          <span class="tiny" style="display:block">${item.stock}/${item.par_level} ${esc(item.unit)}</span>
        </span>
        <span class="dishrow__acts">
          <button class="btn btn--xs btn--ghost" data-act="restock" data-id="${item.id}" title="Top back to par (+${item.needs_restock})">+par</button>
          <button class="btn btn--xs btn--ghost" data-act="edit" data-id="${item.id}">edit</button>
          <button class="btn btn--xs btn--ghost" data-act="toggle" data-id="${item.id}" title="${item.is_available ? "86 this dish" : "put back on the menu"}">${item.is_available ? "86" : "on"}</button>
        </span>
      </div>`;
  }

  function filtered() {
    const q = state.query.toLowerCase();
    return state.items.filter((item) => {
      if (q && !`${item.name} ${item.subtitle} ${item.category_name} ${item.station}`.toLowerCase().includes(q)) return false;
      if (state.view === "low") return item.stock <= item.low_stock_threshold;
      if (state.view === "no-photo") return !item.photo;
      if (state.view === "hidden") return !item.is_available;
      if (state.view === "live") return item.is_available;
      return true;
    });
  }

  function paintList() {
    const host = $("[data-dishlist]");
    const rows = filtered();
    host.innerHTML = rows.length
      ? rows.map(itemRow).join("")
      : `<div class="empty"><span class="empty__mark">◍</span>${state.query ? `nothing matches “${esc(state.query)}”` : "no dishes in this view"}</div>`;
    $$("[data-row]", host).forEach((node) => {
      node.addEventListener("click", (event) => {
        if (event.target.closest("[data-act]")) return;
        openDrawer(Number(node.dataset.row));
      });
      node.addEventListener("keydown", (event) => { if (event.key === "Enter") openDrawer(Number(node.dataset.row)); });
    });
    if (!host.__bound) { host.addEventListener("click", onListAction); host.__bound = true; }
  }

  async function onListAction(event) {
    const btn = event.target.closest("[data-act]");
    if (!btn) return;
    event.stopPropagation();
    const id = Number(btn.dataset.id);
    const item = state.items.find((row) => row.id === id);
    if (!item) return;
    if (btn.dataset.act === "restock") {
      const need = item.needs_restock || Math.max(1, item.par_level - item.stock);
      const res = await api("/api/menu/restock/", { method: "POST", body: { id, quantity: need } });
      if (res.ok) { state.items[state.items.findIndex((r) => r.id === id)] = res.item; paintList(); toast(res.notice, { tone: "good", title: `+${need} ${item.unit}` }); }
    } else if (btn.dataset.act === "toggle") {
      const res = await api("/api/menu/toggle/", { method: "POST", body: { id } });
      if (res.ok) { state.items[state.items.findIndex((r) => r.id === id)] = res.item; paintList(); toast(res.item.is_available ? "Back on the menu." : "86'd — guests can't order it.", { tone: res.item.is_available ? "good" : "warn" }); }
    } else if (btn.dataset.act === "edit") {
      loadIntoComposer(item);
    }
  }

  function loadIntoComposer(item) {
    nameInput.value = item.name;
    priceInput.value = item.price;
    stockInput.value = item.needs_restock || item.stock;
    chapterSelect.value = String(item.category);
    $("[data-twin-id]").value = item.id;
    form.querySelector('[name="subtitle"]').value = item.subtitle || "";
    form.querySelector('[name="cost"]').value = item.cost || "";
    form.querySelector('[name="description"]').value = item.description || "";
    form.querySelector('[name="is_veg"]').checked = !!item.is_veg;
    form.querySelector('[name="is_signature"]').checked = !!item.is_signature;
    state.touched = { price: true, stock: false, chapter: true };
    setMode("restock", `Editing “${item.name}”`);
    if (item.photo) {
      showPhoto({ url: item.photo.url, id: item.photo.id, label: `kept: ${item.photo.label}`, tone: "good", reuse: "Photo already on file — nothing to re-upload." });
    } else {
      showPhoto({});
      $("[data-photo-state]").textContent = "no photo yet";
    }
    footNote.innerHTML = `<span class="dot dot--info"></span>Save applies price + stock to this dish — the photo stays put.`;
    document.querySelector(".composer").scrollIntoView({ behavior: "smooth", block: "start" });
    stockInput.focus();
  }

  /* ── drawer ────────────────────────────────────────────────────────── */
  async function openDrawer(id) {
    const res = await api(`/api/menu/items/${id}/`);
    const item = res.item;
    if (!item) return;
    state.selected = item;
    $$("[data-row]").forEach((node) => node.classList.toggle("is-selected", Number(node.dataset.row) === id));
    const history = (item.price_history || []).map((row) => `<div class="legend__row"><span class="legend__sw" style="background:var(--gold)"></span>
      <span>${money(row.price)}</span><span class="legend__val">${new Date(row.when).toLocaleDateString("en-GB", { day: "2-digit", month: "short" })} ${row.delta ? `(${row.delta > 0 ? "+" : ""}${row.delta}%)` : ""}</span></div>`).join("");
    const ledger = (item.ledger || []).map((row) => `<div class="legend__row"><span class="legend__sw" style="background:var(--${row.direction === "Out" ? "bad" : "good"})"></span>
      <span>${esc(row.reason)} ${row.direction === "Out" ? "−" : "+"}${row.quantity} → ${row.balance}</span>
      <span class="legend__val">${esc(row.when)}</span></div>`).join("");
    RMS.drawer(`<div class="cols--2" style="display:grid;gap:12px">
        <div class="card" style="padding:12px"><span class="tiny">price</span>
          <div class="row" style="gap:6px;margin-top:6px">
            <input class="input input--money" value="${item.price}" data-drawer-price inputmode="decimal">
            <button class="btn btn--sm btn--gold" data-drawer-save-price>set</button>
          </div></div>
        <div class="card" style="padding:12px"><span class="tiny">stock · ${esc(item.stock_label)}</span>
          <div class="row" style="gap:6px;margin-top:6px">
            <button class="btn btn--sm" data-drawer-stock="-1">−1</button>
            <span class="num" style="flex:1;text-align:center">${item.stock}</span>
            <button class="btn btn--sm" data-drawer-stock="1">+1</button>
            <button class="btn btn--sm btn--ghost" data-drawer-stock="10">+10</button>
            <button class="btn btn--sm btn--ghost" data-drawer-stock="par">to par</button>
          </div></div>
      </div>
      <div class="divider"></div>
      <div class="kv">
        <dt>photo</dt><dd>${item.photo ? `${esc(item.photo.label)} · re-used by ${item.photo.reuse} dish${item.photo.reuse === 1 ? "" : "es"} <span class="tag tag--gold">${esc(item.photo_source)}</span>` : "none yet"}</dd>
        <dt>note</dt><dd>${esc(item.photo_note || "—")}</dd>
        <dt>margin</dt><dd>${item.margin_pct === null ? "add a cost" : item.margin_pct + "%"}</dd>
        <dt>turn</dt><dd>${item.turn_label}/day · ${item.sold_total} sold ever</dd>
        <dt>station</dt><dd>${esc(item.station)} · ${item.prep_minutes} min</dd>
        <dt>match key</dt><dd class="mono small">${esc(item.name.toLowerCase())}</dd>
      </div>
      <div class="divider"></div>
      <span class="tiny">price ledger</span><div class="legend" style="margin-top:8px">${history || '<span class="faint small">no changes yet</span>'}</div>
      <div class="divider"></div>
      <span class="tiny">stock ledger</span><div class="legend" style="margin-top:8px">${ledger || '<span class="faint small">no movements yet</span>'}</div>`,
      {
        title: item.name,
        sub: `${item.category_name} · ${item.stock} ${item.unit} · ${money(item.price)}`,
        avatar: item.photo ? "" : (item.name[0] || "◆"),
        foot: `<button class="btn btn--sm btn--danger" data-drawer-delete>Delete dish</button>
               <button class="btn btn--sm btn--ghost" data-drawer-86>${item.is_available ? "86 it" : "Put on menu"}</button>
               <button class="btn btn--sm btn--gold" data-drawer-edit>load into composer</button>`,
      },
    );
    const drawerEl = $("[data-drawer]");
    drawerEl.querySelector("[data-drawer-avatar]").innerHTML = item.photo
      ? `<img src="${item.photo.url}" alt="" style="width:100%;height:100%;object-fit:cover;border-radius:50%">` : esc(item.name[0] || "◆");
    drawerEl.querySelector("[data-drawer-edit]")?.addEventListener("click", () => { RMS.drawer.close(); loadIntoComposer(item); });
    drawerEl.querySelector("[data-drawer-save-price]")?.addEventListener("click", async () => {
      const value = drawerEl.querySelector("[data-drawer-price]").value;
      const out = await api("/api/menu/price/", { method: "POST", body: { id: item.id, price: value } });
      if (out.ok) { patchItem(out.item); toast("Price written to the ledger.", { tone: "good" }); openDrawer(item.id); }
    });
    $$("[data-drawer-stock]", drawerEl).forEach((btn) => btn.addEventListener("click", async () => {
      const raw = btn.dataset.drawerStock;
      const par = raw === "par";
      const quantity = par ? (item.needs_restock || 0) : Number(raw);
      if (!quantity) { toast(par ? "Already at par level." : "Nothing to change.", { tone: "warn" }); return; }
      const out = await api(par ? "/api/menu/restock/" : "/api/menu/adjust/", {
        method: "POST", body: { id: item.id, quantity, reason: par ? "restock" : "count" },
      });
      if (out.ok) {
        const updated = out.item;
        if (par) updated.stock = item.stock + quantity; // restock payload may predate the write
        patchItem(updated);
        paintList();
        openDrawer(item.id);
        toast(par ? `Topped back to par (+${quantity}).` : `Stock ${quantity > 0 ? "+" : ""}${quantity}.`, { tone: "good" });
      }
    }));
    drawerEl.querySelector("[data-drawer-86]")?.addEventListener("click", async () => {
      const out = await api("/api/menu/toggle/", { method: "POST", body: { id: item.id } });
      if (out.ok) { patchItem(out.item); paintList(); openDrawer(item.id); }
    });
    drawerEl.querySelector("[data-drawer-delete]")?.addEventListener("click", async () => {
      if (!confirm(`Delete “${item.name}”? Dishes with sales history are 86'd instead.`)) return;
      const out = await api("/api/menu/delete/", { method: "POST", body: { id: item.id } });
      if (out.ok) {
        state.items = state.items.filter((row) => row.id !== item.id);
        paintList(); RMS.drawer.close(); toast(out.notice, { tone: out.archived ? "warn" : "bad" });
      }
    });
  }

  function patchItem(item) {
    const index = state.items.findIndex((row) => row.id === item.id);
    if (index >= 0) state.items[index] = { ...state.items[index], ...item };
  }

  /* ── photo library ─────────────────────────────────────────────────── */
  function paintLibrary() {
    const host = $("[data-library]");
    if (!host) return;
    host.innerHTML = state.photos.length ? state.photos.map((photo) => `
      <figure class="lib__cell" data-photo="${photo.id}" draggable="true" title="${esc(photo.label)} · ${photo.kb}kb">
        <img src="${photo.url}" alt="${esc(photo.label)}" loading="lazy">
        <button class="lib__kill" data-photo-kill="${photo.id}" title="Delete from library">✕</button>
        <figcaption class="lib__meta">
          <span class="clip">${esc(photo.label)}</span>
          <span class="lib__uses">×${photo.reuse}</span>
        </figcaption>
      </figure>`).join("")
      : `<div class="empty"><span class="empty__mark">◍</span>the library fills itself as you add dishes</div>`;

    $$("[data-photo]", host).forEach((cell) => {
      cell.addEventListener("click", async (event) => {
        if (event.target.closest("[data-photo-kill]")) return;
        const photo = state.photos.find((row) => row.id === Number(cell.dataset.photo));
        if (!photo) return;
        if (state.selected || $("[data-row].is-selected")) {
          const target = state.selected || state.items.find((row) => Number($("[data-row].is-selected")?.dataset.row) === row.id);
          if (target) {
            const out = await api("/api/menu/photos/attach/", { method: "POST", body: { item: target.id, photo_id: photo.id } });
            if (out.ok) { patchItem(out.item); paintList(); toast(out.notice, { tone: "good", title: "Photo linked" }); refreshPhotos(); }
            return;
          }
        }
        showPhoto({ url: photo.url, id: photo.id, label: `library: ${photo.label}`, tone: "info", reuse: `Stored once, re-used ${photo.reuse} time${photo.reuse === 1 ? "" : "s"}.` });
        toast("Photo queued for the composer.", { tone: "info" });
      });
      cell.addEventListener("dragstart", (event) => {
        event.dataTransfer.setData("text/x-rms-photo", String(cell.dataset.photo));
        event.dataTransfer.effectAllowed = "copy";
      });
    });
    $$("[data-photo-kill]", host).forEach((btn) => btn.addEventListener("click", async (event) => {
      event.stopPropagation();
      const id = Number(btn.dataset.photoKill);
      if (!confirm("Delete this photo from the library? Dishes keep their data but lose the image.")) return;
      const out = await api("/api/menu/photos/delete/", { method: "POST", body: { id } });
      if (out.ok) {
        state.photos = state.photos.filter((row) => row.id !== id);
        state.items.forEach((row) => { if (row.photo?.id === id) { row.photo = null; row.photo_source = "none"; } });
        paintLibrary(); paintList(); toast(out.notice, { tone: "bad" });
      }
    }));
  }

  async function refreshPhotos() {
    const res = await api("/api/menu/photos/", { silent: true });
    if (res.ok) {
      state.photos = res.photos;
      state.photos.forEach((photo) => { if (photo.checksum) state.byChecksum.set(photo.checksum, photo); });
      paintLibrary();
    }
  }

  /* ── bindings ──────────────────────────────────────────────────────── */
  nameInput.addEventListener("input", ask);
  nameInput.addEventListener("blur", ask);
  chapterSelect.addEventListener("change", () => { state.touched.chapter = true; ask(); });
  priceInput.addEventListener("input", () => { state.touched.price = true; });
  stockInput.addEventListener("input", () => { state.touched.stock = true; });

  form.addEventListener("submit", (event) => { event.preventDefault(); save(); });
  saveBtn.addEventListener("click", (event) => { event.preventDefault(); save(); });

  document.addEventListener("click", async (event) => {
    const fill = event.target.closest('[data-action="fill-par"]');
    if (fill && state.twin) {
      stockInput.value = state.twin.needs_restock || state.twin.par_level;
      state.touched.stock = true;
      return;
    }
    const force = event.target.closest('[data-action="force-new"]');
    if (force) { $("[data-mode]").value = "create"; setMode("create", "Force a new row"); toast("Creating a separate row — the twin keeps its own stock.", { tone: "info" }); }
    if (event.target.closest('[data-action="reset"]')) resetForm();
  });

  $$("[data-views] button").forEach((btn) => btn.addEventListener("click", () => {
    $$("[data-views] button").forEach((node) => node.classList.remove("is-active"));
    btn.classList.add("is-active");
    state.view = btn.dataset.view;
    paintList();
  }));
  $("[data-search]").addEventListener("input", debounce((event) => { state.query = event.target.value.trim(); paintList(); }, 160));

  // file input + drag and drop, with instant checksum matching
  fileInput.addEventListener("change", () => { if (fileInput.files?.[0]) acceptFile(fileInput.files[0]); });
  ["dragenter", "dragover"].forEach((type) => drop.addEventListener(type, (event) => {
    event.preventDefault(); drop.classList.add("is-over");
  }));
  ["dragleave", "drop"].forEach((type) => drop.addEventListener(type, (event) => {
    event.preventDefault(); drop.classList.remove("is-over");
  }));
  drop.addEventListener("drop", async (event) => {
    const photoId = event.dataTransfer.getData("text/x-rms-photo");
    if (photoId) {
      const photo = state.photos.find((row) => String(row.id) === photoId);
      if (photo) { showPhoto({ url: photo.url, id: photo.id, label: `library: ${photo.label}`, tone: "info", reuse: "Dragged from the library — no new bytes stored." }); }
      return;
    }
    const file = event.dataTransfer.files?.[0];
    if (file) acceptFile(file);
  });

  async function acceptFile(file) {
    if (!/^image\//.test(file.type)) { toast("That file isn't an image.", { tone: "bad" }); return; }
    if (file.size > 8 * 1024 * 1024) { toast("Keep photos under 8 MB — they're for the menu, not the wall.", { tone: "warn" }); return; }
    const hash = await sha1(file);
    const match = hash ? state.byChecksum.get(hash) : null;
    if (match) {
      showPhoto({ url: match.url, id: match.id, label: `already in library · ${match.label}`, tone: "good", reuse: `Identical file (sha-1 ${hash.slice(0, 10)}…) — re-linked to “${match.label}”, zero new bytes uploaded.` });
      toast("That exact photo was already in your library. Nothing was uploaded.", { tone: "good", title: "De-duplicated" });
      return;
    }
    const url = URL.createObjectURL(file);
    showPhoto({ url, file, label: "new upload", tone: "warn" });
    $("[data-photo-state]").textContent = "will be stored once, shared forever";
  }

  document.addEventListener("click", (event) => {
    if (event.target.closest('[data-action="clear-photo"]')) { showPhoto({}); $("[data-photo-state]").textContent = "skipped"; }
    if (event.target.closest('[data-action="pick"]')) {
      document.querySelector("[data-library]")?.scrollIntoView({ behavior: "smooth", block: "center" });
      toast("Pick any frame — it links instead of duplicating.", { tone: "info" });
    }
  });

  /* ── boot ──────────────────────────────────────────────────────────── */
  paintList();
  paintLibrary();
  setMode("auto", "New dish");
  const deep = new URLSearchParams(location.search);
  if (deep.get("item")) openDrawer(Number(deep.get("item")));
  if (deep.get("view")) {
    state.view = deep.get("view");
    $$("[data-views] button").forEach((node) => node.classList.toggle("is-active", node.dataset.view === state.view));
    paintList();
  }
  nameInput.focus();
})();
