/* ============================================================================
   Lumière RMS · WebGL kitchen (three.js, core build only — no addons)
   ----------------------------------------------------------------------------
   A hand-built, stylized still-life: a marble turntable carrying plated dishes.
   Everything is primitive geometry + physical materials, so there is nothing to
   download, no glTF loader, no build step. Exports factories used by hero.js and
   floor.js.
   ========================================================================== */
import * as THREE from "three";

export const GOLD = 0xd8b26a;

/* ── renderer + stage ────────────────────────────────────────────────── */
export function createStage(container, { exposure = 1.05, shadow = true } = {}) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
  renderer.setSize(container.clientWidth || 800, container.clientHeight || 600, false);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = exposure;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  if (shadow) {
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  }
  renderer.domElement.style.display = "block";
  container.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0x07080a, 0.052);
  const camera = new THREE.PerspectiveCamera(34, aspect(container), 0.1, 100);
  camera.position.set(0, 3.6, 7.6);

  const fit = () => {
    const w = container.clientWidth || 800;
    const h = container.clientHeight || 600;
    renderer.setSize(w, h, false);
    camera.aspect = aspect(container, w, h);
    camera.updateProjectionMatrix();
  };
  const ro = new ResizeObserver(fit);
  ro.observe(container);
  fit();

  return { renderer, scene, camera, container, fit, dispose: () => { ro.disconnect(); renderer.dispose(); } };
}

const aspect = (container, w, h) => (w || container.clientWidth || 1) / (h || container.clientHeight || 1);

/* ── studio lighting rig ─────────────────────────────────────────────── */
export function rigLights(scene, { key = 2.4, gold = 22, teal = 12 } = {}) {
  const hemi = new THREE.HemisphereLight(0x9fb6d9, 0x120e09, 0.45);
  scene.add(hemi);

  const ambient = new THREE.AmbientLight(0xffffff, 0.16);
  scene.add(ambient);

  const keyLight = new THREE.DirectionalLight(0xfff4e2, key);
  keyLight.position.set(4.2, 7.4, 3.4);
  keyLight.castShadow = true;
  keyLight.shadow.mapSize.set(1024, 1024);
  keyLight.shadow.camera.near = 0.6;
  keyLight.shadow.camera.far = 26;
  keyLight.shadow.camera.left = -8;
  keyLight.shadow.camera.right = 8;
  keyLight.shadow.camera.top = 8;
  keyLight.shadow.camera.bottom = -8;
  keyLight.shadow.bias = -0.0016;
  keyLight.shadow.radius = 2.4;
  scene.add(keyLight);

  const goldLight = new THREE.PointLight(GOLD, gold, 16, 2);
  goldLight.position.set(-3.6, 2.2, 2.4);
  scene.add(goldLight);

  const tealLight = new THREE.PointLight(0x6f8fd8, teal, 18, 2);
  tealLight.position.set(3.4, 1.4, -3.2);
  scene.add(tealLight);

  const rim = new THREE.SpotLight(0xffd79a, 26, 22, Math.PI / 5.2, 0.85, 2);
  rim.position.set(0, 7.2, -4.4);
  scene.add(rim, rim.target);

  return { hemi, keyLight, goldLight, tealLight, rim };
}

/* ── image-based lighting without an HDR file ────────────────────────── */
export function studioEnvironment(renderer, size = 256) {
  const canvas = document.createElement("canvas");
  canvas.width = size * 2;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  const sky = ctx.createLinearGradient(0, 0, 0, size);
  sky.addColorStop(0, "#2a2f3a");
  sky.addColorStop(0.42, "#12151b");
  sky.addColorStop(1, "#07080a");
  ctx.fillStyle = sky;
  ctx.fillRect(0, 0, size * 2, size);
  // three soft "softboxes" the metal and glaze will reflect
  const boxes = [[0.18, 0.26, 0.16, "rgba(255,247,232,.95)"], [0.62, 0.2, 0.12, "rgba(216,178,106,.85)"],
                 [0.86, 0.42, 0.09, "rgba(150,180,255,.55)"]];
  boxes.forEach(([cx, cy, r, color]) => {
    const g = ctx.createRadialGradient(size * 2 * cx, size * cy, 0, size * 2 * cx, size * cy, size * 2 * r);
    g.addColorStop(0, color);
    g.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, size * 2, size);
  });
  const texture = new THREE.CanvasTexture(canvas);
  texture.mapping = THREE.EquirectangularReflectionMapping;
  texture.colorSpace = THREE.SRGBColorSpace;
  const pmrem = new THREE.PMREMGenerator(renderer);
  const env = pmrem.fromEquirectangular(texture).texture;
  pmrem.dispose();
  texture.dispose();
  return env;
}

