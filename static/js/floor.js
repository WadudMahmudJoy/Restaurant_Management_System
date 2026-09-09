/* ============================================================================
   floor.js · the live floor plan in WebGL
   Reads table state from the API and renders the room in 3D: rounded tables,
   chairs, status light rings, a soft hover tooltip and a lift for anything
   with a live ticket. Click a table and the page receives `rms:table`.
   ========================================================================== */
import * as THREE from "three";
import { createStage, rigLights, studioEnvironment, materials, contactShadowTexture } from "./scenes.js";

const TONES = {
  idle: 0x4ecb8f, good: 0x4ecb8f, info: 0x7aa2ff, warn: 0xf2b544, hot: 0xff6b6b, bad: 0x8b8f98,
};

function roundedRect(w, h, r) {
  const s = new THREE.Shape();
  const x = -w / 2;
  const y = -h / 2;
  s.moveTo(x + r, y);
  s.lineTo(x + w - r, y);
  s.quadraticCurveTo(x + w, y, x + w, y + r);
  s.lineTo(x + w, y + h - r);
  s.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  s.lineTo(x + r, y + h);
  s.quadraticCurveTo(x, y + h, x, y + h - r);
  s.lineTo(x, y + r);
  s.quadraticCurveTo(x, y, x + r, y);
  return s;
}

class Floor {
  constructor(container) {
    this.container = container;
    this.tables = new Map();
    this.group = new THREE.Group();
    this.hovered = null;
    this.yaw = -0.42;
    this.targetYaw = -0.42;
    this.tip = container.querySelector('[data-role="floor-tip"]');
    this.visible = true;
    this.clock = new THREE.Clock();
    this.raycaster = new THREE.Raycaster();
    this.pointer = new THREE.Vector2(-2, -2);
    this.dragging = false;
    this.dragged = 0;
    this.signature = "";

    const stage = createStage(container, { exposure: 1.15, shadow: false });
    this.stage = stage;
    const env = studioEnvironment(stage.renderer);
    stage.scene.environment = env;
    this.M = materials(env);
    rigLights(stage.scene, { key: 1.7, gold: 9, teal: 6 });
    this.shadowTex = contactShadowTexture(96);

    const floor = new THREE.Mesh(
      new THREE.PlaneGeometry(26, 20),
      new THREE.MeshPhysicalMaterial({ color: 0x0b0d11, roughness: 0.62, metalness: 0.08, envMap: env }),
    );
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = -0.02;
    stage.scene.add(floor);

    const grid = new THREE.GridHelper(26, 26, 0x1e232c, 0x161a21);
    grid.material.transparent = true;
    grid.material.opacity = 0.45;
    grid.position.y = 0.001;
    stage.scene.add(grid);
    stage.scene.add(this.group);
    stage.camera.position.set(0, 7.6, 9.6);
    stage.camera.lookAt(0, 0.2, 0);

    this.bind();
    this.loop();

    if ("IntersectionObserver" in window) {
      this.io = new IntersectionObserver((entries) => { this.visible = entries[0].isIntersecting; }, { threshold: 0.02 });
      this.io.observe(container);
    }
    document.addEventListener("visibilitychange", () => { this.visible = !document.hidden; });
  }

  bind() {
    const c = this.container;
    c.style.cursor = "grab";
    c.addEventListener("pointermove", (event) => {
      const box = c.getBoundingClientRect();
      this.pointer.set(
        ((event.clientX - box.left) / box.width) * 2 - 1,
        -((event.clientY - box.top) / box.height) * 2 + 1,
      );
      this.lastClient = { x: event.clientX - box.left, y: event.clientY - box.top };
      if (this.dragging) {
        const dx = event.clientX - (this.lastX ?? event.clientX);
        this.dragged += Math.abs(dx);
        this.targetYaw += dx * 0.006;
      }
      this.lastX = event.clientX;
    }, { passive: true });

    c.addEventListener("pointerdown", (event) => {
      this.dragging = true;
      this.dragged = 0;
      this.lastX = event.clientX;
    });
    addEventListener("pointerup", () => { this.dragging = false; }, { passive: true });
    c.addEventListener("pointerleave", () => {
      this.dragging = false;
      this.pointer.set(-2, -2);
      this.tip?.classList.remove("is-on");
    });
    c.addEventListener("click", () => {
      if (this.hovered && this.dragged < 8) {
        window.dispatchEvent(new CustomEvent("rms:table", {
          detail: { id: this.hovered.userData.id, label: this.hovered.userData.label, order: this.hovered.userData.order },
        }));
      }
    });
  }

