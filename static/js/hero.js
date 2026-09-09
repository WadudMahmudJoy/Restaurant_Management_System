/* ============================================================================
   hero.js · the landing / sign-in WebGL scene
   ---------------------------------------------------------------------------
   Reads the live menu from an inline JSON block and places that many plated
   dishes on a marble turntable. Drag to orbit, hover a plate to surface its
   real price, click to jump to the matching card on the page.
   ========================================================================== */
import * as THREE from "three";
import {
  createStage, rigLights, studioEnvironment, materials, platedDish, turntable,
  dustParticles, contactShadowTexture, DISH_KEYS, GOLD,
} from "./scenes.js";

/* Module scripts have no document.currentScript, so the mode is read from the
   canvas host that this page actually rendered — plus an optional data-mode on
   the host itself for anything unusual (e.g. an embed inside the dashboard). */
const AUTH_HOST = document.getElementById("auth-3d");
const LANDING_HOST = document.getElementById("hero-3d");
const HOST = AUTH_HOST || LANDING_HOST;
const MODE = (HOST && HOST.dataset.mode) || (AUTH_HOST ? "auth" : "landing");
const LABEL = document.querySelector("[data-orbit-label]");

function readDishes() {
  const node = document.querySelector('[data-role="hero-dishes"]');
  if (!node) return [];
  try { return JSON.parse(node.textContent || "[]"); } catch { return []; }
}

const SPRING = 0.085;
const damp = (current, target, k = SPRING) => current + (target - current) * k;

