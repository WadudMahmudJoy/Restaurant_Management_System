/* ============================================================================
   Lumière RMS · shared front-end kernel (classic script, exposes window.RMS)
   ---------------------------------------------------------------------------
   • api()      – CSRF-aware JSON transport with toasts on failure
   • charts()   – dependency-free SVG charts (area, bars, donut, spark)
   • tilt()     – pointer-tracked 3D tilt with damped springs
   • reveal()   – IntersectionObserver entrance choreography
   • counter()  – eased number interpolation for KPIs
   Nothing here needs a build step, a framework or a CDN.
   ========================================================================== */
(() => {
  "use strict";

  const $ = (sel, root = document) => (root || document).querySelector(sel);
  const $$ = (sel, root = document) => Array.from((root || document).querySelectorAll(sel));

  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  const lerp = (a, b, t) => a + (b - a) * t;
  const easeOut = (t) => 1 - Math.pow(1 - t, 3);
  const debounce = (fn, ms = 220) => {
    let t; return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
  };
  const reduced = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const state = {
    currency: "$",
    cache: new Map(),
  };

  /* ── transport ──────────────────────────────────────────────────────── */
  function csrf() {
    const fromCookie = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    if (fromCookie) return decodeURIComponent(fromCookie[1]);
    return $("input[name=csrfmiddlewaretoken]")?.value || "";
  }

  async function api(path, { method = "GET", body, form, silent = false } = {}) {
    const opts = { method, headers: { "X-Requested-With": "fetch" }, credentials: "same-origin" };
    if (form) {
      opts.body = form;
    } else if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.headers["X-CSRFToken"] = csrf();
      opts.body = typeof body === "string" ? body : JSON.stringify(body);
    } else if (method !== "GET") {
      opts.headers["X-CSRFToken"] = csrf();
    }
    const started = performance.now();
    let data;
    try {
      const res = await fetch(path, opts);
      const text = await res.text();
      try { data = text ? JSON.parse(text) : {}; }
      catch { data = { ok: false, error: `Unexpected response (${res.status})` }; }
      if (!res.ok && data.ok !== false) data = { ok: false, error: `HTTP ${res.status}`, ...data };
      data.__ms = Math.round(performance.now() - started);
      data.__status = res.status;
      if (!res.ok && !silent) toast(data.error || `Request failed (${res.status})`, { tone: "bad", title: "Not saved" });
    } catch (err) {
      data = { ok: false, error: String(err.message || err) };
      if (!silent) toast("The server did not answer — is runserver still up?", { tone: "bad", title: "Offline" });
    }
    return data;
  }

  /* ── toasts ─────────────────────────────────────────────────────────── */
  function toast(message, { tone = "info", title = "", ms = 4200 } = {}) {
    const host = $("[data-toasts]");
    if (!host) { console.info("[RMS]", message); return; }
    const node = document.createElement("div");
    node.className = `toast toast--${tone}`;
    node.innerHTML = `<span class="toast__mark"></span>
      <div class="toast__body">${title ? `<b>${esc(title)}</b>` : ""}<span>${esc(message)}</span></div>
      <button class="toast__x" aria-label="Dismiss">✕</button>`;
    host.appendChild(node);
    requestAnimationFrame(() => node.classList.add("is-in"));
    const kill = () => {
      node.classList.remove("is-in");
      setTimeout(() => node.remove(), 500);
    };
    node.querySelector(".toast__x").addEventListener("click", kill);
    if (ms) setTimeout(kill, ms);
    return node;
  }

  /* ── money / time ──────────────────────────────────────────────────── */
  const money = (value, decimals = 2) => {
    const n = Number(value || 0);
    return `${n < 0 ? "−" : ""}${state.currency}${Math.abs(n).toLocaleString("en-US", {
      minimumFractionDigits: decimals, maximumFractionDigits: decimals })}`;
  };
  const int = (value) => Number(value || 0).toLocaleString("en-US");
  function timeAgo(input) {
    if (!input) return "—";
    const then = new Date(input).getTime();
    const secs = Math.max(0, (Date.now() - then) / 1000);
    if (secs < 45) return "just now";
    if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
    if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
    return `${Math.floor(secs / 86400)}d ago`;
  }

  /* ── number counters ───────────────────────────────────────────────── */
  const running = new WeakMap();
  function counter(el, to, { prefix = "", suffix = "", decimals = 0, duration = 900, pct = false } = {}) {
    const from = Number(running.get(el) ?? 0);
    const target = Number(to || 0);
    running.set(el, target);
    if (reduced()) {
      el.textContent = `${prefix}${fmt(target, decimals)}${suffix}`;
      return;
    }
    const start = performance.now();
    const step = (now) => {
      const t = clamp((now - start) / duration, 0, 1);
      const value = lerp(from, target, easeOut(t));
      el.textContent = `${prefix}${fmt(pct ? value * 100 : value, decimals)}${suffix}`;
      if (t < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
    function fmt(v, d) {
      return Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
    }
  }

  /* ── charts (pure SVG strings) ─────────────────────────────────────── */
  function smoothPath(points, smoothing = 0.18) {
    if (points.length < 2) return "";
    let d = `M ${points[0][0]} ${points[0][1]}`;
    for (let i = 0; i < points.length - 1; i += 1) {
      const p0 = points[i - 1] || points[i];
      const p1 = points[i];
      const p2 = points[i + 1];
      const p3 = points[i + 2] || p2;
      const c1x = p1[0] + (p2[0] - p0[0]) * smoothing;
      const c1y = p1[1] + (p2[1] - p0[1]) * smoothing;
      const c2x = p2[0] - (p3[0] - p1[0]) * smoothing;
      const c2y = p2[1] - (p3[1] - p1[1]) * smoothing;
      d += ` C ${c1x.toFixed(2)} ${c1y.toFixed(2)}, ${c2x.toFixed(2)} ${c2y.toFixed(2)}, ${p2[0].toFixed(2)} ${p2[1].toFixed(2)}`;
    }
    return d;
  }

  function lineChart(data, { width = 720, height = 210, pad = 26, fill = true, labels = true, valueKey = "revenue", labelKey = "label" } = {}) {
    if (!data?.length) return `<div class="empty"><span class="empty__mark">◍</span>no data yet</div>`;
    const values = data.map((row) => Number(row[valueKey] || 0));
    const max = Math.max(...values, 1);
    const min = 0;
    const inner = { w: width - pad * 2, h: height - pad * 1.6 };
    const pts = data.map((row, index) => [
      pad + (inner.w * index) / Math.max(1, data.length - 1),
      pad + inner.h - ((values[index] - min) / (max - min || 1)) * inner.h,
    ]);
    const line = smoothPath(pts);
    const area = `${line} L ${pts[pts.length - 1][0]} ${pad + inner.h} L ${pts[0][0]} ${pad + inner.h} Z`;
    const grid = [0.25, 0.5, 0.75, 1].map((f) => {
      const y = pad + inner.h - inner.h * f;
      return `<line class="axis" x1="${pad}" x2="${width - pad}" y1="${y.toFixed(1)}" y2="${y.toFixed(1)}"/>
              <text class="axis-label" x="${pad - 6}" y="${(y + 3).toFixed(1)}" text-anchor="end">${money(max * f, 0)}</text>`;
    }).join("");
    const dots = pts.map((p, i) => {
      const row = data[i];
      return `<circle class="pt" cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="3">
        <title>${esc(row[labelKey])} · ${money(values[i])} · ${row.tickets ?? ""}${row.tickets ? " tickets" : ""}</title>
      </circle>`;
    }).join("");
    const every = Math.max(1, Math.ceil(data.length / 7));
    const ticks = labels ? data.map((row, i) => (i % every === 0
      ? `<text class="axis-label" x="${pts[i][0].toFixed(1)}" y="${height - 2}" text-anchor="middle">${esc(row.day ?? row[labelKey])}</text>` : "")).join("") : "";
    return `<svg class="chart" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="revenue over time">
      <defs>
        <linearGradient id="revGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="rgba(216,178,106,.34)"/>
          <stop offset="100%" stop-color="rgba(216,178,106,0)"/>
        </linearGradient>
      </defs>
      ${grid}
      ${fill ? `<path class="area" d="${area}"/>` : ""}
      <path class="line" d="${line}" pathLength="1" style="stroke-dasharray:1;stroke-dashoffset:1;animation:draw 1.6s cubic-bezier(.22,1,.36,1) forwards"/>
      ${dots}${ticks}
      <style>@keyframes draw{to{stroke-dashoffset:0}}</style>
    </svg>`;
  }

  function barChart(data, { width = 720, height = 150, valueKey = "revenue", labelKey = "hour", tone = "gold" } = {}) {
    if (!data?.length) return "";
    const max = Math.max(...data.map((row) => Number(row[valueKey] || 0)), 1);
    const gap = 4;
    const bar = (width - gap * (data.length - 1)) / data.length;
    return `<svg class="chart chart--hourly" viewBox="0 0 ${width} ${height}" role="img" aria-label="by hour">
      <defs><linearGradient id="barGrad" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="${tone === "gold" ? "#f0dcb0" : "#9ce8c3"}"/>
        <stop offset="100%" stop-color="rgba(216,178,106,.18)"/>
      </linearGradient></defs>
      ${data.map((row, i) => {
        const value = Number(row[valueKey] || 0);
        const h = Math.max(value > 0 ? 3 : 0, (height - 22) * (value / max));
        const x = i * (bar + gap);
        return `<g><rect class="bar" x="${x.toFixed(1)}" y="${(height - 20 - h).toFixed(1)}" width="${bar.toFixed(1)}" height="${h.toFixed(1)}" rx="3">
          <title>${esc(row.label ?? row[labelKey])}:00 · ${money(value)} · ${row.tickets || 0} tickets</title></rect>
          ${i % 2 === 0 ? `<text class="axis-label" x="${(x + bar / 2).toFixed(1)}" y="${height - 6}" text-anchor="middle">${esc(row[labelKey])}</text>` : ""}</g>`;
      }).join("")}
    </svg>`;
  }

  function donut(slices, { size = 132, thickness = 15 } = {}) {
    const total = slices.reduce((sum, row) => sum + Number(row.value || 0), 0) || 1;
    const r = size / 2 - thickness / 2 - 2;
    const c = 2 * Math.PI * r;
    let offset = 0;
    const arcs = slices.map((row) => {
      const share = Number(row.value || 0) / total;
      const dash = `${(c * share - 2).toFixed(2)} ${(c * (1 - share) + 2).toFixed(2)}`;
      const node = `<circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="${row.color}"
        stroke-width="${thickness}" stroke-linecap="round" stroke-dasharray="${dash}"
        stroke-dashoffset="${(-offset).toFixed(2)}" transform="rotate(-90 ${size / 2} ${size / 2})">
        <title>${esc(row.name)} · ${(share * 100).toFixed(1)}%</title></circle>`;
      offset += c * share;
      return node;
    }).join("");
    return `<svg class="donut" viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" role="img" aria-label="chapter mix">
      <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="rgba(255,255,255,.05)" stroke-width="${thickness}"/>
      ${arcs}</svg>`;
  }

  function spark(values, { width = 96, height = 34, color = "#d8b26a" } = {}) {
    const nums = (values || []).map((v) => Number(v || 0));
    if (nums.length < 2) return "";
    const max = Math.max(...nums, 1);
    const pts = nums.map((value, i) => [
      (width * i) / (nums.length - 1),
      height - 2 - (value / max) * (height - 6),
    ]);
    return `<svg class="kpi__spark" viewBox="0 0 ${width} ${height}" aria-hidden="true">
      <path d="${smoothPath(pts)}" fill="none" stroke="${color}" stroke-width="1.6" opacity=".85" stroke-linecap="round"/>
      <circle cx="${pts[pts.length - 1][0].toFixed(1)}" cy="${pts[pts.length - 1][1].toFixed(1)}" r="2.2" fill="${color}"/>
    </svg>`;
  }

  /* ── 3D tilt ───────────────────────────────────────────────────────── */
  function tilt(root = document, selector = "[data-tilt]") {
    if (reduced()) return;
    const strength = 7;
    let items = $$(selector, root);
    if (!items.length) return;
    const track = new WeakMap();
    items.forEach((el) => {
      if (el.__tiltBound) return;
      el.__tiltBound = true;
      const glaze = el.querySelector(".tilt__glare");
      const target = { rx: 0, ry: 0, scale: 1 };
      const current = { rx: 0, ry: 0, scale: 1 };
      let raf = null;
      const loop = () => {
        current.rx = lerp(current.rx, target.rx, 0.16);
        current.ry = lerp(current.ry, target.ry, 0.16);
        current.scale = lerp(current.scale, target.scale, 0.16);
        el.style.transform = `perspective(900px) rotateX(${current.rx.toFixed(2)}deg) rotateY(${current.ry.toFixed(2)}deg) scale3d(${current.scale.toFixed(3)},${current.scale.toFixed(3)},1)`;
        if (Math.abs(current.rx - target.rx) > 0.02 || Math.abs(current.ry - target.ry) > 0.02) {
          raf = requestAnimationFrame(loop);
        } else { raf = null; }
      };
      el.addEventListener("pointermove", (event) => {
        const box = el.getBoundingClientRect();
        const px = (event.clientX - box.left) / box.width;
        const py = (event.clientY - box.top) / box.height;
        target.rx = (0.5 - py) * strength * 1.4;
        target.ry = (px - 0.5) * strength * 1.7;
        target.scale = 1.012;
        if (glaze) { glaze.style.setProperty("--mx", `${px * 100}%`); glaze.style.setProperty("--my", `${py * 100}%`); }
        el.style.setProperty("--mx", `${px * 100}%`);
        el.style.setProperty("--my", `${py * 100}%`);
        if (!raf) raf = requestAnimationFrame(loop);
      });
      el.addEventListener("pointerleave", () => {
        target.rx = 0; target.ry = 0; target.scale = 1;
        if (!raf) raf = requestAnimationFrame(loop);
      });
      track.set(el, { target, current });
    });
  }

  /* ── reveal on scroll ──────────────────────────────────────────────── */
  function reveal(root = document) {
    const items = $$("[data-reveal], [data-stagger]", root);
    if (!items.length) return;
    if (!("IntersectionObserver" in window) || reduced()) {
      items.forEach((el) => el.classList.add("is-in"));
      return;
    }
    const io = new IntersectionObserver((entries) => {
      entries.forEach((entry, index) => {
        if (!entry.isIntersecting) return;
        const el = entry.target;
        const delay = el.hasAttribute("data-stagger")
          ? Array.prototype.indexOf.call(el.parentElement.children, el) * 70 : 0;
        setTimeout(() => el.classList.add("is-in"), delay);
        io.unobserve(el);
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.12 });
    items.forEach((el) => io.observe(el));
  }

  /* ── pointer spotlight ─────────────────────────────────────────────── */
  function spotlight() {
    const node = $(".spotlight");
    if (!node || reduced()) return;
    document.body.classList.add("has-spotlight");
    let x = innerWidth / 2, y = innerHeight / 3, tx = x, ty = y, raf = null;
    addEventListener("pointermove", (e) => { tx = e.clientX; ty = e.clientY; if (!raf) raf = requestAnimationFrame(loop); }, { passive: true });
    const loop = () => {
      x = lerp(x, tx, 0.09); y = lerp(y, ty, 0.09);
      node.style.transform = `translate3d(${x}px, ${y}px, 0) translate(-50%, -50%)`;
      raf = (Math.abs(x - tx) > 0.6 || Math.abs(y - ty) > 0.6) ? requestAnimationFrame(loop) : null;
    };
    loop();
  }

  /* ── topbar state ──────────────────────────────────────────────────── */
  function stickyTopbar() {
    const bar = $("[data-topbar]");
    if (!bar) return;
    const onScroll = () => bar.classList.toggle("is-stuck", scrollY > 24);
    addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }

  /* ── drawer (callable: RMS.drawer(html, opts) · RMS.drawer.close()) ── */
  function drawerClose() {
    $("[data-drawer]")?.classList.remove("is-open");
    $("[data-scrim]")?.classList.remove("is-open");
    document.body.style.overflow = "";
  }

  function drawerOpen(html, { title = "", sub = "", avatar = "◆", foot = "" } = {}) {
    const el = $("[data-drawer]");
    if (!el) { console.warn("[RMS] no drawer on this page"); return; }
    $("[data-drawer-title]", el).textContent = title;
    $("[data-drawer-sub]", el).textContent = sub;
    $("[data-drawer-avatar]", el).textContent = avatar;
    $("[data-drawer-body]", el).innerHTML = html;
    const footEl = $("[data-drawer-foot]", el);
    if (footEl) footEl.innerHTML = foot;
    el.classList.add("is-open");
    $("[data-scrim]")?.classList.add("is-open");
    document.body.style.overflow = "hidden";
    $("[data-drawer-body]", el).scrollTop = 0;
  }
  drawerOpen.close = drawerClose;

  document.addEventListener("click", (event) => {
    if (event.target.closest("[data-drawer-close]") || event.target.matches("[data-scrim]")) drawerClose();
  });
  addEventListener("keydown", (event) => { if (event.key === "Escape") drawerClose(); });

  /* ── modal (guest menu) ────────────────────────────────────────────── */
  function modal(node) {
    const el = node || $("[data-modal]");
    if (!el) return { open() {}, close() {} };
    const show = () => {
      el.hidden = false;
      el.style.cssText = "position:fixed;inset:0;z-index:8500;display:grid;place-items:center;padding:20px;" +
        "background:rgba(4,5,7,.74);backdrop-filter:blur(8px);opacity:0;transition:opacity .35s";
      requestAnimationFrame(() => { el.style.opacity = "1"; el.firstElementChild.animate?.(
        [{ transform: "translateY(18px) scale(.97)", opacity: 0 }, { transform: "none", opacity: 1 }],
        { duration: 520, easing: "cubic-bezier(.22,1,.36,1)" }); });
    };
    const hide = () => { el.style.opacity = "0"; setTimeout(() => { el.hidden = true; }, 280); };
    el.addEventListener("click", (event) => { if (event.target === el || event.target.closest("[data-action=close-modal]")) hide(); });
    return { open: show, close: hide };
  }

  const boot = (fn) => (document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", fn) : fn());

  window.RMS = {
    $, $$, api, toast, money, int, timeAgo, counter, tilt, reveal, spotlight, stickyTopbar,
    charts: { line: lineChart, bar: barChart, donut, spark }, drawer: drawerOpen, drawerClose, modal, boot,
    state, clamp, lerp, easeOut, debounce, esc, reduced, csrf,
  };

  boot(() => { tilt(); reveal(); stickyTopbar(); });
})();
