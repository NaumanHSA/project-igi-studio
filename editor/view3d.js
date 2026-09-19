/* The 3D close-up (docs/PLAN-3d.md): the real geometry around one item, in
 * WebGL, where the item can be moved by hand onto floors, desks and walls.
 *
 *   View3D.open(opts)   show the close-up; calling it again rebuilds it (a new
 *                       target, a new radius) and keeps the view if opts.keepView
 *   View3D.close()
 *   View3D.isOpen()
 *   View3D.follow(pose) the item changed outside the close-up (undo): follow it
 *   View3D.update({target, objects, nav}) the plan changed outside it: bring the
 *               scene up to date (same keys as open), keeping the view
 *   opts.nav    walkways round it {nodes, links, route}; opts.onAddNode({x, y, z})
 *               adds a walkway point where a floor is clicked
 *
 * opts (all positions in game metres, z up):
 *   host        the element to cover (the map stage)
 *   target      the item: {key, name, type, model, x, y, z, rot:[a,b,g], head:0|2,
 *               lift, kind:"floor"|"wall"|"fixed", editable, cam, own, head model}
 *   objects     everything within the radius, the same shape (target included)
 *   terrain     {x0, y0, cell, w, h, z: Float32Array, shade: Float32Array|null}
 *   mesh(model) -> {pos: Float32Array metres, idx: Uint16Array} | null
 *   radius, inside (the item is in a building: start with the roof cut away)
 *   level       the level whose archives hold the textures (api/model3d, api/texture);
 *               without the studio server the models are drawn plain
 *   onMove(key, pose)   pose {x, y, z, gamma, on}: the item was put down
 *   onPick(key)         another item was clicked: edit that one instead
 *   onRadius(r)         a new radius was asked for
 *   onClose()
 *   onPlace(pose)       with setPlacing() on: a click put a new item down here
 *   onCancelPlace()     Esc while placing
 *
 *   View3D.setPlacing({label, model, kind, rot, head, lift} | null)
 *                       an item from the inventory is in hand: a ghost of it
 *                       follows the pointer, a click puts it down
 *   opts.view   how to start: "orbit" (round the item), "top", "eye", "walk",
 *               "player" (behind the player start, looking the way it faces)
 *
 * Driving it, as a shooter's free camera: the mouse is the view's, held in the
 * window (pointer lock), so moving it looks around; W A S D fly, Q and E down
 * and up, Shift fast, easing in and gliding to a stop. Holding Alt lets the
 * mouse go: click to select, Alt+drag to move anything, Shift+Alt+drag to lift
 * it or lower it, Alt+right-drag to circle it. Letting go of Alt takes the view
 * back. Esc frees the mouse; Esc again closes.
 *
 * Angles are the game's: alpha about x, then beta about y, then gamma about z
 * (a rifle lying on a desk is (heading, 1.5708, 0) - its heading is alpha). The
 * editor's "gamma" of an item is its heading, whichever angle carries it: the
 * target's rot[head].
 */
import * as THREE from "three";

const COL = {
  building: 0xb8bcb0, prop: 0xa89574, solid: 0x76855c, vehicle: 0x76855c, door: 0x9aa3a8,
  soldier: 0xb06a58, gun: 0x3c4044, player: 0x5fae6a, pickup: 0xd6c070, camera: 0x505a60, own: 0xe7c25a,
  target: 0xffd24a, terrain: 0x8a9a6a, cone: 0xffe066
};
const WALL_OFF = 0.15;          // a wall item stands this far out, as on the map (camMount)
const FLOOR_UP = 0.55;          // a surface is a floor if its normal is at least this upright
const WALL_FLAT = 0.45;         // ... and a wall if it is at most this
const STEP = Math.PI / 12;      // R turns 15 degrees

let S = null;                   // the close-up, once built
let O = null;                   // the current options

function css() {
  if (document.getElementById("v3d-css")) return;
  const st = document.createElement("style");
  st.id = "v3d-css";
  st.textContent = `
.v3d{position:absolute;inset:0;z-index:30;background:#0b1a10;display:flex;flex-direction:column}
.v3d[hidden]{display:none}
.v3d canvas{flex:1;min-height:0;width:100%;display:block;outline:none}
.v3d-top{display:flex;align-items:center;flex-wrap:wrap;gap:6px 8px;padding:7px 10px;background:var(--surface);
  border-bottom:1px solid var(--line);font-size:12px;color:var(--muted);white-space:nowrap;min-width:0}
.v3d-name{display:flex;flex-direction:column;min-width:120px;flex:1 1 140px;line-height:1.25}
.v3d-top b{color:var(--ink);font-size:13.5px;overflow:hidden;text-overflow:ellipsis}
.v3d-sub{font-size:11px;overflow:hidden;text-overflow:ellipsis}
.v3d-seg{display:flex;gap:2px;align-items:center;padding-left:6px;border-left:1px solid var(--line)}
.v3d-seg .btn{padding:2px 7px;font-size:11.5px}
.v3d-top label{display:flex;align-items:center;gap:5px;padding-left:6px;border-left:1px solid var(--line)}
.v3d-top input[type=range]{width:90px;accent-color:var(--accent)}
.v3d-cutv{min-width:44px;font:11px "IBM Plex Mono",monospace;color:var(--ink)}
.v3d-read{position:absolute;left:12px;bottom:12px;background:var(--surface);border:1px solid var(--line);border-radius:6px;
  padding:7px 10px;font:12px "IBM Plex Mono",monospace;color:var(--ink);box-shadow:var(--shadow);max-width:60%;line-height:1.6}
.v3d-read .k{color:var(--faint);margin-right:6px}
.v3d-read .bad{color:var(--warn)}
.v3d-help{position:absolute;right:12px;bottom:12px;background:var(--surface);border:1px solid var(--line);border-radius:6px;
  padding:7px 10px;font-size:11.5px;color:var(--muted);box-shadow:var(--shadow);max-width:360px;line-height:1.5}
.v3d-help b{color:var(--ink);font-weight:600}
.v3d-tip{position:absolute;pointer-events:none;background:rgba(4,18,8,.9);border:1px solid var(--line);border-radius:4px;
  padding:3px 7px;font-size:11.5px;color:var(--ink);white-space:nowrap;transform:translate(12px,12px)}
.v3d-tip[hidden]{display:none}
.v3d-tip i{font-style:normal;color:var(--accent)}
.v3d-none{position:absolute;inset:0;display:grid;place-items:center;color:var(--muted);font-size:14px}
.v3d-range{min-width:150px}
.v3d-range input{width:96px}
.v3d-radv{min-width:38px;font:11px "IBM Plex Mono",monospace;color:var(--ink)}
.v3d-cross{position:absolute;left:50%;top:calc(50% + 21px);width:22px;height:22px;margin:-11px 0 0 -11px;pointer-events:none;display:none}
.v3d.looking .v3d-cross{display:block}
.v3d-cross::before,.v3d-cross::after{content:"";position:absolute;background:rgba(141,255,154,.85);box-shadow:0 0 6px rgba(141,255,154,.7)}
.v3d-cross::before{left:10px;top:0;width:2px;height:22px;clip-path:polygon(0 0,100% 0,100% 35%,0 35%,0 65%,100% 65%,100% 100%,0 100%)}
.v3d-cross::after{top:10px;left:0;height:2px;width:22px;clip-path:polygon(0 0,35% 0,35% 100%,0 100%,0 0,65% 0,100% 0,100% 100%,65% 100%)}
.v3d-hint{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);pointer-events:none;text-align:center;
  padding:12px 20px;background:rgba(4,18,8,.84);border:1px solid var(--line);border-radius:4px;box-shadow:0 0 30px rgba(0,0,0,.5)}
.v3d-hint[hidden]{display:none}
.v3d-hint b{display:block;font:600 17px "Barlow Condensed",sans-serif;letter-spacing:.12em;text-transform:uppercase;color:var(--player)}
.v3d-hint span{font-size:12px;color:var(--muted)}
.v3d.editing canvas{cursor:default}`;
  document.head.appendChild(st);
}