/* ── material library ────────────────────────────────────────────────── */
export function materials(env) {
  const mat = (opts) => {
    const m = new THREE.MeshPhysicalMaterial(opts);
    m.envMap = env;
    m.envMapIntensity = opts.metalness ? 1.15 : 0.55;
    return m;
  };
  return {
    gold: mat({ color: GOLD, metalness: 1, roughness: 0.22, clearcoat: 0.6, clearcoatRoughness: 0.25 }),
    brassDark: mat({ color: 0x8a6a34, metalness: 1, roughness: 0.45 }),
    ceramic: mat({ color: 0xf3efe6, metalness: 0, roughness: 0.32, clearcoat: 1, clearcoatRoughness: 0.16, sheen: 0.4 }),
    ceramicDark: mat({ color: 0x1d2126, metalness: 0.1, roughness: 0.36, clearcoat: 1, clearcoatRoughness: 0.12 }),
    stone: mat({ color: 0x0e1013, metalness: 0.08, roughness: 0.62, clearcoat: 0.5, clearcoatRoughness: 0.5 }),
    glass: mat({ color: 0xffffff, metalness: 0, roughness: 0.04, transmission: 0.94, thickness: 0.5, ior: 1.45, transparent: true }),
    sauce: (color) => mat({ color, metalness: 0, roughness: 0.22, clearcoat: 1, clearcoatRoughness: 0.1 }),
    food: (color, roughness = 0.55) => mat({ color, metalness: 0, roughness, sheen: 0.5, sheenColor: new THREE.Color(0xffffff) }),
    leaf: mat({ color: 0x4f7d43, metalness: 0, roughness: 0.62, side: THREE.DoubleSide }),
    emissive: (color, intensity = 1.6) => new THREE.MeshBasicMaterial({ color: new THREE.Color(color).multiplyScalar(intensity) }),
  };
}

/* ── geometry helpers ────────────────────────────────────────────────── */
export function plateGeometry({ outer = 1.0, lip = 0.13, well = 0.1, walled = false } = {}) {
  const pts = [];
  const steps = 26;
  pts.push(new THREE.Vector2(0.0001, 0));
  pts.push(new THREE.Vector2(outer * 0.34, 0));
  pts.push(new THREE.Vector2(outer * 0.62, well * 0.35));
  for (let i = 0; i <= 8; i += 1) {
    const t = i / 8;
    const r = outer * (0.62 + 0.38 * t);
    const y = well * 0.35 + lip * Math.sin(t * Math.PI * 0.5);
    pts.push(new THREE.Vector2(r, y));
  }
  if (walled) pts.push(new THREE.Vector2(outer * 0.98, lip * 1.7));
  pts.push(new THREE.Vector2(outer, lip * 1.06));
  pts.push(new THREE.Vector2(outer * 0.985, lip * 0.5));
  pts.push(new THREE.Vector2(outer * 0.9, lip * 0.06));
  const geo = new THREE.LatheGeometry(pts, steps * 2);
  geo.computeVertexNormals();
  return geo;
}

/** Soft contact shadow / ambient occlusion puddle under an object. */
export function contactShadowTexture(size = 128) {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d");
  const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  g.addColorStop(0, "rgba(0,0,0,.72)");
  g.addColorStop(0.5, "rgba(0,0,0,.28)");
  g.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size, size);
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