  setData(rows) {
    if (!Array.isArray(rows)) return;
    const signature = rows.map((row) => `${row.id}:${row.x}:${row.y}:${row.seats}`).join("|");
    if (signature !== this.signature) {
      this.signature = signature;
      this.build(rows);
    }
    rows.forEach((row) => this.apply(row));
  }

  build(rows) {
    for (const node of [...this.group.children]) {
      node.traverse((mesh) => { mesh.geometry?.dispose?.(); if (mesh.material && !Array.isArray(mesh.material)) mesh.material.dispose?.(); });
      this.group.remove(node);
    }
    this.tables.clear();

    const xs = rows.map((r) => Number(r.x) || 0);
    const ys = rows.map((r) => Number(r.y) || 0);
    const cx = ((Math.min(...xs, 0) + Math.max(...xs, 0)) / 2) || 0;
    const cy = ((Math.min(...ys, 0) + Math.max(...ys, 0)) / 2) || 0;
    const spread = Math.max(...xs.map((x) => Math.abs(x - cx)), 1) + 1.6;
    const depth = Math.max(...ys.map((y) => Math.abs(y - cy)), 1) + 1.6;
    this.stage.camera.position.set(0, Math.max(6.4, depth * 1.5 + 4), spread * 1.75 + 4.2);
    this.stage.camera.lookAt(0, 0.2, 0);

    rows.forEach((row) => {
      const node = new THREE.Group();
      node.position.set((row.x ?? 0) - cx, 0, -((row.y ?? 0) - cy));
      node.rotation.y = THREE.MathUtils.degToRad(-(row.rotation || 0));

      const seats = Math.max(1, Math.min(12, row.seats || 2));
      const w = seats > 4 ? 1.6 : seats > 2 ? 1.25 : 0.92;
      const h = seats > 4 ? 1.05 : 0.84;

      const topGeo = new THREE.ExtrudeGeometry(roundedRect(w, h, 0.18), {
        depth: 0.1, bevelEnabled: true, bevelThickness: 0.02, bevelSize: 0.02, bevelSegments: 2,
      });
      topGeo.rotateX(-Math.PI / 2);
      const top = new THREE.Mesh(topGeo, this.M.ceramicDark);
      top.position.y = 0.08;
      node.add(top);

      const ringGeo = new THREE.ExtrudeGeometry(roundedRect(w + 0.18, h + 0.18, 0.22), { depth: 0.02, bevelEnabled: false });
      ringGeo.rotateX(-Math.PI / 2);
      const ring = new THREE.Mesh(ringGeo, new THREE.MeshBasicMaterial({ color: 0x8b8f98, transparent: true, opacity: 0.9 }));
      ring.position.y = 0.02;
      node.add(ring);

      const halo = new THREE.Mesh(
        new THREE.CircleGeometry(Math.max(w, h) * 1.25, 26),
        new THREE.MeshBasicMaterial({ color: 0x8b8f98, transparent: true, opacity: 0.14, depthWrite: false }),
      );
      halo.rotation.x = -Math.PI / 2;
      halo.position.y = 0.004;
      node.add(halo);

      const shadow = new THREE.Mesh(
        new THREE.PlaneGeometry(w * 3, h * 3),
        new THREE.MeshBasicMaterial({ map: this.shadowTex, transparent: true, opacity: 0.45, depthWrite: false }),
      );
      shadow.rotation.x = -Math.PI / 2;
      shadow.position.y = 0.0015;
      node.add(shadow);

      for (let i = 0; i < seats; i += 1) {
        const a = (i / seats) * Math.PI * 2 + 0.2;
        const chair = new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.08, 0.2), this.M.stone);
        chair.position.set(Math.cos(a) * (w / 2 + 0.28), 0.05, Math.sin(a) * (h / 2 + 0.28));
        chair.rotation.y = -a;
        node.add(chair);
      }

      node.userData = { id: row.id, label: row.label, ring, halo, top, seats, order: row.order, pickable: true };
      this.group.add(node);
      this.tables.set(row.id, node);
    });
  }

  apply(row) {
    const node = this.tables.get(row.id);
    if (!node) return;
    const color = new THREE.Color(TONES[row.tone] || 0x8b8f98);
    node.userData.order = row.order;
    node.userData.ring.material.color.copy(color);
    node.userData.halo.material.color.copy(color);
    node.userData.pulse = row.order?.late ? 1 : 0;
    node.userData.lift = row.order ? 0.06 : 0;
    node.userData.tip = `${row.label} · ${row.seats} seats · ${row.status}`
      + (row.order ? ` · ${row.order.number} · ${row.order.age}` : "");
  }

  loop() {
    const step = () => {
      if (this.visible) {
        const t = this.clock.getElapsedTime();
        this.yaw += (this.targetYaw - this.yaw) * 0.1;
        this.group.rotation.y = this.yaw;

        this.tables.forEach((node) => {
          const lift = node.userData.lift || 0;
          node.position.y += (lift - node.position.y) * 0.14;
          const base = node.userData.pulse ? 0.16 + Math.abs(Math.sin(t * 2.6)) * 0.32 : 0.12;
          node.userData.halo.material.opacity = base;
        });

        this.raycaster.setFromCamera(this.pointer, this.stage.camera);
        const hit = this.raycaster.intersectObjects(this.group.children, true)[0];
        let node = hit ? hit.object.parent : null;
        if (node && !node.userData?.pickable) node = null;
        if (node !== this.hovered) {
          this.hovered = node;
          this.container.style.cursor = node ? "pointer" : "grab";
        }
        if (this.tip) {
          if (this.hovered && this.lastClient) {
            this.tip.textContent = this.hovered.userData.tip || this.hovered.userData.label;
            this.tip.style.transform = `translate(${this.lastClient.x + 12}px, ${this.lastClient.y - 30}px)`;
            this.tip.classList.add("is-on");
          } else {
            this.tip.classList.remove("is-on");
          }
        }
        this.stage.renderer.render(this.stage.scene, this.stage.camera);
      }
      requestAnimationFrame(step);
    };
    step();
  }
}

const floors = [];
function init() {
  document.querySelectorAll("[data-role='floor']").forEach((el) => {
    if (el.__floor) return;
    try {
      el.__floor = new Floor(el);
      floors.push(el.__floor);
    } catch (err) {
      console.warn("[RMS] floor disabled:", err?.message);
      el.insertAdjacentHTML("beforeend", '<div class="empty" style="height:200px"><span class="empty__mark">◍</span>WebGL is unavailable — the table list below still works.</div>');
    }
  });
}

const setAll = (rows) => floors.forEach((floor) => floor.setData(rows));

const ready = () => {
  init();
  window.RMS = window.RMS || {};
  window.RMS.floor = { set: setAll, all: () => floors, reinit: init };
  if (!window.RMS_SKIP_FLOOR_FETCH) {
    fetch("/api/floor/", { credentials: "same-origin" })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => { if (data?.floor) setAll(data.floor); })
      .catch(() => {});
  }
};

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", ready);
else ready();

export { Floor, setAll };