function build(host) {
  css();
  const el = document.createElement("div");
  el.className = "v3d";
  el.hidden = true;
  el.innerHTML = `
<div class="v3d-top">
  <span class="v3d-name"><b class="v3d-title"></b><span class="v3d-sub"></span></span>
  <label class="v3d-range" title="Range\nHow far round it to show, 10 to 60 m">Range
    <input type="range" class="v3d-rad" min="10" max="60" step="10" value="60"><span class="v3d-radv">60 m</span></label>
  <div class="v3d-seg" data-g="view">
    <button class="btn" data-v="orbit" title="Look at it from around (F)">Around</button>
    <button class="btn" data-v="top" title="From straight above (T)">Top</button>
    <button class="btn" data-v="eye" title="Standing in front of it, 1.7 m eyes">Eye level</button>
    <button class="btn" data-v="cam" title="What the camera sees">Camera view</button>
    <button class="btn" data-v="walk" title="Walk at eye height: floors, stairs and the ground followed, walls in the way (G)">Walk</button></div>
  <label title="Hide everything above this height: roofs, ceilings, the floors over a room">Cut
    <input type="range" class="v3d-cut" min="0" max="100" value="100"><span class="v3d-cutv">off</span></label>
  <label title="Other buildings see-through"><input type="checkbox" class="v3d-xray">X-ray</label>
  <label title="Guard walkways: the navmesh's points and links, and the selected guard's patrol in gold"><input type="checkbox" class="v3d-nav">Walkways</label>
  <button class="btn v3d-addnode" title="Add a walkway point: click a floor or the ground. It links to the walkway points on its floor within 15 m" hidden>Add walkway point</button>
  <button class="btn v3d-test" title="Test from here\nBuild the mission with the player starting where you stand, facing where you look, and start the game" hidden>Test from here</button>
  <label title="The game's own textures (off: plain colours - the level's grey-green, yours gold)"><input type="checkbox" class="v3d-tex" checked>Textures</label>
  <button class="btn primary v3d-done" title="Esc">Done</button>
</div>
<canvas tabindex="0"></canvas>
<div class="v3d-cross"></div>
<div class="v3d-hint" hidden><b>Click to look around</b><span>The mouse turns the view, W A S D fly · hold Alt to edit</span></div>
<div class="v3d-read"></div>
<div class="v3d-help"></div>
<div class="v3d-tip" hidden></div>`;
  host.appendChild(el);
  const canvas = el.querySelector("canvas");
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  } catch (e) {
    el.insertAdjacentHTML("beforeend", '<div class="v3d-none">This browser cannot draw 3D here (WebGL is off).</div>');
    return { el, dead: true };
  }
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.localClippingEnabled = true;
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(50, 1, 0.05, 3000);
  camera.up.set(0, 0, 1);

  const hemi = new THREE.HemisphereLight(0xe4eef5, 0x4a4f3c, 1.1);
  hemi.position.set(0, 0, 1);
  scene.add(hemi);
  const sun = new THREE.DirectionalLight(0xfff2dc, 1.9);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  sun.shadow.bias = -0.0004;
  sun.shadow.normalBias = 0.02;
  scene.add(sun);
  scene.add(sun.target);
  scene.add(new THREE.AmbientLight(0xffffff, 0.18));

  const s = {
    el, canvas, renderer, scene, camera, sun, hemi, yaw: 0, pitch: -0.4, look: null,
    root: new THREE.Group(), geo: new Map(), cut: new THREE.Plane(new THREE.Vector3(0, 0, -1), 1e6),
    ray: new THREE.Raycaster(), items: [], byKey: new Map(), target: null, drag: null, down: null,
    raf: 0, turn: 0, viewMode: "orbit", size: [0, 0], textured: true
  };
  try { s.textured = localStorage.getItem("plotter:v3dtex") !== "0"; } catch (e) { /* private window */ }
  el.querySelector(".v3d-tex").checked = s.textured;
  scene.add(s.root);
  el.querySelector(".v3d-done").addEventListener("click", close);
  const rad = el.querySelector(".v3d-rad"), radv = el.querySelector(".v3d-radv");
  rad.addEventListener("input", () => { radv.textContent = rad.value + " m"; });
  rad.addEventListener("change", () => {
    const r = +rad.value;
    if (O && O.onRadius && r !== O.radius) O.onRadius(r);
  });
  el.querySelectorAll('[data-g="view"] .btn').forEach(b => b.addEventListener("click", () => setView(b.dataset.v)));
  el.querySelector(".v3d-cut").addEventListener("input", e => setCut(+e.target.value));
  el.querySelector(".v3d-xray").addEventListener("change", e => setXray(e.target.checked));
  try { s.navOn = localStorage.getItem("plotter:v3dnav") === "1"; } catch (e) { /* private window */ }
  el.querySelector(".v3d-nav").checked = !!s.navOn;
  el.querySelector(".v3d-nav").addEventListener("change", e => {
    S.navOn = e.target.checked;
    try { localStorage.setItem("plotter:v3dnav", S.navOn ? "1" : "0"); } catch (err) { /* private window */ }
    if (!S.navOn) setAddingNode(false);
    makeNav();
  });
  el.querySelector(".v3d-addnode").addEventListener("click", () => setAddingNode(!S.addingNode));
  el.querySelector(".v3d-test").addEventListener("click", () => {
    const p = S.camera.position, o = O.origin;
    if (O.onTest) O.onTest({ x: p.x + o[0], y: p.y + o[1], z: p.z - EYE + o[2], gamma: S.yaw });
  });
  el.querySelector(".v3d-tex").addEventListener("change", e => {
    S.textured = e.target.checked;
    try { localStorage.setItem("plotter:v3dtex", S.textured ? "1" : "0"); } catch (err) { /* private window */ }
    if (O) { fill(); setXray(S.el.querySelector(".v3d-xray").checked); const h = S.placing; S.ghost = null; setPlacing(h); }
  });
  canvas.addEventListener("pointerdown", onDown, true);
  canvas.addEventListener("pointermove", onMove);
  canvas.addEventListener("pointerup", onUp);
  canvas.addEventListener("pointerleave", () => { tip(null); });
  canvas.addEventListener("contextmenu", e => e.preventDefault());
  canvas.addEventListener("wheel", onWheel, { passive: false });
  window.addEventListener("keydown", onKey, true);
  window.addEventListener("keyup", onKeyUp, true);
  window.addEventListener("blur", () => { held.clear(); if (S) { S.alt = false; editing(); } });
  document.addEventListener("pointerlockchange", onLockChange);
  document.addEventListener("pointerlockerror", () => { if (S) hint(); });
  return s;
}

// ------------------------------------------------------------------ geometry
function geometryOf(model) {
  if (S.geo.has(model)) return S.geo.get(model);
  const m = O.mesh(model);
  let g = null;
  if (m && m.idx.length) {
    g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(m.pos, 3));
    g.setIndex(new THREE.BufferAttribute(m.idx, 1));
    g.computeBoundingBox();
    g.computeBoundingSphere();
  }
  S.geo.set(model, g);
  return g;
}

// ------------------------------------------------------------------ textures
const TMODEL = new Map();       // model -> Promise of {geo, groups} | null
const TEX = new Map();          // texture name -> THREE.Texture
function b64(s) {
  const bin = atob(s), u = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
  return u.buffer;
}
function texturedModel(model) {
  const key = model + "@" + (O.level || 0);
  if (TMODEL.has(key)) return TMODEL.get(key);
  const p = fetch("api/model3d?name=" + encodeURIComponent(model) + "&level=" + (O.level || 0))
    .then(r => r.ok ? r.json() : null).then(j => {
      if (!j || !j.ok) return null;
      const m = j.model, g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(b64(m.pos)), 3));
      g.setAttribute("uv", new THREE.BufferAttribute(new Float32Array(b64(m.uv)), 2));
      g.setIndex(new THREE.BufferAttribute(new Uint32Array(b64(m.idx)), 1));
      m.groups.forEach((gr, i) => g.addGroup(gr[0], gr[1], i));
      g.computeBoundingBox();
      g.computeBoundingSphere();
      g.userData.keep = true;
      return { geo: g, groups: m.groups };
    }).catch(() => null);
  TMODEL.set(key, p);
  return p;
}
function textureOf(name) {
  const key = name + "@" + (O.level || 0);
  if (TEX.has(key)) return TEX.get(key);
  const t = new THREE.TextureLoader().load("api/texture?name=" + encodeURIComponent(name) + "&level=" + (O.level || 0) + "&size=512");
  t.colorSpace = THREE.SRGBColorSpace;
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.flipY = false;                  // the game's uvs start at the top row
  t.anisotropy = 4;
  TEX.set(key, t);
  return t;
}
// the model's own look, once it has come: its textures, tinted for what it is
function dress(mesh, it, isTarget) {
  if (!S.textured || !it.model || !O.level) return;
  const wanted = S.fillId;
  texturedModel(it.model).then(t => {
    if (!t || wanted !== S.fillId || !mesh.parent) return;
    const tint = isTarget ? 0xffe9a0 : it.own ? 0xfff2c8 : 0xffffff;
    const mats = t.groups.map(gr => {
      const m = new THREE.MeshLambertMaterial({ color: tint, side: THREE.DoubleSide, flatShading: true,
        map: gr[2] ? textureOf(gr[2]) : null, alphaTest: gr[3] ? 0.5 : 0 });
      if (isTarget) m.emissive = new THREE.Color(0x2a1c00);
      else m.clippingPlanes = [S.cut];
      return m;
    });
    const old = mesh.material;
    mesh.geometry = t.geo;
    mesh.material = mats;
    (Array.isArray(old) ? old : [old]).forEach(m => m.dispose());
    if (S.el.querySelector(".v3d-xray").checked && it.type === "building" && !isTarget) setXray(true);
  });
}

function material(color, opts = {}) {
  return new THREE.MeshLambertMaterial(Object.assign({
    color, flatShading: true, side: THREE.DoubleSide
  }, opts));
}

// which of the three angles carries an item's heading: alpha (0) for a rifle
// lying down, gamma (2) for everything else; and how: angle = off + sign *
// heading (a rifle's alpha turns it clockwise, so its sign is -1)
function hi(it) { return it && it.head === 0 ? 0 : 2; }
function sgn(it) { return it && it.headSign === -1 ? -1 : 1; }
function headOf(it, rot) { return sgn(it) * (((rot || [])[hi(it)] || 0) - (it.headOff || 0)); }

// the game's orientation: alpha about x, then beta about y, then gamma about z
function orient(obj, rot) {
  obj.rotation.set(rot[0] || 0, rot[1] || 0, rot[2] || 0, "ZYX");
}

function colorOf(it) {
  if (it.key === O.target.key) return COL.target;
  if (it.own) return COL.own;
  if (it.type === "building") return COL.building;
  if (it.type === "soldier") return COL.soldier;
  if (it.type === "player") return COL.player;
  if (it.type === "pickup") return COL.pickup;
  if (it.type === "camera") return COL.camera;
  if (it.type === "door") return COL.door;
  if (it.type === "vehicle" || it.type === "explodable" || it.solid) return COL.solid;
  return COL.prop;
}

function makeItem(it) {
  const group = new THREE.Group();
  if (it.type === "spot") {               // a place, not a thing: nothing to draw
    group.userData.item = it;
    group.userData.body = new THREE.Group();
    group.add(group.userData.body);
    place(group, it);
    return group;
  }
  const isTarget = it.key === O.target.key;
  const mat = material(colorOf(it), isTarget ? { emissive: 0x3a2a00 } : {});
  if (!isTarget && it.type !== "terrain") mat.clippingPlanes = [S.cut];
  const g = it.model ? geometryOf(it.model) : null;
  const body = new THREE.Group();
  body.position.z = it.lift || 0;
  if (g) {
    const mesh = new THREE.Mesh(g, mat);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    mesh.userData.item = it;
    body.add(mesh);
    dress(mesh, it, isTarget);
    if (isTarget && g.index.count < 60000) {
      const edges = new THREE.LineSegments(new THREE.EdgesGeometry(g, 35),
        new THREE.LineBasicMaterial({ color: 0xfff0a0, transparent: true, opacity: 0.85 }));
      body.add(edges);
    }
  } else {
    // nothing to draw it with: a marker the size of a person
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(0.4, 0.4, 1.0), mat);
    mesh.position.z = 0.5;
    mesh.userData.item = it;
    body.add(mesh);
  }
  if (g && it.gun && it.grip) body.add(gunOf(it, isTarget));
  if (it.cam && it.cam.model) {
    // the camera itself, on its holder: pan about z, tilt about x
    const hg = geometryOf(it.cam.model);
    if (hg) {
      const head = new THREE.Mesh(hg, mat.clone());
      head.rotation.set(it.cam.pitch || 0, 0, it.cam.pan || 0, "ZYX");
      head.castShadow = true;
      head.userData.item = it;
      body.add(head);
      dress(head, Object.assign({}, it, { model: it.cam.model }), isTarget);
      if (isTarget || it.cam.cone) body.add(viewCone(it.cam));
    }
  }
  group.add(body);
  group.userData.item = it;
  group.userData.body = body;
  place(group, it);
  return group;
}