function boot() {
  if (!HOST) return;
  const dishes = readDishes();
  let gl = null;
  try {
    gl = document.createElement("canvas").getContext("webgl2") || document.createElement("canvas").getContext("webgl");
  } catch { gl = null; }
  if (!gl) {
    HOST.insertAdjacentHTML("beforeend",
      `<div style="position:absolute;inset:0;background:
        radial-gradient(60% 50% at 50% 60%, rgba(216,178,106,.22), transparent 70%),
        url('/media/menu/seed/ribeye-au-poivre.jpg') center/cover;opacity:.5;filter:saturate(.9)"></div>`);
    return;
  }

  const stage = createStage(HOST, { exposure: MODE === "auth" ? 1.12 : 1.02 });
  const { renderer, scene, camera } = stage;
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  scene.environment = studioEnvironment(renderer);
  const M = materials(scene.environment);
  rigLights(scene, { key: MODE === "auth" ? 2.8 : 2.4 });

  /* ── stage contents ─────────────────────────────────────────────────── */
  const world = new THREE.Group();
  scene.add(world);
  const deck = turntable(M, MODE === "auth" ? 2.6 : 3.35);
  world.add(deck);
  const shadowTex = contactShadowTexture();

  const ring = new THREE.Group();
  world.add(ring);
  const pods = [];
  const count = MODE === "auth" ? 3 : Math.max(3, Math.min(6, dishes.length || 4));
  for (let i = 0; i < count; i += 1) {
    const dish = dishes[i % Math.max(1, dishes.length)] || { name: "Chef's plate", price: "0.00" };
    const kind = DISH_KEYS[i % DISH_KEYS.length];
    const pod = platedDish(M, {
      kind,
      label: { name: dish.name || "Chef's plate", price: dish.price, chapter: dish.chapter, accent: dish.accent || "#d8b26a", id: dish.id },
      shadowTex,
    });
    const angle = (i / count) * Math.PI * 2 - Math.PI / 2;
    const radius = MODE === "auth" ? 1.5 : 2.02;
    pod.position.set(Math.cos(angle) * radius, 0.09, Math.sin(angle) * radius);
    pod.rotation.y = -angle + Math.PI / 2;
    pod.scale.setScalar(0.001);
    pod.userData.targetScale = 0.82;
    pod.userData.bobPhase = i * 1.7;
    pod.userData.baseY = pod.position.y;
    ring.add(pod);
    pods.push(pod);
  }

  // hero centrepiece: a big plated dish the camera orbits
  const centre = platedDish(M, { kind: "steak", label: null, shadowTex });
  centre.scale.setScalar(MODE === "auth" ? 0.9 : 1.16);
  centre.position.y = 0.12;
  centre.userData.pickable = false;
  if (MODE === "auth") { pods.forEach((p) => p.scale.setScalar(0.001)); }
  world.add(centre);

  // gold chandelier ring above the pass
  const halo = new THREE.Mesh(new THREE.TorusGeometry(MODE === "auth" ? 2.1 : 2.9, 0.02, 8, 128), M.emissive(GOLD, 1.9));
  halo.rotation.x = Math.PI / 2;
  halo.position.y = 2.5;
  scene.add(halo);
  const halo2 = new THREE.Mesh(new THREE.TorusGeometry(MODE === "auth" ? 2.7 : 3.9, 0.012, 8, 128), M.emissive(0x86a6e8, 1.1));
  halo2.rotation.x = Math.PI / 2.15;
  halo2.position.y = 3.1;
  scene.add(halo2);

  const dust = dustParticles(MODE === "auth" ? 260 : 520, MODE === "auth" ? 7 : 11);
  scene.add(dust);

  // floor haze disc so the deck floats in a room, not the void
  const haze = new THREE.Mesh(
    new THREE.CircleGeometry(9, 64),
    new THREE.MeshBasicMaterial({ color: 0x0a0c10, transparent: true, opacity: 0.9 }),
  );
  haze.rotation.x = -Math.PI / 2;
  haze.position.y = -0.5;
  scene.add(haze);

  /* ── input: orbit, drag, hover, click ───────────────────────────────── */
  const pointer = { x: 0, y: 0, nx: 0, ny: 0, down: false, moved: 0, last: { x: 0, y: 0 } };
  const orbit = { yaw: 0, pitch: 0.0, targetYaw: 0, targetPitch: 0, zoom: 0, targetZoom: 0 };
  const raycaster = new THREE.Raycaster();
  let hovered = null;

  const el = renderer.domElement;
  el.style.touchAction = "pan-y";

  HOST.addEventListener("pointermove", (event) => {
    const box = HOST.getBoundingClientRect();
    pointer.x = event.clientX;
    pointer.y = event.clientY;
    pointer.nx = ((event.clientX - box.left) / box.width) * 2 - 1;
    pointer.ny = -(((event.clientY - box.top) / box.height) * 2 - 1);
    if (pointer.down) {
      const dx = event.clientX - pointer.last.x;
      const dy = event.clientY - pointer.last.y;
      pointer.moved += Math.abs(dx) + Math.abs(dy);
      orbit.targetYaw += dx * 0.006;
      orbit.targetPitch = THREE.MathUtils.clamp(orbit.targetPitch + dy * 0.0035, -0.12, 0.42);
      pointer.last = { x: event.clientX, y: event.clientY };
    }
  }, { passive: true });

  HOST.addEventListener("pointerdown", (event) => {
    pointer.down = true;
    pointer.moved = 0;
    pointer.last = { x: event.clientX, y: event.clientY };
    el.style.cursor = "grabbing";
  });
  addEventListener("pointerup", () => { pointer.down = false; el.style.cursor = ""; }, { passive: true });
  HOST.addEventListener("wheel", (event) => {
    if (MODE === "auth") return;
    if (event.deltaY > 40) {
      orbit.targetZoom = THREE.MathUtils.clamp(orbit.targetZoom + 0.6, 0, 2.4);
    }
  }, { passive: true });

  HOST.addEventListener("click", () => {
    if (pointer.moved > 12 || !hovered) return;
    const id = hovered.userData.label?.id;
    const target = id && document.querySelector(`[data-dish-id="${id}"]`);
    if (target) {
      target.scrollIntoView({ behavior: "smooth", block: "center" });
      target.classList.add("flash");
      setTimeout(() => target.classList.remove("flash"), 1200);
    }
  });

  /* ── loop ───────────────────────────────────────────────────────────── */
  const clock = new THREE.Clock();
  let spin = reduced ? 0.02 : 0.14;
  let visible = true;
  let quality = 1;
  let fpsAvg = 60;

  const labelWorld = new THREE.Vector3();

  function frame() {
    const dt = Math.min(0.05, clock.getDelta());
    const t = clock.elapsedTime;
    fpsAvg = fpsAvg * 0.92 + (1 / Math.max(dt, 0.001)) * 0.08;

    // adaptive resolution keeps 60fps on laptops with dpr 3
    if (fpsAvg < 44 && quality > 0.72) { quality = 0.72; renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.25)); }
    if (fpsAvg > 57 && quality < 1) { quality = 1; renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75)); }

    // intro: pods pop in, deck spins down
    pods.forEach((pod, i) => {
      const delay = 0.28 + i * 0.13;
      const age = Math.max(0, Math.min(1, (t - delay) / 0.9));
      const eased = 1 - Math.pow(1 - age, 3);
      const wanted = pod.userData.targetScale * (pod === hovered ? 1.09 : 1) * (reduced ? 1 : eased);
      pod.scale.setScalar(damp(pod.scale.x, wanted, 0.16));
      pod.position.y = pod.userData.baseY + (reduced ? 0 : Math.sin(t * 0.9 + pod.userData.bobPhase) * 0.012);
    });
    spin = damp(spin, reduced ? 0.02 : 0.13, 0.02);
    if (!pointer.down) orbit.targetYaw += dt * spin;
    ring.rotation.y = damp(ring.rotation.y, orbit.targetYaw, 0.09);
    deck.rotation.y = ring.rotation.y * 0.35;
    centre.rotation.y = damp(centre.rotation.y, -orbit.targetYaw * 0.6 + t * 0.06, 0.08);
    centre.position.y = 0.12 + (reduced ? 0 : Math.sin(t * 0.8) * 0.014);

    orbit.yaw = damp(orbit.yaw, orbit.targetYaw, 0.12);
    orbit.pitch = damp(orbit.pitch, orbit.targetPitch, 0.12);
    orbit.zoom = damp(orbit.zoom, orbit.targetZoom, 0.08);

    const drift = reduced ? 0 : 1;
    const camRadius = (MODE === "auth" ? 6.1 : 7.5) + orbit.zoom;
    const px = Math.sin(orbit.yaw) * camRadius + pointer.nx * 0.42 * drift;
    const pz = Math.cos(orbit.yaw) * camRadius;
    const py = (MODE === "auth" ? 3.1 : 3.55) + orbit.pitch * 3.1 + pointer.ny * 0.3 * drift;
    camera.position.set(px, py, pz);
    camera.lookAt(0, 0.62, 0);
    camera.fov = damp(camera.fov, MODE === "auth" ? 30 : 34 - orbit.zoom * 0.8, 0.06);
    camera.updateProjectionMatrix();

    halo.rotation.z += dt * 0.06;
    halo2.rotation.z -= dt * 0.04;
    halo.position.y = 2.5 + (reduced ? 0 : Math.sin(t * 0.6) * 0.06);

    dust.rotation.y += dt * 0.012;
    const seeds = dust.userData.seeds;
    const pos = dust.geometry.attributes.position;
    for (let i = 0; i < pos.count; i += 1) {
      const y = pos.getY(i) + dt * (0.06 + seeds[i] * 0.12);
      pos.setY(i, y > 6.4 ? -1.6 : y);
    }
    pos.needsUpdate = true;

    // hover raycast (cheap: only pods)
    if (!pointer.down && LABEL) {
      raycaster.setFromCamera(new THREE.Vector2(pointer.nx, pointer.ny), camera);
      const hit = raycaster.intersectObjects(pods, true)[0];
      const pod = hit ? hit.object.parent : null;
      const next = pod && pod.userData.label ? pod : null;
      if (next !== hovered) {
        hovered = next;
        el.style.cursor = hovered ? "pointer" : "";
        LABEL.classList.toggle("is-on", Boolean(hovered));
        if (hovered) {
          const info = hovered.userData.label;
          LABEL.innerHTML = `<span style="color:${info.accent}">${info.chapter || "dish"}</span>
            <span>${info.name}</span> <b>$${Number(info.price || 0).toFixed(2)}</b>`;
        }
      }
      if (hovered) {
        hovered.getWorldPosition(labelWorld);
        labelWorld.y += 0.72;
        labelWorld.project(camera);
        const box = HOST.getBoundingClientRect();
        LABEL.style.left = `${((labelWorld.x + 1) / 2) * box.width}px`;
        LABEL.style.top = `${((1 - labelWorld.y) / 2) * box.height}px`;
      }
    }

    // scroll dolly on the landing page
    if (MODE !== "auth") {
      const progress = Math.min(1, scrollY / Math.max(1, innerHeight));
      world.position.y = -progress * 1.5;
      world.rotation.x = progress * 0.14;
      scene.traverse(() => {});
      renderer.toneMappingExposure = 1.02 - progress * 0.3;
    }

    if (visible) renderer.render(scene, camera);
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  /* ── pause when off-screen or hidden ───────────────────────────────── */
  if ("IntersectionObserver" in window) {
    new IntersectionObserver((entries) => { visible = entries[0].isIntersecting; }, { threshold: 0.01 }).observe(HOST);
  }
  document.addEventListener("visibilitychange", () => { visible = !document.hidden; });
  addEventListener("pagehide", () => { stage.dispose(); renderer.forceContextLoss?.(); }, { once: true });
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
else boot();
