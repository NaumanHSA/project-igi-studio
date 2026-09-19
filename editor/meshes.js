/* Top-down renders of the game's own models, the way the map computer shows
 * buildings: lit from the north-west, higher parts brighter, edges traced where
 * the height jumps.
 *
 * data/meshes.bin (built by studio/extract/meshes.py) holds every structure's render
 * mesh; a model is drawn once per zoom bucket into a small canvas, in model
 * space, and the plan draws that canvas at the object's position and rotation.
 *
 *   MeshSprites.load(base)            -> Promise, once
 *   MeshSprites.has(model)            -> bool
 *   MeshSprites.sprite(model, ppm, palette)
 *       -> {img, x0, y1, w, h}        img covers model x0..x0+w, y1-h..y1 (metres)
 *   MeshSprites.PALETTES              green (shipped), solid (vehicles and solid props), own, ok, warn, bad
 *   MeshSprites.viewer()              a 3D preview: {el, set(model, palette), stop()}
 *                                     drag to turn, wheel to zoom, double-click to spin
 */
(function (global) {
  "use strict";

  var INDEX = null, BUF = null, loading = null, CACHE = {}, GEOM = {}, GRIPS = {};
  var KINDS = {}, PICKUPS = {};   // model -> "character" | "item"; pickup id -> model
  var MAX_PX = 1600;

  var PALETTES = {
    green: { lo: [8, 34, 14], hi: [150, 250, 150], edge: [200, 255, 200] },
    // darker, with bright edges, so a truck in a yard or a plane under a hangar roof stands out
    solid: { lo: [12, 48, 20], hi: [104, 196, 104], edge: [225, 255, 225] },
    own:   { lo: [46, 36, 6], hi: [255, 222, 110], edge: [255, 240, 170] },
    ok:    { lo: [10, 44, 16], hi: [120, 255, 140], edge: [190, 255, 200] },
    warn:  { lo: [52, 34, 4], hi: [255, 190, 80], edge: [255, 225, 160] },
    bad:   { lo: [56, 10, 8], hi: [255, 110, 96], edge: [255, 190, 180] }
  };

  function inflate(buf) {
    return new Response(new Blob([buf]).stream().pipeThrough(new DecompressionStream("deflate"))).arrayBuffer();
  }

  function load(base) {
    if (loading) return loading;
    if (typeof DecompressionStream === "undefined") return (loading = Promise.resolve(false));
    var v = "?v=" + Date.now();
    loading = Promise.all([
      fetch(base + "meshes.json" + v).then(function (r) { return r.ok ? r.json() : null; }),
      fetch(base + "meshes.bin" + v).then(function (r) { return r.ok ? r.arrayBuffer() : null; })
    ]).then(function (res) {
      if (!res[0] || !res[1]) return false;
      return inflate(res[1]).then(function (raw) {
        INDEX = res[0].models; BUF = raw;
        KINDS = res[0].kinds || {}; PICKUPS = res[0].pickups || {}; GRIPS = res[0].grips || {};
        return true;
      });
    }).catch(function () { return false; });
    return loading;
  }

  function has(model) { return !!(INDEX && model && INDEX[model]); }

  // Several models as one, for the previews: parts [{model, x, y, z, g}] (g a
  // turn about z, radians), under a key of the caller's; a part may itself be
  // one made here (a guard with his gun). Asked again, the key is made anew.
  // Parts past 65535 vertices are left out (the faces index them in 16 bits).
  function composite(key, parts) {
    if (!INDEX || !key || !parts) return null;
    var list = [], nv = 0, nf = 0, ext = 1;
    parts.forEach(function (p) {
      if (!p || !has(p.model) || p.model === key) return;
      var e = INDEX[p.model];
      if (nv + e[1] > 65535) return;
      var b = bounds(p.model), r = Math.max(Math.abs(b.minx), Math.abs(b.maxx), Math.abs(b.miny), Math.abs(b.maxy));
      ext = Math.max(ext, Math.abs(p.x || 0) + r, Math.abs(p.y || 0) + r, Math.abs(p.z || 0) + Math.max(Math.abs(b.minz), Math.abs(b.maxz)));
      list.push(p); nv += e[1]; nf += e[2];
    });
    if (!list.length) return null;
    var sc = ext < 300 ? 0.01 : ext < 600 ? 0.02 : 0.05;
    var buf = new ArrayBuffer(nv * 6 + nf * 6), v = new Int16Array(buf, 0, nv * 3), f = new Uint16Array(buf, nv * 6, nf * 3);
    var vo = 0, fo = 0;
    list.forEach(function (p) {
      var e = INDEX[p.model], s2 = e[3], c = Math.cos(p.g || 0), sn = Math.sin(p.g || 0);
      var vi = new Int16Array(e[5] || BUF, e[0], e[1] * 3), fi = new Uint16Array(e[5] || BUF, e[0] + e[1] * 6, e[2] * 3);
      for (var i = 0; i < e[1]; i++) {
        var x = vi[i * 3] * s2, y = vi[i * 3 + 1] * s2, z = vi[i * 3 + 2] * s2;
        var X = (p.x || 0) + x * c - y * sn, Y = (p.y || 0) + x * sn + y * c, Z = (p.z || 0) + z;
        v[(vo + i) * 3] = Math.max(-32768, Math.min(32767, Math.round(X / sc)));
        v[(vo + i) * 3 + 1] = Math.max(-32768, Math.min(32767, Math.round(Y / sc)));
        v[(vo + i) * 3 + 2] = Math.max(-32768, Math.min(32767, Math.round(Z / sc)));
      }
      for (var j = 0; j < e[2] * 3; j++) f[fo * 3 + j] = fi[j] + vo;
      vo += e[1]; fo += e[2];
    });
    INDEX[key] = [0, nv, nf, sc, "c", buf];
    delete GEOM[key]; delete GEOM3[key]; delete SURF[key];
    Object.keys(CACHE).forEach(function (k) { if (k.indexOf(key + "|") === 0) delete CACHE[k]; });
    return key;
  }

  // A character with its weapon in its hands, as one model for the previews:
  // "003_01_1+100_01_1", the gun's vertices put on the character's grip
  // (meshes.json "grips"). Its own buffer, in the same layout as the others.
  // The character alone when either is missing.
  function armed(model, gun) {
    if (!has(model) || !has(gun) || !GRIPS[model]) return model;
    var key = model + "+" + gun;
    if (INDEX[key]) return key;
    var a = INDEX[model], b = INDEX[gun], g = GRIPS[model], sc = a[3], sb = b[3];
    var na = a[1], nb = b[1], fa = a[2], fb = b[2];
    if (na + nb > 65535) return model;
    var buf = new ArrayBuffer((na + nb) * 6 + (fa + fb) * 6);
    var v = new Int16Array(buf, 0, (na + nb) * 3), f = new Uint16Array(buf, (na + nb) * 6, (fa + fb) * 3);
    v.set(new Int16Array(a[5] || BUF, a[0], na * 3));
    f.set(new Uint16Array(a[5] || BUF, a[0] + na * 6, fa * 3));
    var vb = new Int16Array(b[5] || BUF, b[0], nb * 3), ib = new Uint16Array(b[5] || BUF, b[0] + nb * 6, fb * 3);
    for (var i = 0; i < nb; i++) {
      var x = vb[i * 3] * sb, y = vb[i * 3 + 1] * sb, z = vb[i * 3 + 2] * sb;
      for (var k = 0; k < 3; k++) {
        var c = g[k] + g[3 + k * 3] * x + g[4 + k * 3] * y + g[5 + k * 3] * z;
        v[(na + i) * 3 + k] = Math.max(-32768, Math.min(32767, Math.round(c / sc)));
      }
    }
    for (var j = 0; j < fb * 3; j++) f[fa * 3 + j] = ib[j] + na;
    INDEX[key] = [0, na + nb, fa + fb, sc, "a", buf];
    if (KINDS[model]) KINDS[key] = KINDS[model];
    return key;
  }
  // something to draw from above (a fence panel or a sign is all walls)
  function hasTop(model) { return has(model) && geometry(model).faces.length > 0; }

  // vertices in metres, faces sorted low to high, and the model's extent
  function geometry(model) {
    if (GEOM[model]) return GEOM[model];
    var e = INDEX[model], off = e[0], nv = e[1], nf = e[2], sc = e[3];
    var vi = new Int16Array(e[5] || BUF, off, nv * 3);
    var fi = new Uint16Array(e[5] || BUF, off + nv * 6, nf * 3);
    var v = new Float32Array(nv * 3);
    var minx = 1e9, miny = 1e9, minz = 1e9, maxx = -1e9, maxy = -1e9, maxz = -1e9;
    for (var i = 0; i < nv; i++) {
      var x = vi[i * 3] * sc, y = vi[i * 3 + 1] * sc, z = vi[i * 3 + 2] * sc;
      v[i * 3] = x; v[i * 3 + 1] = y; v[i * 3 + 2] = z;
      if (x < minx) minx = x; if (x > maxx) maxx = x;
      if (y < miny) miny = y; if (y > maxy) maxy = y;
      if (z < minz) minz = z; if (z > maxz) maxz = z;
    }
    var faces = [];
    for (var f = 0; f < nf; f++) {
      var a = fi[f * 3], b = fi[f * 3 + 1], c = fi[f * 3 + 2];
      var ax = v[a * 3], ay = v[a * 3 + 1], az = v[a * 3 + 2];
      var ux = v[b * 3] - ax, uy = v[b * 3 + 1] - ay, uz = v[b * 3 + 2] - az;
      var wx = v[c * 3] - ax, wy = v[c * 3 + 1] - ay, wz = v[c * 3 + 2] - az;
      var nx = uy * wz - uz * wy, ny = uz * wx - ux * wz, nz = ux * wy - uy * wx;
      var ln = Math.sqrt(nx * nx + ny * ny + nz * nz) || 1;
      if (nz < 0) { nx = -nx; ny = -ny; nz = -nz; }
      if (nz / ln < 0.05) continue;          // edge-on from above
      var top = Math.max(az, v[b * 3 + 2], v[c * 3 + 2]);
      faces.push({ a: a, b: b, c: c, nx: nx / ln, ny: ny / ln, nz: nz / ln,
                   z: (az + v[b * 3 + 2] + v[c * 3 + 2]) / 3, top: top });
    }
    // painter's order: what is lower is drawn first and covered by what is above
    faces.sort(function (p, q) { return p.top - q.top || p.z - q.z; });
    GEOM[model] = { v: v, faces: faces, minx: minx, maxx: maxx, miny: miny, maxy: maxy, minz: minz, maxz: maxz };
    return GEOM[model];
  }

  // The model's upright faces, as segments on the plan with the height they
  // cover: where a camera, a sign or a light can actually hang. The top-down
  // geometry above throws these away (they are edge-on from above), and a
  // bounding box is no use on anything that overhangs - a radar dome's base
  // wall is metres inside the dome above it.
  var SURF = {};
  function walls(model) {
    if (SURF[model]) return SURF[model];
    if (!has(model)) return null;
    var e = INDEX[model], off = e[0], nv = e[1], nf = e[2], sc = e[3];
    var vi = new Int16Array(e[5] || BUF, off, nv * 3), fi = new Uint16Array(e[5] || BUF, off + nv * 6, nf * 3);
    var out = [];
    for (var f = 0; f < nf; f++) {
      var a = fi[f * 3], b = fi[f * 3 + 1], c = fi[f * 3 + 2];
      var ax = vi[a * 3] * sc, ay = vi[a * 3 + 1] * sc, az = vi[a * 3 + 2] * sc;
      var bx = vi[b * 3] * sc, by = vi[b * 3 + 1] * sc, bz = vi[b * 3 + 2] * sc;
      var cx = vi[c * 3] * sc, cy = vi[c * 3 + 1] * sc, cz = vi[c * 3 + 2] * sc;
      var ux = bx - ax, uy = by - ay, uz = bz - az, wx = cx - ax, wy = cy - ay, wz = cz - az;
      var nx = uy * wz - uz * wy, ny = uz * wx - ux * wz, nz = ux * wy - uy * wx;
      var ln = Math.sqrt(nx * nx + ny * ny + nz * nz);
      if (!ln || Math.abs(nz) / ln > 0.35) continue;         // a roof or a slope, not a wall
      var z0 = Math.min(az, bz, cz), z1 = Math.max(az, bz, cz);
      if (z1 - z0 < 1) continue;                             // too short to hang anything on
      // seen from above a wall face is a line: take its two farthest corners
      var pts = [[ax, ay], [bx, by], [cx, cy]], best = 0, p0 = pts[0], p1 = pts[1];
      for (var i = 0; i < 3; i++) {
        for (var j = i + 1; j < 3; j++) {
          var d = (pts[i][0] - pts[j][0]) * (pts[i][0] - pts[j][0]) + (pts[i][1] - pts[j][1]) * (pts[i][1] - pts[j][1]);
          if (d > best) { best = d; p0 = pts[i]; p1 = pts[j]; }
        }
      }
      if (best < 0.35 * 0.35) continue;
      var h = Math.sqrt(nx * nx + ny * ny) || 1;
      out.push({ x1: p0[0], y1: p0[1], x2: p1[0], y2: p1[1], z0: z0, z1: z1, nx: nx / h, ny: ny / h });
    }
    SURF[model] = out;
    return out;
  }

  function bounds(model) {
    if (!has(model)) return null;
    var g = geometry(model);
    return { minx: g.minx, maxx: g.maxx, miny: g.miny, maxy: g.maxy, minz: g.minz, maxz: g.maxz };
  }

  // light from the north-west, well above the horizon
  var LX = -0.42, LY = 0.5, LZ = 0.76;

  function render(model, ppm, pal) {
    var g = geometry(model);
    var wm = Math.max(0.2, g.maxx - g.minx), hm = Math.max(0.2, g.maxy - g.miny);
    ppm = Math.min(ppm, MAX_PX / Math.max(wm, hm));
    var pad = 2, W = Math.ceil(wm * ppm) + pad * 2, H = Math.ceil(hm * ppm) + pad * 2;
    var cv = document.createElement("canvas"); cv.width = W; cv.height = H;
    var hc = document.createElement("canvas"); hc.width = W; hc.height = H;
    var cx = cv.getContext("2d"), hx = hc.getContext("2d");
    var span = Math.max(0.5, g.maxz - g.minz), v = g.v;
    function X(i) { return (v[i * 3] - g.minx) * ppm + pad; }
    function Y(i) { return (g.maxy - v[i * 3 + 1]) * ppm + pad; }
    cx.lineJoin = "round"; hx.lineJoin = "round";
    cx.lineWidth = 0.6; hx.lineWidth = 0.6;
    for (var k = 0; k < g.faces.length; k++) {
      var f = g.faces[k];
      var lam = Math.max(0, f.nx * LX + f.ny * LY + f.nz * LZ);
      var t = (f.z - g.minz) / span;
      var i = Math.min(1, (0.28 + 0.62 * lam) * (0.72 + 0.4 * t));
      var r = pal.lo[0] + (pal.hi[0] - pal.lo[0]) * i | 0,
          gg = pal.lo[1] + (pal.hi[1] - pal.lo[1]) * i | 0,
          b = pal.lo[2] + (pal.hi[2] - pal.lo[2]) * i | 0;
      var col = "rgb(" + r + "," + gg + "," + b + ")";
      var hv = Math.round(t * 255), hcol = "rgb(" + hv + "," + hv + "," + hv + ")";
      var x0 = X(f.a), y0 = Y(f.a), x1 = X(f.b), y1 = Y(f.b), x2 = X(f.c), y2 = Y(f.c);
      cx.beginPath(); cx.moveTo(x0, y0); cx.lineTo(x1, y1); cx.lineTo(x2, y2); cx.closePath();
      cx.fillStyle = col; cx.strokeStyle = col; cx.fill(); cx.stroke();
      hx.beginPath(); hx.moveTo(x0, y0); hx.lineTo(x1, y1); hx.lineTo(x2, y2); hx.closePath();
      hx.fillStyle = hcol; hx.strokeStyle = hcol; hx.fill(); hx.stroke();
    }
    // trace edges where the height jumps by more than ~40 cm, and the silhouette
    var img = cx.getImageData(0, 0, W, H), hd = hx.getImageData(0, 0, W, H).data, d = img.data;
    var jump = Math.max(2, Math.round(0.4 / span * 255)), E = pal.edge;
    var out = new Uint8ClampedArray(d);
    for (var y = 1; y < H - 1; y++) {
      for (var x = 1; x < W - 1; x++) {
        var p = (y * W + x) * 4;
        var a0 = d[p + 3];
        var aN = d[p - W * 4 + 3], aS = d[p + W * 4 + 3], aW = d[p - 1], aE = d[p + 7];
        var edge = 0;
        if (a0 > 40 && (aN < 40 || aS < 40 || aW < 40 || aE < 40)) edge = 0.85;
        else if (a0 > 40) {
          var h0 = hd[p];
          var dz = Math.max(Math.abs(h0 - hd[p - W * 4]), Math.abs(h0 - hd[p + W * 4]),
                            Math.abs(h0 - hd[p - 4]), Math.abs(h0 - hd[p + 4]));
          if (dz > jump && h0 >= Math.max(hd[p - W * 4], hd[p + W * 4], hd[p - 4], hd[p + 4]) - jump) edge = 0.7;
        }
        if (edge) {
          out[p] = d[p] + (E[0] - d[p]) * edge;
          out[p + 1] = d[p + 1] + (E[1] - d[p + 1]) * edge;
          out[p + 2] = d[p + 2] + (E[2] - d[p + 2]) * edge;
          out[p + 3] = Math.max(a0, 230);
        }
      }
    }
    img.data.set(out);
    cx.putImageData(img, 0, 0);
    return { img: cv, x0: g.minx - pad / ppm, y1: g.maxy + pad / ppm, w: W / ppm, h: H / ppm, ppm: ppm };
  }

  // one render per model, palette and zoom bucket (powers of two, pixels per metre)
  function bucket(ppm) {
    var b = 2;
    while (b < ppm && b < 48) b *= 2;
    return b;
  }
  function sprite(model, ppm, palette) {
    if (!has(model)) return null;
    var pal = PALETTES[palette] ? palette : "green", bk = bucket(ppm);
    var key = model + "|" + pal + "|" + bk;
    if (!CACHE[key]) CACHE[key] = render(model, bk, PALETTES[pal]);
    return CACHE[key];
  }
  function clear() { CACHE = {}; }

  /* ---------------- 3D preview ---------------- */
  // every face with its true normal, and the edges worth tracing: the outline
  // and the creases (faces meeting at more than ~35 degrees)
  var GEOM3 = {};
  function geometry3(model) {
    if (GEOM3[model]) return GEOM3[model];
    var g = geometry(model), e = INDEX[model], off = e[0], nv = e[1], nf = e[2];
    var fi = new Uint16Array(e[5] || BUF, off + nv * 6, nf * 3), v = g.v, faces = [], edges = {};
    for (var f = 0; f < nf; f++) {
      var a = fi[f * 3], b = fi[f * 3 + 1], c = fi[f * 3 + 2];
      var ux = v[b * 3] - v[a * 3], uy = v[b * 3 + 1] - v[a * 3 + 1], uz = v[b * 3 + 2] - v[a * 3 + 2];
      var wx = v[c * 3] - v[a * 3], wy = v[c * 3 + 1] - v[a * 3 + 1], wz = v[c * 3 + 2] - v[a * 3 + 2];
      var nx = uy * wz - uz * wy, ny = uz * wx - ux * wz, nz = ux * wy - uy * wx;
      var ln = Math.sqrt(nx * nx + ny * ny + nz * nz) || 1;
      var face = { a: a, b: b, c: c, nx: nx / ln, ny: ny / ln, nz: nz / ln, lines: [], d: 0 };
      faces.push(face);
      var pairs = [[a, b], [b, c], [c, a]];
      for (var p = 0; p < 3; p++) {
        var i0 = pairs[p][0], i1 = pairs[p][1];
        var k = i0 < i1 ? i0 * 65536 + i1 : i1 * 65536 + i0;
        (edges[k] = edges[k] || []).push(face);
      }
    }
    Object.keys(edges).forEach(function (k) {
      var fs = edges[k], crease = fs.length === 1;
      if (!crease) {
        var d = Math.abs(fs[0].nx * fs[1].nx + fs[0].ny * fs[1].ny + fs[0].nz * fs[1].nz);
        crease = d < 0.82;
      }
      if (!crease) return;
      var kk = +k, lo = Math.floor(kk / 65536), hi = kk % 65536;
      for (var j = 0; j < fs.length; j++) fs[j].lines.push(lo, hi);
    });
    GEOM3[model] = { g: g, faces: faces };
    return GEOM3[model];
  }

  function renderView(cv, model, yaw, pitch, zoom, pal) {
    var G = geometry3(model), g = G.g, v = g.v, c2 = cv.getContext("2d");
    var W = cv.width, H = cv.height;
    c2.setTransform(1, 0, 0, 1, 0, 0);
    c2.clearRect(0, 0, W, H);
    var cx = (g.minx + g.maxx) / 2, cy = (g.miny + g.maxy) / 2, cz = (g.minz + g.maxz) / 2;
    var R = Math.max(0.5, Math.hypot(g.maxx - g.minx, g.maxy - g.miny, g.maxz - g.minz) / 2);
    var cyw = Math.cos(yaw), syw = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch);
    var F = R * 3.4, scale = Math.min(W, H) / (R * 2.25) * zoom;
    var tmp = [0, 0, 0];
    function proj(x, y, z) {
      var x1 = x * cyw - y * syw, y1 = x * syw + y * cyw;
      var depth = y1 * cp - z * sp, up = y1 * sp + z * cp, k = F / (F + depth);
      tmp[0] = W / 2 + x1 * scale * k; tmp[1] = H / 2 - up * scale * k; tmp[2] = depth;
      return tmp;
    }
    var n = v.length / 3, X = new Float32Array(n), Y = new Float32Array(n), Dp = new Float32Array(n);
    for (var i = 0; i < n; i++) {
      proj(v[i * 3] - cx, v[i * 3 + 1] - cy, v[i * 3 + 2] - cz);
      X[i] = tmp[0]; Y[i] = tmp[1]; Dp[i] = tmp[2];
    }
    // the ground it stands on: a faint grid, and north
    var gz = g.minz - cz, half = R * 1.15;
    var step = Math.pow(2, Math.round(Math.log(Math.max(0.5, R / 4)) / Math.LN2));
    c2.lineWidth = 1;
    c2.strokeStyle = "rgba(90,210,110,.16)";
    c2.beginPath();
    for (var t = -Math.floor(half / step) * step; t <= half + 1e-6; t += step) {
      proj(t, -half, gz); c2.moveTo(tmp[0], tmp[1]); proj(t, half, gz); c2.lineTo(tmp[0], tmp[1]);
      proj(-half, t, gz); c2.moveTo(tmp[0], tmp[1]); proj(half, t, gz); c2.lineTo(tmp[0], tmp[1]);
    }
    c2.stroke();
    proj(0, half * 1.08, gz);
    c2.fillStyle = "rgba(140,230,150,.6)";
    c2.font = "600 " + Math.round(10 * (W / 240 > 1 ? W / 240 : 1)) + "px 'IBM Plex Mono', monospace";
    c2.textAlign = "center";
    c2.fillText("N", tmp[0], tmp[1]);
    var faces = G.faces;
    for (var q = 0; q < faces.length; q++) {
      var fq = faces[q];
      fq.d = (Dp[fq.a] + Dp[fq.b] + Dp[fq.c]) / 3;
    }
    var order = faces.slice().sort(function (a, b) { return b.d - a.d; });
    var E = pal.edge, lw = Math.max(0.6, W / 400);
    c2.lineJoin = "round";
    for (q = 0; q < order.length; q++) {
      var f = order[q];
      var lam = Math.abs(f.nx * LX + f.ny * LY + f.nz * LZ);
      var fog = 1 - 0.3 * Math.min(1, Math.max(0, (f.d + R) / (2 * R)));
      var I = Math.min(1, (0.22 + 0.72 * lam) * fog);
      var col = "rgb(" + (pal.lo[0] + (pal.hi[0] - pal.lo[0]) * I | 0) + "," +
                (pal.lo[1] + (pal.hi[1] - pal.lo[1]) * I | 0) + "," + (pal.lo[2] + (pal.hi[2] - pal.lo[2]) * I | 0) + ")";
      c2.beginPath();
      c2.moveTo(X[f.a], Y[f.a]); c2.lineTo(X[f.b], Y[f.b]); c2.lineTo(X[f.c], Y[f.c]); c2.closePath();
      c2.fillStyle = col; c2.strokeStyle = col; c2.lineWidth = lw;
      c2.fill(); c2.stroke();
      if (f.lines.length) {
        c2.strokeStyle = "rgba(" + E[0] + "," + E[1] + "," + E[2] + "," + (0.3 + 0.4 * fog).toFixed(2) + ")";
        c2.lineWidth = lw * 1.4;
        c2.beginPath();
        for (var L = 0; L < f.lines.length; L += 2) {
          var e0 = f.lines[L], e1 = f.lines[L + 1];
          c2.moveTo(X[e0], Y[e0]); c2.lineTo(X[e1], Y[e1]);
        }
        c2.stroke();
      }
    }
  }

  function viewer() {
    var cv = document.createElement("canvas");
    cv.className = "pv-canvas";
    cv.setAttribute("role", "img");
    cv.title = "Drag to turn, wheel to zoom, double-click to spin again";
    var st = { model: null, pal: "green", yaw: -0.75, pitch: 0.5, zoom: 1, spin: true, raf: 0, drag: null, last: 0 };
    function fit() {
      var dpr = Math.min(global.devicePixelRatio || 1, 2), r = cv.getBoundingClientRect();
      var w = Math.max(1, Math.round(r.width * dpr)), h = Math.max(1, Math.round(r.height * dpr));
      if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }
    }
    function paint() {
      if (!st.model || !has(st.model) || !cv.isConnected) return;
      fit();
      renderView(cv, st.model, st.yaw, st.pitch, st.zoom, PALETTES[st.pal] || PALETTES.green);
    }
    function tick(now) {
      st.raf = 0;
      if (!cv.isConnected || !st.model) return;
      if (st.spin && !document.hidden && now - st.last > 33) { st.yaw += 0.012; st.last = now; paint(); }
      st.raf = requestAnimationFrame(tick);
    }
    function run() { if (!st.raf) st.raf = requestAnimationFrame(tick); }
    cv.addEventListener("pointerdown", function (e) {
      st.drag = { x: e.clientX, y: e.clientY, yaw: st.yaw, pitch: st.pitch };
      st.spin = false;
      try { cv.setPointerCapture(e.pointerId); } catch (err) {}
    });
    cv.addEventListener("pointermove", function (e) {
      if (!st.drag) return;
      st.yaw = st.drag.yaw + (e.clientX - st.drag.x) * 0.01;
      st.pitch = Math.max(-0.15, Math.min(1.5, st.drag.pitch + (e.clientY - st.drag.y) * 0.01));
      paint();
    });
    cv.addEventListener("pointerup", function () { st.drag = null; });
    cv.addEventListener("wheel", function (e) {
      e.preventDefault();
      st.zoom = Math.max(0.5, Math.min(4, st.zoom * (e.deltaY < 0 ? 1.12 : 1 / 1.12)));
      paint();
    }, { passive: false });
    cv.addEventListener("dblclick", function () { st.spin = true; st.zoom = 1; st.pitch = 0.5; run(); });
    return {
      el: cv,
      set: function (model, pal) {
        if (model !== st.model) { st.model = model; st.zoom = 1; }
        st.pal = pal || "green";
        paint(); run();
      },
      redraw: paint,
      turn: function (yaw, pitch) { st.yaw = yaw; if (pitch != null) st.pitch = pitch; st.spin = false; paint(); },
      view: function () { return { yaw: st.yaw, pitch: st.pitch, zoom: st.zoom, spin: st.spin }; },
      stop: function () { st.model = null; }
    };
  }

  global.MeshSprites = {
    load: load, has: has, hasTop: hasTop, sprite: sprite, bounds: bounds, clear: clear, viewer: viewer,
    walls: walls,
    // the faces seen from above, for rasterising a model's top heights
    top: function (model) { if (!has(model)) return null; var g = geometry(model); return { v: g.v, faces: g.faces }; },
    ready: function () { return !!INDEX; }, PALETTES: PALETTES,
    // the model the world shows for a pickup id (WEAPON_ID_AK47 -> 100_01_1)
    pickupModel: function (id) { return (id && PICKUPS[id]) || null; },
    kind: function (model) { return KINDS[model] || null; },
    // raw geometry for the 3D close-up: positions (metres) and triangles
    raw: function (model) {
      if (!has(model)) return null;
      var e = INDEX[model], off = e[0], nv = e[1], nf = e[2], sc = e[3];
      var vi = new Int16Array(e[5] || BUF, off, nv * 3), pos = new Float32Array(nv * 3);
      for (var i = 0; i < nv * 3; i++) pos[i] = vi[i] * sc;
      return { pos: pos, idx: new Uint16Array(e[5] || BUF, off + nv * 6, nf * 3).slice(0) };
    },
    // where a character holds its weapon: [x, y, z, rotation row by row], or null
    grip: function (model) { return GRIPS[model] || null; },
    armed: armed, composite: composite
  };
})(window);