// the weapon in a guard's hands: its model on the grip his pose holds it at
// (meshes.json "grips": position, then the rotation row by row)
function gunOf(it, isTarget, ghostMat) {
  const gg = geometryOf(it.gun);
  if (!gg) return new THREE.Group();
  const q = it.grip, mat = ghostMat || material(COL.gun, isTarget ? { emissive: 0x2a1c00 } : {});
  if (!ghostMat && !isTarget) mat.clippingPlanes = [S.cut];
  const gun = new THREE.Mesh(gg, mat);
  gun.matrixAutoUpdate = false;
  gun.matrix.set(q[3], q[4], q[5], q[0], q[6], q[7], q[8], q[1], q[9], q[10], q[11], q[2], 0, 0, 0, 1);
  gun.castShadow = true;
  if (ghostMat) gun.raycast = () => {};
  else {
    gun.userData.item = it;
    dress(gun, Object.assign({}, it, { model: it.gun }), isTarget);
  }
  return gun;
}

// what a camera sees: a pyramid of its field of view out to its range
function viewCone(cam) {
  const r = Math.min(cam.range || 20, 60), h = Math.tan(((cam.fov || 50) * Math.PI / 180) / 2) * r,
    v = Math.tan(((cam.fovV || 40) * Math.PI / 180) / 2) * r;
  const p = [0, 0, 0, -h, r, -v, h, r, -v, h, r, v, -h, r, v];
  const idx = [0, 1, 2, 0, 2, 3, 0, 3, 4, 0, 4, 1];
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(p, 3));
  g.setIndex(idx);
  const cone = new THREE.Group();
  cone.add(new THREE.Mesh(g, new THREE.MeshBasicMaterial({ color: COL.cone, transparent: true, opacity: 0.12,
    side: THREE.DoubleSide, depthWrite: false })));
  cone.add(new THREE.LineSegments(new THREE.EdgesGeometry(g), new THREE.LineBasicMaterial({ color: COL.cone,
    transparent: true, opacity: 0.55 })));
  cone.rotation.set(cam.pitch || 0, 0, cam.pan || 0, "ZYX");
  cone.raycast = () => {};
  cone.traverse(c => { c.raycast = () => {}; });
  return cone;
}

function place(group, it) {
  const o = O.origin;
  group.position.set(it.x - o[0], it.y - o[1], it.z - o[2]);
  orient(group, it.rot || [0, 0, it.gamma || 0]);
  group.userData.box = null;                   // where it stands, for walking, is asked again
}

function terrainMesh(t) {
  const o = O.origin, w = t.w, h = t.h;
  const pos = new Float32Array(w * h * 3), col = new Float32Array(w * h * 3), uv = new Float32Array(w * h * 2);
  const base = new THREE.Color(COL.terrain), rock = new THREE.Color(0x8f8b80), c = new THREE.Color();
  for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) {
    const k = j * w + i;
    let z = t.z[k];
    if (!(z === z)) z = o[2] - 50;
    pos[k * 3] = t.x0 + i * t.cell - o[0];
    pos[k * 3 + 1] = t.y0 + j * t.cell - o[1];
    pos[k * 3 + 2] = z - o[2];
    // the detail texture repeats every 4 m, fixed to the world
    uv[k * 2] = (t.x0 + i * t.cell) / 4;
    uv[k * 2 + 1] = (t.y0 + j * t.cell) / 4;
  }
  for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) {
    const k = j * w + i;
    const zx = pos[(j * w + Math.min(w - 1, i + 1)) * 3 + 2] - pos[(j * w + Math.max(0, i - 1)) * 3 + 2];
    const zy = pos[(Math.min(h - 1, j + 1) * w + i) * 3 + 2] - pos[(Math.max(0, j - 1) * w + i) * 3 + 2];
    const slope = Math.min(1, Math.hypot(zx, zy) / (4 * t.cell));
    if (t.rgb) {
      // the ground's own material, a little greyer where it is steep
      c.setRGB(t.rgb[k * 3], t.rgb[k * 3 + 1], t.rgb[k * 3 + 2], THREE.SRGBColorSpace).lerp(rock, slope * 0.35);
      if (t.tile) c.multiplyScalar(1 / Math.max(0.25, t.tile.mean * 1.6));   // the detail map darkens by its mean
    } else {
      c.copy(base).lerp(rock, slope);
      const sh = t.shade ? t.shade[k] : 0.5;
      c.multiplyScalar(0.75 + 0.5 * sh);
    }
    col[k * 3] = c.r; col[k * 3 + 1] = c.g; col[k * 3 + 2] = c.b;
  }
  // where a building is open to the sky under ground level (a ramp down to
  // bunker doors) the game draws no ground: those points are left out
  const idx = [], hole = t.hole;
  for (let j = 0; j < h - 1; j++) for (let i = 0; i < w - 1; i++) {
    const a = j * w + i, b = a + 1, cc = a + w, d = cc + 1;
    if (hole && (hole[a] || hole[b] || hole[cc] || hole[d])) continue;
    idx.push(a, b, d, a, d, cc);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  g.setAttribute("color", new THREE.BufferAttribute(col, 3));
  g.setAttribute("uv", new THREE.BufferAttribute(uv, 2));
  g.setIndex(idx);
  g.computeVertexNormals();
  let map = null;
  if (t.tile && t.rgb) {
    // the level's own grain: its most common ground texture, in grey
    const src = t.tile.px, n = t.tile.size, px = new Uint8Array(n * n * 4);
    for (let q = 0; q < n * n; q++) {
      const v = src[q];
      px[q * 4] = px[q * 4 + 1] = px[q * 4 + 2] = v;
      px[q * 4 + 3] = 255;
    }
    map = new THREE.DataTexture(px, n, n, THREE.RGBAFormat);
    map.wrapS = map.wrapT = THREE.RepeatWrapping;
    map.magFilter = THREE.LinearFilter;
    map.minFilter = THREE.LinearMipmapLinearFilter;
    map.generateMipmaps = true;
    map.needsUpdate = true;
  }
  const mesh = new THREE.Mesh(g, new THREE.MeshLambertMaterial({ vertexColors: true, map }));
  mesh.receiveShadow = true;
  mesh.userData.item = { key: "terrain", name: "the ground", type: "terrain" };
  return mesh;
}

// ------------------------------------------------------------------ building the scene
function drop(obj) {
  const cached = new Set(S.geo.values());
  obj.traverse(c => {
    if (c.userData.item && c.userData.item.type === "terrain" && c.material && c.material.map) c.material.map.dispose();
    if (c.geometry && !cached.has(c.geometry) && !c.geometry.userData.keep) c.geometry.dispose();
    if (c.material) (Array.isArray(c.material) ? c.material : [c.material]).forEach(m => m.dispose());
  });
}
function fill() {
  const root = S.root;
  S.fillId = (S.fillId || 0) + 1;         // textures on their way to an older scene are dropped
  drop(root);
  root.clear();
  S.items = [];
  S.byKey = new Map();
  if (O.terrain) root.add(terrainMesh(O.terrain));
  for (const it of O.objects) {
    const g = makeItem(it);
    root.add(g);
    S.items.push(g);
    S.byKey.set(it.key, g);
  }
  S.target = S.byKey.get(O.target.key) || null;
  S.turn = 0;
  S.nav = null;
  makeNav();
  const R = O.radius + 6;
  sunOver(0, 0, 0);
  const sc = S.sun.shadow.camera;
  sc.left = -R * 1.3; sc.right = R * 1.3; sc.top = R * 1.3; sc.bottom = -R * 1.3;
  sc.near = 0.5; sc.far = R * 8;
  sc.updateProjectionMatrix();
  // the ground reaches further than the things on it; the fog ends where it does
  const T = O.terrain, reach = T ? Math.min(T.w, T.h) * T.cell / 2 : R * 3;
  S.scene.fog = new THREE.Fog(0x9fb2ba, Math.max(R, reach * 0.45), reach * 0.97);
  S.scene.background = new THREE.Color(0x9fb2ba);
}

// the sun: from the north-west, high, its shadows over the close-up round a
// point (the item, or wherever the camera has gone)
function sunOver(x, y, z) {
  const R = O.radius + 6;
  S.sun.position.set(x - 0.55 * R * 2, y + 0.75 * R * 2, z + 1.6 * R * 2);
  S.sun.target.position.set(x, y, z);
}

// The close-up goes where the camera goes. Once the camera is a few metres from
// where the scene was gathered, the host gathers it again round the camera:
// what stands near, the walkways and, once the camera nears the edge of the
// ground it has, the ground. What is still near stays as it is, what came into
// reach is made and what fell out of it goes, so you can fly or walk the whole
// level from anywhere you opened it.
function explore(now) {
  if (!O || !O.explore || S.drag) return;
  if (now - (S.youAt || 0) > 200 && away()) { S.youAt = now; readout(); }
  if (now - (S.exploredAt || 0) < 250) return;
  const o = O.origin, p = S.camera.position, wx = p.x + o[0], wy = p.y + o[1];
  const T = O.terrain, half = T ? Math.min(T.w, T.h) * T.cell / 2 : 0;
  const ground = !!T && Math.hypot(wx - (T.x0 + (T.w - 1) * T.cell / 2), wy - (T.y0 + (T.h - 1) * T.cell / 2)) > half * 0.35;
  if (!ground && Math.hypot(wx - S.centre[0], wy - S.centre[1]) < Math.max(5, O.radius * 0.3)) return;
  S.exploredAt = now;
  S.centre = [wx, wy];
  // a cut set for the room it opened in means nothing out here: off, once
  const cutEl = S.el.querySelector(".v3d-cut");
  if (!S.cutFreed && +cutEl.value < 100 && Math.hypot(p.x, p.y) > O.radius) {
    S.cutFreed = true;
    cutEl.value = 100;
    setCut(100);
  }
  const got = O.explore(wx, wy, p.z + o[2], ground);
  if (!got) return;
  if (got.terrain) {
    O.terrain = got.terrain;
    const old = S.root.children.find(c => c.userData.item && c.userData.item.type === "terrain");
    if (old) { S.root.remove(old); drop(old); }
    S.root.add(terrainMesh(O.terrain));
  }
  update({ objects: got.objects, nav: got.nav });
  sunOver(Math.round(p.x), Math.round(p.y), Math.round(p.z));
}

