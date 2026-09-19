/* The map computer's zoom transition: a quick "CONNECTING" bar and thin
 * horizontal static that flickers across the picture and fades, with the image
 * tearing sideways for a frame or two.
 *
 *   MapFX.init(stageElement, mapCanvas)
 *   MapFX.glitch(strength)     strength 0..1 (a wheel notch is ~0.6, a jump is 1)
 *
 * Nothing runs when the viewer asks for reduced motion.
 */
(function (global) {
  "use strict";

  var host = null, target = null, layer = null, bar = null, fill = null, cv = null, g = null;
  var until = 0, started = 0, raf = 0, power = 0, DUR = 520, offT = 0, seq = 0;
  var reduced = global.matchMedia && global.matchMedia("(prefers-reduced-motion: reduce)");

  function init(stage, mapCanvas) {
    host = stage; target = mapCanvas;
    layer = document.createElement("div");
    layer.className = "fx";
    layer.setAttribute("aria-hidden", "true");
    layer.innerHTML = '<canvas></canvas><div class="fx-bar"><span>CONNECTING</span><div><i></i></div></div>';
    host.appendChild(layer);
    cv = layer.querySelector("canvas");
    g = cv.getContext("2d");
    bar = layer.querySelector(".fx-bar");
    fill = layer.querySelector(".fx-bar i");
  }

  function glitch(strength) {
    if (!layer || (reduced && reduced.matches)) return;
    var now = performance.now();
    power = Math.max(now < until ? power : 0, strength == null ? 1 : strength);
    if (now >= until) started = now;
    until = now + DUR;
    layer.classList.add("on");
    if (!raf) raf = requestAnimationFrame(frame);
    // frames can stall (a hidden tab, a busy page): the last call's timer ends
    // it whatever the frames did
    var mine = ++seq;
    clearTimeout(offT);
    offT = setTimeout(function () { if (mine === seq) finish(); }, DUR + 150);
  }

  function finish() {
    until = 0;
    if (raf) { cancelAnimationFrame(raf); raf = 0; }
    g.clearRect(0, 0, cv.width, cv.height);
    layer.classList.remove("on");
    target.style.transform = "";
  }

  function frame(now) {
    raf = 0;
    var W = host.clientWidth, H = host.clientHeight;
    if (cv.width !== W || cv.height !== H) { cv.width = W; cv.height = H; }
    var left = until - now, t = Math.min(1, (now - started) / DUR);
    g.clearRect(0, 0, W, H);
    if (left <= 0) { finish(); return; }
    var fade = Math.min(1, left / (DUR * 0.55)) * power;
    // static: short bright dashes, denser at the start
    var n = Math.round((W * H / 5200) * fade);
    for (var i = 0; i < n; i++) {
      var y = Math.random() * H | 0, x = Math.random() * W | 0, len = 6 + Math.random() * Math.random() * 90;
      var a = (0.25 + Math.random() * 0.6) * fade;
      g.fillStyle = Math.random() < 0.35 ? "rgba(235,255,235," + a + ")" : "rgba(120,255,140," + a + ")";
      g.fillRect(x, y, len, 1);
    }
    // a few full-width scan bands rolling down
    for (var k = 0; k < 3; k++) {
      var by = ((now / 3 + k * H / 3) % H) | 0;
      g.fillStyle = "rgba(90,255,120," + (0.05 * fade) + ")";
      g.fillRect(0, by, W, 2 + k);
    }
    // the picture tears sideways for the first few frames
    target.style.transform = t < 0.35 && Math.random() < 0.6 ? "translateX(" + ((Math.random() - 0.5) * 6 * power).toFixed(1) + "px)" : "";
    fill.style.width = Math.min(100, t * 135).toFixed(1) + "%";
    bar.style.opacity = String(Math.min(1, left / 160));
    raf = requestAnimationFrame(frame);
  }

  global.MapFX = { init: init, glitch: glitch };
})(window);
