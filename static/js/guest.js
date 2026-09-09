/* ============================================================================
   guest.js · the public menu — 3D tilting plates, a cart, and a real ticket
   Posts to /api/guest/order/ which reserves stock through the same ledger the
   kitchen uses, so a guest order shows up on the rail with its stock already
   committed.
   ========================================================================== */
(() => {
  "use strict";
  const { $, $$, api, esc, money, toast, tilt, reveal } = window.RMS;
  const node = document.querySelector('[data-role="menu-seed"]');
  let chapters = [];
  try { chapters = JSON.parse(node?.textContent || "[]"); } catch { chapters = []; }

  const cart = new Map();
  const KEY = "rms.cart";
  const modal = RMS.modal();

  function restore() {
    try {
      const raw = JSON.parse(localStorage.getItem(KEY) || "{}");
      Object.entries(raw).forEach(([id, row]) => cart.set(Number(id), row));
    } catch { /* ignore */ }
  }
  const persist = () => { try { localStorage.setItem(KEY, JSON.stringify(Object.fromEntries(cart))); } catch { /* ignore */ } };

  const dishCard = (item, chapter) => {
    const media = item.photo
      ? `<img src="${item.photo.url}" alt="${esc(item.name)}" loading="lazy">`
      : `<div class="medallion" style="--accent:${chapter.accent}"><span class="medallion__mark">${esc(chapter.icon)}</span></div>`;
    const qty = cart.get(item.id)?.quantity || 0;
    return `
      <article class="dish tilt" data-tilt data-dish="${item.id}" data-dish-id="${item.id}">
        <div class="dish__media">
          ${media}
          <span class="dish__price num">${money(item.price)}</span>
          <span class="dish__chapter" style="color:${chapter.accent}">${esc(chapter.icon)} ${esc(chapter.name)}</span>
        </div>
        <div class="dish__body">
          <h3 class="dish__name">${esc(item.name)}</h3>
          <p class="dish__sub">${esc(item.subtitle || item.description || "")}</p>
          <div class="dish__foot">
            <span class="chip"><span class="dot ${item.stock <= item.low_stock_threshold ? "dot--warn" : "dot--good"}"></span>
              ${item.stock <= item.low_stock_threshold ? "last few" : "ready tonight"}</span>
            <span class="row" style="gap:6px">
              ${qty ? `<button class="btn btn--xs btn--ghost" data-dec="${item.id}">−</button><span class="num small">${qty}</span>` : ""}
              <button class="btn btn--xs btn--gold" data-add="${item.id}">${qty ? "add" : "to table"}</button>
            </span>
          </div>
          ${item.allergens?.length ? `<p class="tiny" style="margin:9px 0 0">allergens · ${item.allergens.map(esc).join(" · ")}</p>` : ""}
        </div>
        <span class="tilt__glare"></span>
      </article>`;
  };

  function render() {
    const host = $("[data-chapters]");
    const nav = $("[data-chapter-nav]");
    const term = "";
    host.innerHTML = chapters.map((chapter) => `
      <section class="chapter" id="ch-${chapter.id}" data-chapter="${chapter.id}">
        <header class="chapter__title" style="--accent:${chapter.accent}">
          <h2><span>${esc(chapter.icon)}</span> ${esc(chapter.name)}</h2>
          <span class="tiny">${chapter.items.length} dishes${chapter.blurb ? ` · ${esc(chapter.blurb)}` : ""}</span>
        </header>
        <div class="rail" style="margin-top:16px">${chapter.items.map((item) => dishCard(item, chapter)).join("")}</div>
      </section>`).join("")
      || `<div class="empty panel" style="padding:40px"><span class="empty__mark">◍</span>The menu is being written. Check back shortly.</div>`;

    nav.innerHTML = chapters.map((chapter, index) =>
      `<button data-jump="${chapter.id}" class="${index === 0 ? "is-active" : ""}" style="${index === 0 ? "" : ""}">
        ${esc(chapter.icon)} ${esc(chapter.name)} <span class="faint">${chapter.items.length}</span></button>`).join("");

    $$("[data-jump]", nav).forEach((btn) => btn.addEventListener("click", () => {
      document.getElementById(`ch-${btn.dataset.jump}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
      $$("[data-jump]", nav).forEach((n) => n.classList.remove("is-active"));
      btn.classList.add("is-active");
    }));

    $$("[data-add]", host).forEach((btn) => btn.addEventListener("click", () => bump(Number(btn.dataset.add), 1)));
    $$("[data-dec]", host).forEach((btn) => btn.addEventListener("click", () => bump(Number(btn.dataset.dec), -1)));
    tilt(host);
    reveal(host);
    paintCart();
  }

  const findItem = (id) => {
    for (const chapter of chapters) {
      const found = chapter.items.find((row) => row.id === id);
      if (found) return { item: found, chapter };
    }
    return {};
  };

  function bump(id, delta) {
    const { item } = findItem(id);
    if (!item) return;
    const next = Math.max(0, (cart.get(id)?.quantity || 0) + delta);
    if (next === 0) cart.delete(id);
    else cart.set(id, { id, name: item.name, price: Number(item.price), quantity: Math.min(next, item.stock || 24) });
    persist();
    render();
  }

  function paintCart() {
    const host = $("[data-cart]");
    const rows = [...cart.values()];
    const total = rows.reduce((sum, row) => sum + row.price * row.quantity, 0);
    $("[data-cart-total]").textContent = money(total);
    $("[data-cart-items]").innerHTML = rows.length
      ? rows.map((row) => `<span class="cart__pill">${row.quantity}× ${esc(row.name)}
          <button data-cart-dec="${row.id}" aria-label="remove one">✕</button></span>`).join("")
      : `<span class="tiny">nothing on the table yet</span>`;
    host.classList.toggle("is-in", rows.length > 0);
    $$("[data-cart-dec]").forEach((btn) => btn.addEventListener("click", () => bump(Number(btn.dataset.cartDec), -1)));
    const submit = $("[data-action='checkout']");
    if (submit) submit.textContent = rows.length ? `Send ${rows.reduce((n, r) => n + r.quantity, 0)} to kitchen` : "Send to kitchen";
  }

  $("[data-action='clear-cart']")?.addEventListener("click", () => { cart.clear(); persist(); render(); });

  $("[data-action='checkout']")?.addEventListener("click", () => {
    if (!cart.size) { toast("Add a plate first.", { tone: "warn" }); return; }
    modal.open();
  });

  $("[data-checkout-form]")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const button = form.querySelector("button[type=submit]");
    button.classList.add("is-busy");
    const res = await api("/api/guest/order/", {
      method: "POST",
      body: {
        guest: form.guest.value.trim() || "Web guest",
        party: Number(form.party.value) || 2,
        note: form.note.value.trim(),
        lines: [...cart.values()].map((row) => ({ item: row.id, quantity: row.quantity })),
      },
    });
    button.classList.remove("is-busy");
    if (!res.ok) { toast(res.error || "The kitchen could not take that.", { tone: "bad", title: "Not fired" }); return; }
    cart.clear();
    persist();
    modal.close();
    render();
    toast(res.notice || `Ticket ${res.number} is in.`, { tone: "good", title: `${res.number} · ${money(res.total)}`, ms: 8000 });
  });

  // highlight the chapter nav from scroll position
  const spy = () => {
    let current = null;
    $$("[data-chapter]").forEach((section) => {
      if (section.getBoundingClientRect().top < innerHeight * 0.4) current = section.dataset.chapter;
    });
    if (!current) return;
    $$("[data-jump]").forEach((btn) => btn.classList.toggle("is-active", btn.dataset.jump === current));
  };
  addEventListener("scroll", () => requestAnimationFrame(spy), { passive: true });

  window.RMS.boot(() => { restore(); render(); });
})();