// ------------------------------------------------------------------ views
function frame() {
  const r = O.radius;
  const m = S.target ? S.target.userData.body.children.find(c => c.isMesh) : null;
  const g = m ? new THREE.Box3().setFromObject(m) : null;
  const c = g && !g.isEmpty() ? g.getCenter(new THREE.Vector3()) : new THREE.Vector3(0, 0, 1);
  const size = g && !g.isEmpty() ? g.getSize(new THREE.Vector3()).length() : 1;
  // close enough to see a pistol on a desk, far enough to take in a building
  const d = Math.max(2.2, Math.min(Math.max(r, size * 1.3), size * 3.5 + 1.5));
  return { c, r, d };
}
// ------------------------------------------------------------------ the free camera
// A spectator's camera, as in a shooter's free roam: it looks from where it is.
// Drag to look around, W A S D (or the arrows) to fly where it looks, Q and E
// straight down and up, Shift fast; the wheel moves forward and back; right-drag
// circles the item. yaw 0 looks north (+y), as an item's heading does.
function dirOf(yaw, pitch) {
  return new THREE.Vector3(-Math.sin(yaw) * Math.cos(pitch), Math.cos(yaw) * Math.cos(pitch), Math.sin(pitch));
}
function applyLook() {
  S.pitch = Math.max(-1.55, Math.min(1.55, S.pitch));
  S.camera.lookAt(S.camera.position.clone().add(dirOf(S.yaw, S.pitch)));
}
function lookAt(p) {
  const d = new THREE.Vector3().subVectors(p, S.camera.position);
  if (d.lengthSq() < 1e-8) return;
  S.yaw = Math.atan2(-d.x, d.y);
  S.pitch = Math.atan2(d.z, Math.hypot(d.x, d.y));
  applyLook();
}
function itemCentre() {
  const m = S.target ? S.target.userData.body.children.find(c => c.isMesh) : null;
  const b = m ? new THREE.Box3().setFromObject(m) : null;
  return b && !b.isEmpty() ? b.getCenter(new THREE.Vector3()) : new THREE.Vector3(0, 0, 1);
}
function onWheel(e) {
  e.preventDefault();
  if (S.walking) return;                      // a walker's feet stay on the floor
  const step = (e.shiftKey ? 4 : 1.2) * Math.sign(e.deltaY) * -1;
  vel.addScaledVector(dirOf(S.yaw, S.pitch), step * 4.5);
}

function setView(mode) {
  vel.set(0, 0, 0);
  S.el.querySelector(".v3d-test").hidden = !(mode === "walk" && O && O.onTest);
  // walking starts on the floor under the camera, looking ahead
  if (mode === "walk") {
    const p = S.camera.position;
    if (floorAt(p.x, p.y, p.z) != null || floorAt(p.x, p.y, p.z + 200) != null) {
      if (floorAt(p.x, p.y, p.z) == null) p.z += 200;       // under the ground: up through it first
      S.walking = true; S.viewMode = "walk"; S.pitch = -0.08;
      settle(true); applyLook();
      S.el.querySelectorAll('[data-g="view"] .btn').forEach(b => b.classList.toggle("on", b.dataset.v === "walk"));
      help();
      return;
    }
  }
  S.walking = mode === "walk";
  if (S.walking) mode = "eye";                // nothing under the camera: start where Eye level stands
  S.viewMode = mode;
  S.el.querySelectorAll('[data-g="view"] .btn').forEach(b => b.classList.toggle("on", b.dataset.v === mode));
  const { c, r, d: dist } = frame();
  const it = O.target, head = headingOf(it);
  const fx = -Math.sin(head), fy = Math.cos(head);          // the item's forward: local +y
  S.camera.fov = 60;
  // looking through a camera, the camera itself is not in the way
  if (S.target) S.target.visible = mode !== "cam";
  if (mode === "top") {
    S.camera.position.set(c.x + 0.01, c.y - 0.01, c.z + Math.max(6, r * 1.6));
  } else if (mode === "eye") {
    // standing in front of it, far enough to take it in, eyes 1.7 m over the ground there
    const d = Math.max(3, dist * 0.9);
    S.camera.position.set(c.x + fx * d, c.y + fy * d, (it.floor != null ? it.floor - O.origin[2] : c.z - 1) + 1.7);
  } else if (mode === "player") {
    // behind the player start and over it, looking the way it faces: the
    // mission as the player first sees it, with the player in the picture
    const fl = it.floor != null ? it.floor - O.origin[2] : 0;
    S.camera.position.set(-fx * 4.5, -fy * 4.5, fl + 2.6);
    S.camera.updateProjectionMatrix();
    lookAt(new THREE.Vector3(fx * 12, fy * 12, fl + 1.2));
    S.el.querySelectorAll('[data-g="view"] .btn').forEach(b => b.classList.remove("on"));
    help();
    return;
  } else if (mode === "cam" && it.cam) {
    // from the camera's own lens, looking where it looks
    const pitch = it.cam.pitch || 0, h = head + (it.cam.pan || 0);
    const dir = new THREE.Vector3(-Math.sin(h) * Math.cos(pitch), Math.cos(h) * Math.cos(pitch), Math.sin(pitch));
    const eye = new THREE.Vector3(0, 0, (it.lift || 0) + 0.05).add(dir.clone().multiplyScalar(0.3));
    S.camera.position.copy(eye);
    S.camera.fov = Math.max(20, Math.min(100, it.cam.fovV || 40));
    S.camera.updateProjectionMatrix();
    lookAt(eye.clone().add(dir.multiplyScalar(5)));
    return;
  } else {
    // in front of it and to one side; indoors from high up, over the cut-away walls
    const d = dist, up = O.inside ? 1.6 : 0.7, back = O.inside ? 0.45 : 0.7;
    S.camera.position.set(c.x + fx * d * back + fy * d * 0.45, c.y + fy * d * back - fx * d * 0.45, c.z + d * up);
  }
  S.camera.updateProjectionMatrix();
  lookAt(c);
  if (S.walking) {
    S.el.querySelectorAll('[data-g="view"] .btn').forEach(b => b.classList.toggle("on", b.dataset.v === "walk"));
    settle(true);
  }
  help();
}
// ------------------------------------------------------------------ walkways
// The navmesh round the item (O.nav: nodes [x, y, z, own], links [x1..z2, own],
// route [[x, y, z]...]): small posts and lines, yours gold, the level's in the
// climb colour; the selected guard's patrol a gold line over them. Not picked.
function makeNav() {
  if (S.nav) { S.root.remove(S.nav); drop(S.nav); S.nav = null; }
  const N = O && O.nav;
  S.el.querySelector(".v3d-addnode").hidden = !(S.navOn && O && O.onAddNode);
  if (!N || !S.navOn) return;
  const o = O.origin, g = new THREE.Group();
  const post = new THREE.CylinderGeometry(0.09, 0.09, 0.5, 8).rotateX(Math.PI / 2).translate(0, 0, 0.25);
  const mats = [new THREE.MeshBasicMaterial({ color: 0x6fdcec }), new THREE.MeshBasicMaterial({ color: 0xffd24a })];
  [0, 1].forEach(own => {
    const list = N.nodes.filter(n => !!n[3] === !!own);
    if (!list.length) return;
    const im = new THREE.InstancedMesh(post, mats[own], list.length), m = new THREE.Matrix4();
    list.forEach((n, i) => { m.makeTranslation(n[0] - o[0], n[1] - o[1], n[2] - o[2]); im.setMatrixAt(i, m); });
    g.add(im);
  });
  [0, 1].forEach(own => {
    const list = N.links.filter(l => !!l[6] === !!own);
    if (!list.length) return;
    const pos = new Float32Array(list.length * 6);
    list.forEach((l, i) => { for (let k = 0; k < 6; k++) pos[i * 6 + k] = l[k] - o[k % 3] + (k % 3 === 2 ? 0.2 : 0); });
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    g.add(new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ color: own ? 0xffd24a : 0x6fdcec, transparent: true, opacity: 0.8 })));
  });
  if (N.route && N.route.length > 1) {
    const geo = new THREE.BufferGeometry().setFromPoints(N.route.map(p => new THREE.Vector3(p[0] - o[0], p[1] - o[1], p[2] - o[2] + 0.45)));
    g.add(new THREE.Line(geo, new THREE.LineBasicMaterial({ color: 0xffd24a })));
  }
  g.traverse(c => { c.raycast = () => {}; });
  S.nav = g;
  S.root.add(g);
}
function setAddingNode(on) {
  S.addingNode = !!on && !!(O && O.onAddNode);
  if (S.addingNode) unlock();             // a floor to click needs a pointer
  S.el.querySelector(".v3d-addnode").classList.toggle("on", S.addingNode);
  S.canvas.style.cursor = S.addingNode ? "crosshair" : "";
  help();
}