export function dustParticles(count = 520, spread = 11) {
  const positions = new Float32Array(count * 3);
  const seeds = new Float32Array(count);
  for (let i = 0; i < count; i += 1) {
    const r = Math.sqrt(Math.random()) * spread;
    const a = Math.random() * Math.PI * 2;
    positions[i * 3] = Math.cos(a) * r;
    positions[i * 3 + 1] = -1.4 + Math.random() * 7.4;
    positions[i * 3 + 2] = Math.sin(a) * r;
    seeds[i] = Math.random();
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geo.setAttribute("aSeed", new THREE.BufferAttribute(seeds, 1));
  const material = new THREE.PointsMaterial({
    color: GOLD, size: 0.03, transparent: true, opacity: 0.6,
    blending: THREE.AdditiveBlending, depthWrite: false, sizeAttenuation: true,
  });
  const points = new THREE.Points(geo, material);
  points.userData.seeds = seeds;
  return points;
}

/* ── the dishes ──────────────────────────────────────────────────────── */
/** Each builder returns a THREE.Group sized to sit on a plate of radius 1. */
const DISH_BUILDERS = {
  burger(M) {
    const g = new THREE.Group();
    const bun = M.food(0xd9a15b, 0.72);
    const bottom = new THREE.Mesh(new THREE.CylinderGeometry(0.6, 0.62, 0.2, 32), bun);
    bottom.position.y = 0.1;
    const patty = new THREE.Mesh(new THREE.CylinderGeometry(0.63, 0.6, 0.17, 28), M.food(0x5b3826, 0.68));
    patty.position.y = 0.29;
    const cheese = new THREE.Mesh(new THREE.BoxGeometry(1.02, 0.035, 1.02), M.sauce(0xe9a83a));
    cheese.position.y = 0.4;
    cheese.rotation.y = Math.PI / 4;
    const lettuce = new THREE.Mesh(new THREE.TorusGeometry(0.56, 0.075, 8, 26), M.leaf);
    lettuce.rotation.x = Math.PI / 2;
    lettuce.position.y = 0.45;
    const top = new THREE.Mesh(new THREE.SphereGeometry(0.6, 32, 18, 0, Math.PI * 2, 0, Math.PI / 2), bun);
    top.scale.set(1, 0.62, 1);
    top.position.y = 0.5;
    g.add(bottom, patty, cheese, lettuce, top);
    // sesame
    const seedGeo = new THREE.SphereGeometry(0.032, 8, 6);
    for (let i = 0; i < 22; i += 1) {
      const a = Math.random() * Math.PI * 2;
      const r = 0.16 + Math.random() * 0.36;
      const seed = new THREE.Mesh(seedGeo, M.food(0xf3e6c8, 0.6));
      seed.position.set(Math.cos(a) * r, 0.5 + Math.sqrt(Math.max(0, 0.36 - r * r)) * 0.55 + 0.02, Math.sin(a) * r);
      g.add(seed);
    }
    return g;
  },
  ramen(M) {
    const g = new THREE.Group();
    const bowl = new THREE.Mesh(plateGeometry({ outer: 0.92, lip: 0.34, well: -0.02, walled: true }), M.ceramicDark);
    const broth = new THREE.Mesh(new THREE.CylinderGeometry(0.78, 0.7, 0.06, 40), M.sauce(0x8c5a2b));
    broth.position.y = 0.24;
    g.add(bowl, broth);
    // noodles: tubes on a wavy curve
    const noodleMat = M.food(0xf0dda6, 0.5);
    for (let n = 0; n < 7; n += 1) {
      const pts = [];
      const phase = n * 0.9;
      for (let i = 0; i <= 12; i += 1) {
        const t = i / 12;
        const a = phase + t * 5.2;
        pts.push(new THREE.Vector3(Math.cos(a) * (0.2 + 0.4 * t), 0.28 + Math.sin(t * 8 + phase) * 0.045, Math.sin(a) * (0.2 + 0.4 * t)));
      }
      const curve = new THREE.CatmullRomCurve3(pts);
      const tube = new THREE.Mesh(new THREE.TubeGeometry(curve, 40, 0.028, 7, false), noodleMat);
      g.add(tube);
    }
    const egg = new THREE.Mesh(new THREE.SphereGeometry(0.17, 22, 16), M.food(0xfaf0d8, 0.4));
    egg.scale.set(1, 0.78, 1);
    egg.position.set(-0.3, 0.33, 0.18);
    const yolk = new THREE.Mesh(new THREE.SphereGeometry(0.085, 18, 14), M.sauce(0xe08b2b));
    yolk.position.set(-0.3, 0.4, 0.29);
    const nori = new THREE.Mesh(new THREE.BoxGeometry(0.26, 0.3, 0.02), M.food(0x1b2a22, 0.6));
    nori.position.set(0.42, 0.4, -0.16);
    nori.rotation.set(-0.25, 0.5, 0.12);
    const scallion = new THREE.Mesh(new THREE.TorusGeometry(0.05, 0.016, 6, 12), M.leaf);
    scallion.position.set(0.1, 0.31, 0.3);
    scallion.rotation.x = Math.PI / 2;
    g.add(egg, yolk, nori, scallion);
    return g;
  },
  pizza(M) {
    const g = new THREE.Group();
    const dough = new THREE.Mesh(new THREE.CylinderGeometry(0.86, 0.82, 0.09, 40), M.food(0xd8a25c, 0.72));
    dough.position.y = 0.07;
    const sauce = new THREE.Mesh(new THREE.CylinderGeometry(0.76, 0.76, 0.03, 40), M.sauce(0xb23a26));
    sauce.position.y = 0.13;
    const cheese = new THREE.Mesh(new THREE.CylinderGeometry(0.73, 0.73, 0.028, 40), M.food(0xf1d488, 0.36));
    cheese.position.y = 0.152;
    const crust = new THREE.Mesh(new THREE.TorusGeometry(0.83, 0.075, 10, 44), M.food(0xc98a45, 0.75));
    crust.rotation.x = Math.PI / 2;
    crust.position.y = 0.1;
    g.add(dough, sauce, cheese, crust);
    const pepGeo = new THREE.CylinderGeometry(0.11, 0.1, 0.026, 16);
    const pepMat = M.food(0x9c2f22, 0.5);
    for (let i = 0; i < 7; i += 1) {
      const a = (i / 7) * Math.PI * 2 + 0.4;
      const r = 0.24 + (i % 3) * 0.18;
      const pep = new THREE.Mesh(pepGeo, pepMat);
      pep.position.set(Math.cos(a) * r, 0.17, Math.sin(a) * r);
      g.add(pep);
    }
    for (let i = 0; i < 9; i += 1) {
      const a = Math.random() * Math.PI * 2;
      const leaf = new THREE.Mesh(new THREE.SphereGeometry(0.055, 10, 8), M.leaf);
      leaf.scale.set(1.5, 0.28, 1);
      leaf.position.set(Math.cos(a) * (0.2 + Math.random() * 0.5), 0.175, Math.sin(a) * (0.2 + Math.random() * 0.5));
      g.add(leaf);
    }
    return g;
  },
  steak(M) {
    const g = new THREE.Group();
    const meat = new THREE.Mesh(new THREE.CylinderGeometry(0.6, 0.58, 0.3, 26), M.food(0x6e3a2a, 0.62));
    meat.scale.set(1.25, 1, 0.82);
    meat.position.y = 0.2;
    const sear = new THREE.Mesh(new THREE.CylinderGeometry(0.61, 0.59, 0.06, 26), M.food(0x2f1b14, 0.5));
    sear.scale.copy(meat.scale);
    sear.position.y = 0.33;
    const butter = new THREE.Mesh(new THREE.BoxGeometry(0.19, 0.07, 0.15), M.food(0xf3e6a8, 0.35));
    butter.position.set(0.06, 0.4, 0.02);
    g.add(meat, sear, butter);
    const rosemary = new THREE.Group();
    const stem = new THREE.Mesh(new THREE.CylinderGeometry(0.014, 0.014, 0.42, 8), M.food(0x4a3a22, 0.7));
    stem.rotation.z = Math.PI / 2;
    rosemary.add(stem);
    for (let i = 0; i < 9; i += 1) {
      const needle = new THREE.Mesh(new THREE.ConeGeometry(0.02, 0.1, 6), M.leaf);
      needle.position.set(-0.19 + i * 0.045, i % 2 ? 0.05 : -0.05, 0);
      needle.rotation.z = i % 2 ? -0.6 : 2.4;
      rosemary.add(needle);
    }
    rosemary.position.set(0.02, 0.46, 0.12);
    rosemary.rotation.y = 0.5;
    g.add(rosemary);
    for (let i = 0; i < 3; i += 1) {
      const pepper = new THREE.Mesh(new THREE.SphereGeometry(0.028, 8, 6), M.food(0x1a1a1a, 0.4));
      pepper.position.set(-0.2 + i * 0.2, 0.37, 0.16 - i * 0.12);
      g.add(pepper);
    }
    return g;
  },
  cake(M) {
    const shape = new THREE.Shape();
    shape.moveTo(0, 0);
    shape.lineTo(0.86, 0.5);
    shape.lineTo(0.86, -0.5);
    shape.closePath();
    const geo = new THREE.ExtrudeGeometry(shape, { depth: 0.52, bevelEnabled: true, bevelSize: 0.02, bevelThickness: 0.02, bevelSegments: 3 });
    geo.rotateX(-Math.PI / 2);
    geo.center();
    const g = new THREE.Group();
    const layers = [0xe9c8d4, 0xf6ead6, 0xd9a0b6, 0xf6ead6];
    layers.forEach((color, i) => {
      const slab = new THREE.Mesh(geo.clone(), M.food(color, 0.5));
      slab.scale.set(1, 0.55, 1);
      slab.position.y = -0.16 + i * 0.14;
      g.add(slab);
    });
    const glaze = new THREE.Mesh(geo.clone(), M.sauce(0xd88fa8));
    glaze.scale.set(1.02, 0.1, 1.02);
    glaze.position.y = 0.28;
    g.add(glaze);
    const pistachio = new THREE.Mesh(new THREE.SphereGeometry(0.06, 12, 10), M.food(0x7fa76a, 0.5));
    pistachio.position.set(0.1, 0.35, 0.16);
    const petal = new THREE.Mesh(new THREE.SphereGeometry(0.07, 12, 8), M.sauce(0xf2c0cf));
    petal.scale.set(1.6, 0.22, 1);
    petal.position.set(-0.12, 0.34, -0.06);
    g.add(pistachio, petal);
    g.position.y = 0.14;
    return g;
  },
  cocktail(M) {
    const g = new THREE.Group();
    const cup = new THREE.Mesh(plateGeometry({ outer: 0.52, lip: 0.72, well: 0.02, walled: true }), M.glass);
    cup.position.y = 0.02;
    const liquid = new THREE.Mesh(new THREE.CylinderGeometry(0.44, 0.36, 0.5, 30), M.sauce(0x74a86a));
    liquid.position.y = 0.34;
    const ice = new THREE.Mesh(new THREE.SphereGeometry(0.16, 18, 14), M.glass);
    ice.position.set(0.1, 0.55, 0.05);
    const straw = new THREE.Mesh(new THREE.CylinderGeometry(0.026, 0.026, 0.86, 12), M.brassDark);
    straw.position.set(0.18, 0.72, 0);
    straw.rotation.z = 0.28;
    const coaster = new THREE.Mesh(new THREE.CylinderGeometry(0.62, 0.62, 0.03, 34), M.stone);
    coaster.position.y = 0.015;
    g.add(cup, liquid, ice, straw, coaster);
    return g;
  },
};

export const DISH_KEYS = Object.keys(DISH_BUILDERS);

/**
 * A plated dish on its own little stage: plate, contact shadow, gold rim.
 * `label` is attached so hover raycasting can surface the right dish.
 */
export function platedDish(M, { kind = "burger", scale = 1, label = null, shadowTex } = {}) {
  const group = new THREE.Group();
  const plate = new THREE.Mesh(plateGeometry({ outer: 1.02, lip: 0.14, well: 0.02 }), M.ceramic);
  plate.castShadow = true;
  plate.receiveShadow = true;
  const rim = new THREE.Mesh(new THREE.TorusGeometry(1.0, 0.012, 8, 90), M.gold);
  rim.rotation.x = Math.PI / 2;
  rim.position.y = 0.148;
  group.add(plate, rim);

  const build = DISH_BUILDERS[kind] || DISH_BUILDERS.burger;
  const dish = build(M);
  dish.traverse((node) => {
    if (node.isMesh) { node.castShadow = true; node.receiveShadow = true; }
  });
  group.add(dish);

  if (shadowTex) {
    const shadow = new THREE.Mesh(
      new THREE.PlaneGeometry(2.6, 2.6),
      new THREE.MeshBasicMaterial({ map: shadowTex, transparent: true, opacity: 0.85, depthWrite: false }),
    );
    shadow.rotation.x = -Math.PI / 2;
    shadow.position.y = -0.012;
    group.add(shadow);
  }
  group.scale.setScalar(scale);
  group.userData.label = label;
  group.userData.kind = kind;
  group.userData.pickable = true;
  return group;
}

/** The marble turntable the whole scene sits on. */
export function turntable(M, radius = 3.35) {
  const g = new THREE.Group();
  const disc = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius * 0.98, 0.14, 72), M.stone);
  disc.receiveShadow = true;
  const inlay = new THREE.Mesh(new THREE.TorusGeometry(radius * 0.82, 0.006, 6, 120), M.gold);
  inlay.rotation.x = Math.PI / 2;
  inlay.position.y = 0.072;
  const skirt = new THREE.Mesh(new THREE.CylinderGeometry(radius * 0.86, radius * 0.7, 0.42, 48, 1, true), M.brassDark);
  skirt.position.y = -0.26;
  const halo = new THREE.Mesh(new THREE.RingGeometry(radius * 1.02, radius * 1.5, 64), 
    new THREE.MeshBasicMaterial({ color: 0x1a1d22, transparent: true, opacity: 0.55, side: THREE.DoubleSide }));
  halo.rotation.x = -Math.PI / 2;
  halo.position.y = -0.44;
  g.add(disc, inlay, skirt, halo);
  return g;
}

export { DISH_BUILDERS };