// ------------------------------------------------------------------ walking
// The eye 1.7 m over the floor under it. W A S D walk along the ground where it
// looks (Shift runs); a step up to 0.55 m (stairs, a kerb) is climbed, a drop is
// fallen down; a wall, a crate or a fence in the way stops it at knee, waist or
// head height, and it slides along instead where it can.
const EYE = 1.7, STEP_UP = 0.55, BODY = 0.3;
// The ground from its own grid (a ray through the whole terrain mesh every frame
// is slow); floors and roofs from the things near the point.
function groundAt(x, y) {
  const T = O && O.terrain;
  if (!T) return null;
  const o = O.origin, fx = (x + o[0] - T.x0) / T.cell, fy = (y + o[1] - T.y0) / T.cell;
  const i = Math.floor(fx), j = Math.floor(fy);
  if (i < 0 || j < 0 || i >= T.w - 1 || j >= T.h - 1) return null;
  const hl = T.hole, k0 = j * T.w + i;
  if (hl && (hl[k0] || hl[k0 + 1] || hl[k0 + T.w] || hl[k0 + T.w + 1])) return null;   // open ground: the floor is the building's
  const u = fx - i, v = fy - j, z = (a, b) => T.z[b * T.w + a];
  const zz = (z(i, j) * (1 - u) + z(i + 1, j) * u) * (1 - v) + (z(i, j + 1) * (1 - u) + z(i + 1, j + 1) * u) * v;
  return zz === zz ? zz - o[2] : null;
}
function near(x, y, r) {
  return S.items.filter(g => {
    const b = g.userData.box || (g.userData.box = new THREE.Box3().setFromObject(g));
    return !b.isEmpty() && x > b.min.x - r && x < b.max.x + r && y > b.min.y - r && y < b.max.y + r;
  });
}
function floorAt(x, y, fromZ) {
  S.ray.set(new THREE.Vector3(x, y, fromZ), new THREE.Vector3(0, 0, -1));
  S.ray.far = 80;
  const h = hits(S.ray, false, near(x, y, 0.1)).find(q => q.normal.z > FLOOR_UP && support(q.item)) || null;
  S.ray.far = Infinity;
  const g = groundAt(x, y);
  const f = h ? h.point.z : null;
  if (g != null && g <= fromZ && (f == null || g > f)) return g;
  return f;
}
function wallAhead(p, dir, len) {
  const list = near(p.x + dir.x * len / 2, p.y + dir.y * len / 2, len + BODY);
  if (!list.length) return false;
  for (const up of [STEP_UP + 0.1, 1.1, 1.6]) {
    S.ray.set(new THREE.Vector3(p.x, p.y, p.z - EYE + up), dir);
    S.ray.far = len + BODY;
    const w = hits(S.ray, false, list).find(q => Math.abs(q.normal.z) < 0.7 && support(q.item));
    S.ray.far = Infinity;
    if (w) return true;
  }
  return false;
}
// keep the eye over the floor: now (entering) or falling at 9 m/s; standing
// still on it, nothing to do
function settle(now, dt) {
  const p = S.camera.position, k = p.x.toFixed(3) + "," + p.y.toFixed(3) + "," + p.z.toFixed(3);
  if (!now && S.settled === k) return;
  const fl = floorAt(p.x, p.y, p.z - EYE + STEP_UP + 0.02);
  if (fl == null) return;
  const want = fl + EYE;
  if (now || want > p.z) p.z = want;
  else p.z = Math.max(want, p.z - 9 * (dt || 0.016));
  S.settled = p.x.toFixed(3) + "," + p.y.toFixed(3) + "," + p.z.toFixed(3);
}
function walk(mx, my, dt) {
  const f = new THREE.Vector3(-Math.sin(S.yaw), Math.cos(S.yaw), 0), r = new THREE.Vector3(Math.cos(S.yaw), Math.sin(S.yaw), 0);
  const d = new THREE.Vector3().addScaledVector(f, my).addScaledVector(r, mx);
  if (d.lengthSq() > 0) {
    const m = Math.min(1, d.length());          // the input eases in and out
    d.normalize().multiplyScalar((fast ? 7 : 3.5) * dt * m);
    const p = S.camera.position;
    // the whole step, or else along x or y alone (sliding along a wall)
    for (const s of [d, new THREE.Vector3(d.x, 0, 0), new THREE.Vector3(0, d.y, 0)]) {
      const len = s.length();
      if (len < 1e-5) continue;
      if (wallAhead(p, s.clone().divideScalar(len), len)) continue;
      if (floorAt(p.x + s.x, p.y + s.y, p.z - EYE + STEP_UP + 0.02) == null) continue;   // off the edge of the world
      p.add(s);
      break;
    }
  }
  settle(false, dt);
}
function headingOf(it) {
  // the item's facing in the world: its heading angle plus a quarter turn (local +y)
  // (a rifle on its side points its barrel, local +y, at minus alpha)
  const rot = it.rot || [0, 0, it.gamma || 0];
  return it.head === 0 ? -rot[0] : rot[2];
}

function setCut(v) {
  const el = S.el.querySelector(".v3d-cutv");
  if (v >= 100) {
    S.cut.constant = 1e6;
    el.textContent = "off";
  } else {
    // 0..99 -> 1 m under the item to 12 m over it
    const h = -1 + v / 99 * 13;
    S.cut.constant = h;
    el.textContent = (h >= 0 ? "+" : "") + h.toFixed(1) + " m";
  }
}
function setXray(on) {
  for (const g of S.items) {
    const it = g.userData.item;
    if (it.key === O.target.key || it.type !== "building") continue;
    g.traverse(c => {
      if (c.isMesh) {
        (Array.isArray(c.material) ? c.material : [c.material]).forEach(m => {
          m.transparent = on;
          m.opacity = on ? 0.22 : 1;
          m.depthWrite = !on;
        });
        c.castShadow = !on;
      }
    });
  }
}

// ------------------------------------------------------------------ picking
const ndc = new THREE.Vector2();
function cast(e, skipTarget) {
  const r = S.canvas.getBoundingClientRect();
  ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
  S.ray.setFromCamera(ndc, S.camera);
  return hits(S.ray, skipTarget);
}
function hits(ray, skipTarget, list) {
  const out = ray.intersectObjects(list || S.root.children, true);
  return out.filter(h => {
    if (!h.face || !h.object.isMesh) return false;
    const it = h.object.userData.item;
    if (!it) return false;
    if (skipTarget && it.key === O.target.key) return false;
    // see-through faces (nets, grilles, foliage cards) are not something to click or stand on
    const mm = h.object.material, mat = Array.isArray(mm) ? mm[h.face.materialIndex] : mm;
    if (mat && mat.alphaTest > 0 && it.key !== O.target.key) return false;
    // above the cut, nothing is there
    if (S.cut.constant < 1e5 && h.point.z > S.cut.constant && it.key !== O.target.key && it.type !== "terrain") return false;
    return true;
  }).map(h => {
    const n = h.face.normal.clone().transformDirection(h.object.matrixWorld);
    if (n.dot(ray.ray.direction) > 0) n.negate();     // the side that faces us
    return { point: h.point, normal: n, item: h.object.userData.item, dist: h.distance };
  });
}
// what a wall item hangs on: the first wall behind it, within a metre
function behind(p) {
  const it = O.target, o = O.origin, rot = p.rot || it.rot || [0, 0, 0];
  const h = rot[hi(it)] || 0;
  const back = new THREE.Vector3(Math.sin(h), -Math.cos(h), 0);
  S.ray.set(new THREE.Vector3(p.x - o[0], p.y - o[1], p.z - o[2] + (it.lift || 0) + 0.1), back);
  S.ray.far = 1.2;
  const w = hits(S.ray, true).filter(q => Math.abs(q.normal.z) < WALL_FLAT)[0];
  S.ray.far = Infinity;
  return w ? w.item.name : "";
}
// nothing stands on a rifle or a guard
function support(it) { return !/^(pickup|soldier|player|ghost|camera|switch|siren|alarmlight)$/.test(it.type); }
// the surface straight below a point (skipping the target); big: floors and
// ground only, not a lamp or a crate under it
function below(p, reach = 30, big = false) {
  S.ray.set(new THREE.Vector3(p.x, p.y, p.z + 0.05), new THREE.Vector3(0, 0, -1));
  S.ray.far = reach;
  const h = hits(S.ray, true).filter(q => q.normal.z > FLOOR_UP && support(q.item) &&
    (!big || q.item.type === "terrain" || q.item.type === "building")).find(() => true) || null;
  S.ray.far = Infinity;
  return h;
}
// the ceiling over the item: the first thing straight above it, within 8 m
function ceiling() {
  const m = S.target ? S.target.userData.body.children.find(c => c.isMesh) : null;
  const b = m ? new THREE.Box3().setFromObject(m) : null;
  if (!b || b.isEmpty()) return null;
  const c = b.getCenter(new THREE.Vector3());
  // from head height over the floor, so a shelf over a desk is not the ceiling
  const fl = below(new THREE.Vector3(c.x, c.y, b.min.z + 0.1), 30, true);
  const z0 = Math.max(b.max.z + 0.05, fl ? fl.point.z + 1.9 : -1e9);
  S.ray.set(new THREE.Vector3(c.x, c.y, z0), new THREE.Vector3(0, 0, 1));
  S.ray.far = 8;
  const h = hits(S.ray, true).find(q => q.item.type !== "terrain") || null;
  S.ray.far = Infinity;
  return h ? h.point.z : null;
}

// the lowest point of the target's own model, turned as it is: what rests on the floor
function footOf(it, rot) {
  it = it || O.target;
  const g = it.model ? geometryOf(it.model) : null;
  if (!g) return 0;
  const m = new THREE.Matrix4().makeRotationFromEuler(new THREE.Euler(rot[0] || 0, rot[1] || 0, rot[2] || 0, "ZYX"));
  const p = g.attributes.position, v = new THREE.Vector3();
  let lo = Infinity;
  const stepN = Math.max(1, Math.floor(p.count / 4000));
  for (let i = 0; i < p.count; i += stepN) {
    v.fromBufferAttribute(p, i).applyMatrix4(m);
    if (v.z < lo) lo = v.z;
  }
  return (lo === Infinity ? 0 : lo) + (it.lift || 0);
}

// ------------------------------------------------------------------ moving the target
function poseFrom(hit, e, it) {
  it = it || O.target;
  const o = O.origin;
  const rot = (it.rot || [0, 0, it.gamma || 0]).slice();
  if (it.kind === "wall") {
    const n = hit.normal;
    const g = Math.atan2(n.y, n.x) - Math.PI / 2 + (it === O.target ? S.turn : 0);
    rot[hi(it)] = g;
    return { x: hit.point.x + n.x * WALL_OFF + o[0], y: hit.point.y + n.y * WALL_OFF + o[1],
      z: hit.point.z + o[2], rot, on: hit.item.name, gamma: g };
  }
  return { x: hit.point.x + o[0], y: hit.point.y + o[1], z: hit.point.z + o[2] - footOf(it, rot),
    rot, on: hit.item.name, gamma: headOf(it, rot) };
}
function surfaceFor(e, it) {
  it = it || O.target;
  const hs = cast(e, it === O.target).filter(h => support(h.item));   // an item in hand can go onto the one being edited
  if (!hs.length) return null;
  if (it.kind === "wall") return hs.filter(h => Math.abs(h.normal.z) < WALL_FLAT && h.item.type !== "terrain")[0] || null;
  const first = hs[0];
  if (first.normal.z > FLOOR_UP) return first;
  // a wall under the pointer: the floor at its foot, on this side of it
  const p = first.point.clone().add(first.normal.clone().multiplyScalar(0.3));
  p.z += 0.3;
  return below(p, 60);
}
function applyPose(p) {
  const it = O.target;
  it.x = p.x; it.y = p.y; it.z = p.z; it.rot = p.rot;
  if (S.target) place(S.target, it);
  readout(p);
}

// ------------------------------------------------------------------ the mouse: looking, or editing
// Looking, the pointer is locked to the view and the mouse turns it. Holding Alt
// lets it go, to edit; so does an item in hand or adding walkway points, which
// need a pointer to aim with.
const SENS = 0.0024;            // radians of turn per pixel of mouse
function lockable() { return !!S && !S.dead && !S.placing && !S.addingNode; }
function lock() {
  if (!lockable() || S.el.hidden || document.pointerLockElement === S.canvas) return;
  try {
    const p = S.canvas.requestPointerLock();
    if (p && p.catch) p.catch(() => hint());
  } catch (e) { hint(); }
}
function unlock() { if (document.pointerLockElement === S.canvas) document.exitPointerLock(); }
function onLockChange() {
  if (!S) return;
  const was = S.locked;
  S.locked = document.pointerLockElement === S.canvas;
  // Esc frees the mouse without closing the view (see onKey)
  if (was && !S.locked && !S.altUnlock) S.lockLostAt = performance.now();
  S.altUnlock = false;
  S.el.classList.toggle("looking", S.locked);
  if (S.locked) tip(null);
  hint();
}
function hint() {
  if (!S) return;
  S.el.querySelector(".v3d-hint").hidden = S.locked || S.alt || !!S.placing || !!S.addingNode || S.el.hidden || !!S.dead;
}
function editing() { if (S) { S.el.classList.toggle("editing", !!S.alt); hint(); } }
// in the middle of the view, while looking: what the crosshair is on
function centreTip() {
  const r = S.canvas.getBoundingClientRect(), e = { clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 };
  const h = cast(e, false)[0];
  tip(h ? h.item : null, e);
}
function onDown(e) {
  S.canvas.focus();
  // looking: the mouse turns the view, and a click does nothing
  if (S.locked) { e.preventDefault(); return; }
  // not editing: a click takes the mouse back to looking
  if (e.button === 0 && !e.altKey && lockable()) { lock(); return; }
  try { S.canvas.setPointerCapture(e.pointerId); } catch (err) { /* a synthetic pointer */ }
  const hs = cast(e, false);
  const h = hs[0];
  S.down = { x: e.clientX, y: e.clientY, hit: h || null, moved: false };
  // Alt: whatever is under the pointer is taken, the item being edited or any
  // other one (it becomes the one being edited, the view kept), and moved
  if (e.button === 0 && e.altKey && h) {
    if (h.item.key !== O.target.key && pickable(h.item) && O.onPick) O.onPick(h.item.key);
    const t = O.target;
    if (h.item.key === t.key && t.editable && t.kind !== "fixed") {
      S.drag = { lift: e.shiftKey, y0: e.clientY, z0: t.z, pose: null };
      return;
    }
  }
  // a walkway point where the floor is clicked (on release, if it was a click)
  if (S.addingNode && e.button === 0) { S.look = { orbit: false, x: e.clientX, y: e.clientY, yaw: S.yaw, pitch: S.pitch,
    pivot: itemCentre(), pos: S.camera.position.clone() }; return; }
  // looking around (left) or circling the item (right)
  S.look = { orbit: e.button === 2 && !S.walking, x: e.clientX, y: e.clientY, yaw: S.yaw, pitch: S.pitch,
    pivot: itemCentre(), pos: S.camera.position.clone() };
}
function onMove(e) {
  if (S.locked) {
    S.yaw -= (e.movementX || 0) * SENS;
    S.pitch -= (e.movementY || 0) * SENS;
    applyLook();
    centreTip();
    return;
  }
  if (S.down && Math.hypot(e.clientX - S.down.x, e.clientY - S.down.y) > 4) S.down.moved = true;
  if (S.look) {
    const L = S.look, dx = e.clientX - L.x, dy = e.clientY - L.y, k = 0.0042;
    if (L.orbit) {
      // round the item: the camera's offset from it turned, and looking at it
      const off = new THREE.Vector3().subVectors(L.pos, L.pivot);
      const r = off.length(), a0 = Math.atan2(off.y, off.x), e0 = Math.asin(Math.max(-1, Math.min(1, off.z / (r || 1))));
      const a = a0 - dx * k, el = Math.max(-1.45, Math.min(1.45, e0 + dy * k));
      S.camera.position.set(L.pivot.x + r * Math.cos(el) * Math.cos(a), L.pivot.y + r * Math.cos(el) * Math.sin(a), L.pivot.z + r * Math.sin(el));
      lookAt(L.pivot);
    } else {
      S.yaw = L.yaw - dx * k;
      S.pitch = L.pitch - dy * k;
      applyLook();
    }
    tip(null);
    return;
  }
  if (S.drag) {
    const it = O.target;
    let p;
    if (S.drag.lift || e.shiftKey && S.drag.pose) {
      // straight up or down: a metre per so many pixels at this distance
      const d = S.camera.position.distanceTo(itemCentre());
      const dz = (S.drag.y0 - e.clientY) * d / 600;
      p = { x: it.x, y: it.y, z: S.drag.z0 + dz, rot: (it.rot || [0, 0, 0]).slice(), on: "", gamma: headOf(it, it.rot) };
    } else {
      const h = surfaceFor(e);
      if (!h) return;
      p = poseFrom(h, e);
    }
    S.drag.pose = p;
    applyPose(p);
    return;
  }
  if (e.buttons) { tip(null); return; }
  if (S.placing && S.ghost) { ghostAt(e); tip(null); return; }
  const h = cast(e, false)[0];
  tip(h ? h.item : null, e);
}
function onUp(e) {
  const d = S.down;
  S.down = null;
  S.look = null;
  try { S.canvas.releasePointerCapture(e.pointerId); } catch (err) { /* already released */ }
  // Alt was let go during the drag: the view is taken back now it is done
  if (S.relockAfterUp && !S.alt) { S.relockAfterUp = false; setTimeout(lock, 0); }
  if (S.drag) {
    const pose = S.drag.pose;
    S.drag = null;
    if (pose) commit(pose);
    return;
  }
  if (e.button !== 0) return;
  if (d && !d.moved && S.addingNode) {
    const h = cast(e, false).find(q => q.normal.z > FLOOR_UP && support(q.item));
    if (h && O.onAddNode) O.onAddNode({ x: +(h.point.x + O.origin[0]).toFixed(2), y: +(h.point.y + O.origin[1]).toFixed(2),
      z: +(h.point.z + O.origin[2]).toFixed(2) });
    return;
  }
  // with an item in hand, a click puts it down
  if (d && !d.moved && S.placing && S.ghost) {
    const p = ghostAt(e);
    if (p && O.onPlace) O.onPlace({ x: +p.x.toFixed(3), y: +p.y.toFixed(3), z: +p.z.toFixed(3),
      gamma: +headOf(S.ghost.userData.item, p.rot).toFixed(5), on: p.on || "" });
    return;
  }
  // a click on something else: that one instead (to edit, or just to look at)
  if (d && !d.moved && d.hit && d.hit.item.key !== O.target.key && pickable(d.hit.item) && O.onPick) O.onPick(d.hit.item.key);
}
function commit(p) {
  const it = O.target;
  it.x = p.x; it.y = p.y; it.z = p.z; it.rot = p.rot;
  // the editor's heading: the angle that carries it, less what the level added
  if (O.onMove) O.onMove(it.key, { x: +p.x.toFixed(3), y: +p.y.toFixed(3), z: +p.z.toFixed(3),
    gamma: +headOf(it, p.rot).toFixed(5), on: p.on || "" });
  readout(p);
}
function turnBy(a) {
  const it = O.target;
  if (!it.editable || it.kind === "fixed") return;
  const rot = (it.rot || [0, 0, 0]).slice();
  rot[hi(it)] = (rot[hi(it)] || 0) + sgn(it) * a;      // R turns anticlockwise, whatever carries it
  S.turn += a;
  const p = { x: it.x, y: it.y, z: it.z, rot, on: "" };
  applyPose(p);
  commit(p);
}
function nudge(dx, dy, dz) {
  const it = O.target;
  if (!it.editable || it.kind === "fixed") return;
  // along the view: "up" is away from the camera
  const f = dirOf(S.yaw, 0);
  const r = new THREE.Vector3(f.y, -f.x, 0);
  const p = { x: it.x + r.x * dx + f.x * dy, y: it.y + r.y * dx + f.y * dy, z: it.z + dz, rot: (it.rot || [0, 0, 0]).slice(), on: "" };
  applyPose(p);
  commit(p);
}
// Flying: arrows or W A S D move the view while held, Q and E take it down and up,
// Shift is faster. The item itself nudges with Ctrl and the same keys.
const FLY = { ArrowUp: [0, 1, 0], w: [0, 1, 0], ArrowDown: [0, -1, 0], s: [0, -1, 0],
  ArrowLeft: [-1, 0, 0], a: [-1, 0, 0], ArrowRight: [1, 0, 0], d: [1, 0, 0],
  q: [0, 0, -1], PageDown: [0, 0, -1], e: [0, 0, 1], PageUp: [0, 0, 1] };
const held = new Set();
let fast = false, lastT = 0;
const vel = new THREE.Vector3();          // the free camera's speed, metres a second
const wm = { x: 0, y: 0 };                // walking's eased input
const EASE_IN = 9, GLIDE = 4.2;           // how fast it gets going, and how long it glides
function flyKey(k) { return FLY[k] ? k : FLY[k.toLowerCase()] ? k.toLowerCase() : null; }
function fly(now) {
  const dt = Math.min(0.1, lastT ? (now - lastT) / 1000 : 0);
  lastT = now;
  if (!dt) return;
  let mx = 0, my = 0, mz = 0;
  held.forEach(k => { const v = FLY[k]; mx += v[0]; my += v[1]; mz += v[2]; });
  if (S.walking) {
    const k = 1 - Math.exp(-(mx || my ? EASE_IN : GLIDE * 1.6) * dt);
    wm.x += (mx - wm.x) * k; wm.y += (my - wm.y) * k;
    if (!mx && !my && Math.abs(wm.x) < 0.02 && Math.abs(wm.y) < 0.02) { wm.x = wm.y = 0; settle(false, dt); return; }
    walk(wm.x, wm.y, dt);
    return;
  }
  // forward is where it looks, up and down included, as a spectator flies
  const f = dirOf(S.yaw, S.pitch), r = new THREE.Vector3(Math.cos(S.yaw), Math.sin(S.yaw), 0);
  const want = new THREE.Vector3().addScaledVector(f, my).addScaledVector(r, mx);
  want.z += mz;
  if (want.lengthSq() > 1) want.normalize();
  want.multiplyScalar(fast ? 32 : 11);
  vel.lerp(want, 1 - Math.exp(-(want.lengthSq() ? EASE_IN : GLIDE) * dt));
  if (!want.lengthSq() && vel.lengthSq() < 0.0004) { vel.set(0, 0, 0); return; }
  S.camera.position.addScaledVector(vel, dt);
}
function onKeyUp(e) {
  const k = flyKey(e.key);
  if (k) held.delete(k);
  fast = e.shiftKey;
  if (e.key === "Alt" && S && !S.el.hidden) {
    // the browser's own use of a lone Alt (its menu) would take the keys away
    e.preventDefault();
    S.alt = false;
    if (S.relock) {
      S.relock = false;
      if (S.drag || S.look) S.relockAfterUp = true; else lock();
    }
    editing();
  }
}
function onKey(e) {
  if (!S || S.el.hidden) return;
  if (e.target && /INPUT|TEXTAREA|SELECT/.test(e.target.tagName) && e.target.type !== "range" && e.target.type !== "checkbox") return;
  const k = e.key, ctrl = e.ctrlKey || e.metaKey, st = e.shiftKey ? 0.5 : e.altKey ? 0.01 : 0.05;
  let used = true;
  fast = e.shiftKey;
  // Alt: the mouse is let go, to edit; letting go of Alt takes the view back
  if (k === "Alt") {
    e.preventDefault();
    if (!S.alt) {
      S.alt = true;
      S.relock = S.locked;
      if (S.locked) { S.altUnlock = true; unlock(); }
      editing();
    }
    return;
  }
  if (k === "Escape") {
    // the Esc that freed the mouse is not the one that closes the view
    if (document.pointerLockElement === S.canvas || performance.now() - (S.lockLostAt || 0) < 300) { e.preventDefault(); return; }
    if (S.placing && O.onCancelPlace) O.onCancelPlace(); else close();
  }
  else if (ctrl && k === "ArrowLeft") nudge(-st, 0, 0);
  else if (ctrl && k === "ArrowRight") nudge(st, 0, 0);
  else if (ctrl && k === "ArrowUp") nudge(0, st, 0);
  else if (ctrl && k === "ArrowDown") nudge(0, -st, 0);
  else if (ctrl && k === "PageUp") nudge(0, 0, st);
  else if (ctrl && k === "PageDown") nudge(0, 0, -st);
  else if (ctrl) used = false;              // undo, redo and saving belong to the editor
  else if (flyKey(k)) held.add(flyKey(k));
  else if (k === "r" || k === "R") turnBy((e.shiftKey ? -1 : 1) * (e.altKey ? Math.PI / 180 : STEP));
  else if (k === "t" || k === "T") setView("top");
  else if (k === "g" || k === "G") setView(S.walking ? "orbit" : "walk");
  else if (k === "f" || k === "F") setView("orbit");
  else used = false;
  if (used) { e.preventDefault(); e.stopPropagation(); }
}

// ------------------------------------------------------------------ an item in hand
function setPlacing(p) {
  if (!S || S.dead) return;
  if (S.ghost) { S.root.remove(S.ghost); S.ghost.traverse(c => { if (c.material) c.material.dispose(); }); S.ghost = null; }
  S.placing = p || null;
  if (p) unlock();                        // an item in hand is aimed with the pointer
  if (p) {
    const it = Object.assign({ key: "ghost", name: p.label, type: "ghost", x: 0, y: 0, z: 0 }, p);
    const g = new THREE.Group(), body = new THREE.Group();
    body.position.z = it.lift || 0;
    const geo = it.model ? geometryOf(it.model) : null;
    const mat = new THREE.MeshLambertMaterial({ color: COL.own, transparent: true, opacity: 0.55, depthWrite: false,
      side: THREE.DoubleSide, flatShading: true });
    const mesh = new THREE.Mesh(geo || new THREE.BoxGeometry(0.4, 0.4, 1), mat);
    if (!geo) mesh.position.z = 0.5;
    mesh.raycast = () => {};
    body.add(mesh);
    if (geo && it.gun && it.grip) body.add(gunOf(it, false, mat));
    g.add(body);
    g.visible = false;
    g.userData.item = it;
    S.ghost = g;
    S.root.add(g);
  }
  if (isOpen()) help();
}
function ghostAt(e) {
  const it = S.ghost.userData.item, h = surfaceFor(e, it);
  if (!h) { S.ghost.visible = false; return null; }
  const p = poseFrom(h, e, it);
  it.x = p.x; it.y = p.y; it.z = p.z; it.rot = p.rot;
  place(S.ghost, it);
  S.ghost.visible = true;
  return p;
}
function help() {
  const t = O.target, pl = S.placing;
  hint();
  if (S.addingNode) {
    S.el.querySelector(".v3d-help").innerHTML = "<b>Click a floor</b> or the ground to add a walkway point there · drag to look around · " +
      "<b>Add walkway point</b> again to stop";
    return;
  }
  const look = "The mouse looks around, <b>W A S D</b> " + (S.walking ? "walk" : "fly") + (S.walking ? "" : ", <b>Q E</b> down and up") +
    ", <b>Shift</b> fast · <b>Esc</b> frees the mouse, again to close";
  if (S.walking && !pl) {
    S.el.querySelector(".v3d-help").innerHTML = "<b>Walking</b> · " + look + "<br>Hold <b>Alt</b> to edit · <b>G</b> or another view to fly again";
    return;
  }
  S.el.querySelector(".v3d-help").innerHTML = pl ?
    "<b>Click</b> to put " + esc(pl.label) + " down " + (pl.kind === "wall" ? "on a wall" : "on a floor, a desk or the ground") +
    " · <b>Esc</b> to stop placing<br>Drag to look around, <b>WASD</b> to fly, <b>Q E</b> down and up, <b>Shift</b> fast" :
    look + "<br>Hold <b>Alt</b> to edit: click to select, <b>Alt+drag</b> moves anything, <b>Shift+Alt+drag</b> up and down, " +
    "<b>Alt+right-drag</b> round it" + (t.editable && t.kind !== "fixed" ? " · <b>R</b> turn · <b>Ctrl+arrows</b> nudge 5 cm" : "");
}

// ------------------------------------------------------------------ what it stands on
// the camera has gone well past where the close-up put it: the readout says
// where you are rather than what the item stands on
function away() {
  const p = S.camera.position, t = O.target, o = O.origin;
  return Math.hypot(p.x - (t.x - o[0]), p.y - (t.y - o[1])) > Math.max(O.radius, S.openD || 0) + 15;
}
function youReadout() {
  const el = S.el.querySelector(".v3d-read"), o = O.origin, p = S.camera.position;
  const feet = S.walking ? p.z - EYE : p.z, g = groundAt(p.x, p.y);
  el.innerHTML = `<span class="k">you</span>${(p.x + o[0]).toFixed(1)}, ${(p.y + o[1]).toFixed(1)}, ${(feet + o[2]).toFixed(1)}` +
    (g != null ? `<br><span class="k">${S.walking ? "ground" : "over"}</span>` +
      (S.walking ? `${(feet - g) > 0.3 ? (feet - g).toFixed(1) + " m below you" : "under your feet"}` : `${(p.z - g).toFixed(1)} m over the ground`) : "");
}
function readout(p) {
  if (!p && away()) return youReadout();
  const it = O.target, el = S.el.querySelector(".v3d-read"), o = O.origin;
  p = p || it;
  // a building from its base (its foundation goes into the ground), anything else from its lowest point
  const pos = new THREE.Vector3(p.x - o[0], p.y - o[1], p.z - o[2] +
    (it.type === "building" ? 0.3 : footOf(it, p.rot || it.rot || [0, 0, 0]) + 0.02));
  let rows = [];
  if (it.kind === "wall") {
    rows.push(`<span class="k">on</span>${esc(p.on || behind(p) || it.on || "nothing behind it")}`);
    const fl = below(pos, 40, true);
    if (fl) rows.push(`<span class="k">height</span>${(pos.z - fl.point.z).toFixed(2)} m over ${esc(fl.item.name)}`);
  } else {
    const fl = below(pos, 40, it.type === "building");
    if (fl) {
      const gap = pos.z - 0.02 - fl.point.z;
      rows.push(`<span class="k">on</span>${esc(fl.item.name)}` +
        (Math.abs(gap) > 0.03 ? ` <span class="bad">${gap > 0 ? gap.toFixed(2) + " m above it" : (-gap).toFixed(2) + " m into it"}</span>` : ""));
    } else rows.push(`<span class="k">on</span><span class="bad">nothing under it</span>`);
  }
  rows.push(`<span class="k">at</span>${p.x.toFixed(2)}, ${p.y.toFixed(2)}, ${p.z.toFixed(2)}`);
  el.innerHTML = rows.join("<br>");
}
function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]); }
function pickable(it) { return !!it && it.type !== "terrain" && /^(own|ref):/.test(it.key || ""); }
function tip(it, e) {
  const t = S.el.querySelector(".v3d-tip");
  if (!it || it.type === "terrain") { t.hidden = true; return; }
  const r = S.el.getBoundingClientRect();
  t.innerHTML = esc(it.name) + (it.key === O.target.key ? (O.target.editable && O.target.kind !== "fixed" ? " <i>Alt+drag to move</i>" : "") :
    it.editable ? " <i>Alt+drag to move</i>" : pickable(it) ? " <i>Alt+click to look at it</i>" : "");
  t.style.left = (e.clientX - r.left) + "px";
  t.style.top = (e.clientY - r.top) + "px";
  t.hidden = false;
}

// ------------------------------------------------------------------ the loop
function resize() {
  const c = S.canvas, w = c.clientWidth, h = c.clientHeight;
  if (!w || !h) return;
  if (w !== S.size[0] || h !== S.size[1]) {
    S.size = [w, h];
    S.renderer.setSize(w, h, false);
    S.camera.aspect = w / h;
    S.camera.updateProjectionMatrix();
  }
}
function loop() {
  if (!S || S.el.hidden) { S && (S.raf = 0); return; }
  resize();
  const now = performance.now();
  fly(now);
  explore(now);
  S.renderer.render(S.scene, S.camera);
  S.raf = requestAnimationFrame(loop);
}

// ------------------------------------------------------------------ the API
function open(opts) {
  const keep = S && !S.el.hidden && opts.keepView;
  const camState = keep ? { p: S.camera.position.clone(), yaw: S.yaw, pitch: S.pitch, o: O.origin } : null;
  O = opts;
  O.origin = [opts.target.x, opts.target.y, opts.target.z];
  if (S) { S.centre = [O.origin[0], O.origin[1]]; S.exploredAt = 0; S.cutFreed = false; }
  if (!S) { S = build(opts.host); S.centre = [O.origin[0], O.origin[1]]; }
  if (S.dead) { S.el.hidden = false; return; }
  if (S.el.parentNode !== opts.host) opts.host.appendChild(S.el);
  S.el.hidden = false;
  S.el.querySelector(".v3d-title").textContent = opts.target.name || "Item";
  S.el.querySelector(".v3d-sub").textContent = opts.target.sub ? opts.target.sub : opts.target.editable ?
    (opts.target.kind === "wall" ? "hangs on walls" : opts.target.kind === "fixed" ? "stays where it is" : "stands on floors") :
    "the level's own - not movable";
  const rad = S.el.querySelector(".v3d-rad");
  rad.value = opts.radius;
  S.el.querySelector(".v3d-radv").textContent = rad.value + " m";
  const camBtn = S.el.querySelector('[data-g="view"] [data-v="cam"]');
  camBtn.hidden = !opts.target.cam;
  const holding = S.placing;
  fill();
  S.ghost = null;
  setPlacing(holding);
  help();
  const cutEl = S.el.querySelector(".v3d-cut");
  if (!keep) {
    // inside a building: cut just below the ceiling over it, so the room is open
    // (outdoors nothing is cut - not a dome's overhang, not a tree)
    setCut(100);
    const top = opts.inside ? ceiling() : null;
    const h = top != null ? top - 0.08 : opts.inside ? 2.6 : null;
    const v = h == null ? 100 : Math.max(0, Math.min(99, Math.round((h + 1) / 13 * 99)));
    cutEl.value = v;
    setCut(v);
    if (v < 100) S.cut.constant = h;       // exactly under the ceiling, not the slider's step
    S.el.querySelector(".v3d-xray").checked = false;
  }
  setXray(S.el.querySelector(".v3d-xray").checked);
  if (camState) {
    // the same view of the world, from the new origin
    const d = new THREE.Vector3(camState.o[0] - O.origin[0], camState.o[1] - O.origin[1], camState.o[2] - O.origin[2]);
    S.camera.position.copy(camState.p.add(d));
    S.yaw = camState.yaw;
    S.pitch = camState.pitch;
    applyLook();
  } else setView(opts.view || "orbit");
  S.openD = Math.hypot(S.camera.position.x - (opts.target.x - O.origin[0]), S.camera.position.y - (opts.target.y - O.origin[1]));
  readout();
  if (!S.raf) S.raf = requestAnimationFrame(loop);
  S.canvas.focus();
  // opened fresh (a click, so the browser allows it): the mouse is the view's
  if (!keep) { vel.set(0, 0, 0); if (!S.alt) lock(); }
  hint();
}
function close() {
  if (!S) return;
  unlock();
  S.el.hidden = true;
  S.drag = null;
  S.alt = false;
  editing();
  const cb = O && O.onClose;
  if (cb) cb();
}
function isOpen() { return !!S && !S.el.hidden && !S.dead; }
// The plan changed outside the close-up: the panel turned or moved something,
// undo, what rests on a moved crate came along. The same scene, brought up to
// date and seen from where you are: what only moved or turned is moved, what
// looks different is made again, what is gone goes.
const LOOK = ["model", "type", "own", "solid", "lift", "cam", "name"];
function update(opts) {
  if (!isOpen() || !O || S.drag) return;
  if (opts.target && opts.target.key !== O.target.key) return;
  if (opts.target) Object.assign(O.target, opts.target);
  const next = new Map((opts.objects || []).map(it => [it.key, it]));
  const same = (a, b) => LOOK.every(k => JSON.stringify(a[k]) === JSON.stringify(b[k]));
  for (const [k, g] of S.byKey) {
    if (next.has(k)) continue;
    S.root.remove(g); drop(g); S.byKey.delete(k);
    S.items.splice(S.items.indexOf(g), 1);
  }
  for (const it of next.values()) {
    const g = S.byKey.get(it.key);
    if (g && same(g.userData.item, it)) {
      Object.assign(g.userData.item, it);      // the meshes share this object
      place(g, g.userData.item);
      g.userData.box = null;
      continue;
    }
    if (g) { S.root.remove(g); drop(g); S.items.splice(S.items.indexOf(g), 1); }
    const n = makeItem(it);
    S.root.add(n); S.items.push(n); S.byKey.set(it.key, n);
  }
  S.target = S.byKey.get(O.target.key) || null;
  if (S.el.querySelector(".v3d-xray").checked) setXray(true);
  if ("nav" in opts) { O.nav = opts.nav; makeNav(); }
  readout();
}
function follow(pose) {
  if (!isOpen() || !O) return;
  const it = O.target;
  Object.assign(it, pose);
  if (S.target) place(S.target, it);
  readout();
}

// where a point of the world is on the screen (client pixels) - for the tests
function screenOf(x, y, z) {
  if (!isOpen()) return null;
  const o = O.origin, v = new THREE.Vector3(x - o[0], y - o[1], z - o[2]).project(S.camera);
  const r = S.canvas.getBoundingClientRect();
  return [r.left + (v.x + 1) / 2 * r.width, r.top + (1 - v.y) / 2 * r.height];
}

window.View3D = { open, close, isOpen, follow, update, screenOf, setPlacing, target: () => O && O.target,
  cam: () => S ? [S.camera.position.x, S.camera.position.y, S.camera.position.z] : null,
  walking: () => !!(S && S.walking), navCount: () => (S && S.nav ? S.nav.children.length : 0),
  // what a step forward meets - for the tests
  walkProbe: () => {
    if (!S) return null;
    const p = S.camera.position, f = new THREE.Vector3(-Math.sin(S.yaw), Math.cos(S.yaw), 0), out = [];
    for (const up of [STEP_UP + 0.1, 1.1, 1.6]) {
      S.ray.set(new THREE.Vector3(p.x, p.y, p.z - EYE + up), f); S.ray.far = 0.65;
      out.push(hits(S.ray, false).map(q => q.item.name + " nz " + q.normal.z.toFixed(2) + " d " + q.dist.toFixed(2)).join("; "));
      S.ray.far = Infinity;
    }
    return { floor: floorAt(p.x + f.x * 0.35, p.y + f.y * 0.35, p.z - EYE + STEP_UP + 0.02), eye: p.z, rays: out };
  },
  look: () => S ? [S.yaw, S.pitch] : null,
  // for the tests: the camera at a world point, looking at another
  lookFrom: (x, y, z, tx, ty, tz) => {
    if (!S) return; const o = O.origin;
    S.camera.position.set(x - o[0], y - o[1], z - o[2]); S.exploredAt = -1e9; explore(performance.now());
    lookAt(new THREE.Vector3(tx - o[0], ty - o[1], tz - o[2]));
  },
  // for the tests: the camera at a point of the world, what is loaded round it
  goTo: (x, y, z) => { if (!S) return; const o = O.origin; S.camera.position.set(x - o[0], y - o[1], z - o[2]); S.exploredAt = -1e9; explore(performance.now()); },
  loaded: () => S ? { items: S.items.length, centre: S.centre, terrain: O.terrain ? [O.terrain.x0, O.terrain.y0, O.terrain.w, O.terrain.h] : null,
    keys: S.items.map(g => g.userData.item.name) } : null,
  // for the tests: the camera d metres from an item, from the side at angle a
  // (0 = north of it), a little above its middle, looking at it
  closeTo: (k, d, a) => {
    const g = S && S.byKey.get(k);
    if (!g) return false;
    const c = new THREE.Box3().setFromObject(g).getCenter(new THREE.Vector3());
    S.camera.position.set(c.x - Math.sin(a) * d, c.y + Math.cos(a) * d, c.z + d * 0.25);
    lookAt(c);
    return true;
  },
  // how an item is drawn now: position and turn - for the tests
  shown: k => { const g = S && S.byKey.get(k); return g ? { p: g.position.toArray().map(v => +v.toFixed(3)),
    r: [g.rotation.x, g.rotation.y, g.rotation.z].map(v => +v.toFixed(3)) } : null; },
  // for the tests: fly for so many milliseconds with the keys held now
  flyFor: ms => { const t0 = performance.now(); lastT = t0; fly(t0 + ms); S.exploredAt = -1e9; explore(t0 + ms); },
  // what is under a screen point - for the tests
  probe: (x, y) => { const h = isOpen() ? cast({ clientX: x, clientY: y }, false)[0] : null;
    return h ? { name: h.item.name, key: h.item.key, type: h.item.type, nz: +h.normal.z.toFixed(2) } : null; } };
window.dispatchEvent(new Event("view3d-ready"));
