/* Plan-view icons for the Project IGI Studio editor.
 *
 * SVG path data in a 24x24 box centred on (12,12), drawn with Path2D (which
 * takes SVG syntax directly), so they stay crisp at any zoom and can be lifted
 * straight into an <svg>. Filled with the even-odd rule, so a path can cut
 * holes (the medipack's cross, a barrel's rim).
 *
 * Buildings are not drawn from these: they use a top-down render of the model
 * itself (meshes.js). Icons are for guards, the player, pickups, and things
 * nobody walks into - vehicles, aircraft, trees, crates, lamps - which read
 * better as a symbol. Vehicle and tree icons point "forward" up (+y) and are
 * stretched to the model's real footprint by drawBox().
 */
(function (global) {
  "use strict";

  var P = {
    /* people: the map computer's contact triangles, pointing where they face */
    contact:   "M12 3.5 L19.5 20 L12 16.5 L4.5 20Z",
    // head and shoulders: a guard in a list, where a map triangle reads as nothing
    guardface: "M12 3.4a3.9 3.9 0 1 0 0 7.8 3.9 3.9 0 0 0 0-7.8z M3.8 21c0-4.2 3.6-6.9 8.2-6.9s8.2 2.7 8.2 6.9z",
    sniper:    "M12 3.5 L19.5 20 L12 16.5 L4.5 20Z M12 9.2a2.2 2.2 0 1 0 .01 0Z",
    heavy:     "M12 3.5 L19.5 20 L12 16.5 L4.5 20Z M9.2 12.6h5.6v2H9.2z",
    officer:   "M12 3.5 L19.5 20 L12 16.5 L4.5 20Z M12 8.6l1.2 2.4 2.5.3-1.9 1.7.5 2.5-2.3-1.3-2.3 1.3.5-2.5-1.9-1.7 2.5-.3z",
    civilian:  "M12 5a6.5 6.5 0 1 0 .01 0Z M12 1.5l2 3.2h-4z",
    player:    "M12 2 L20 21.5 L12 17 L4 21.5Z M12 8.5 L15.6 17.4 L12 15.4 L8.4 17.4Z",

    /* weapons and items, lying flat, muzzle to the right */
    rifle:     "M1.5 10.6h13.8l1.4-1h5.8v1.9h-4.3l-.8 1h-3.3l-1.3 3.4H10.7l.9-3.4H8.3l-1.7 2.7H3.4l1.3-2.7H1.5z",
    sniperRifle: "M1 11.1h15l1-.8h6v1.7h-5.2l-.6.8h-3.7l-1 2.9h-2l.7-2.9H7.6L5.8 15H2.9l1.3-2.2H1z M7.5 7.7h7v2.1h-7z",
    smg:       "M4.5 9.8h10.2l1-1h3.8v2h-2.2l-1 1h-2.1l-.7 5.4h-2.2l.5-5.4H9.3l-.6 2.6H6.5l.6-2.6H4.5z",
    shotgun:   "M1.5 10.4h16.4v1.2h4.6v1.3h-4.6l-.5.7H8.9l-2.4 2.8H3.3l1.9-2.8H1.5z",
    pistol:    "M4.5 7.8h13v3.2h-7.2l-1.3 6.2H5.4l1.2-6.2H4.5z",
    launcher:  "M1.5 9.8h17.2l3.8-2.3v8.8l-3.8-2.3H1.5z M8 14h2.2v3.6H8z",
    grenade:   "M12 7.2a5 5.6 0 1 0 .01 0Z M10.6 3.2h4.6v3.3h-4.6z M15.2 3.9h2.8v1.6h-2.8z",
    mine:      "M12 4.8a7.2 7.2 0 1 0 .01 0Z M12 9.6a2.4 2.4 0 1 0 .01 0Z",
    flashbang: "M8 6h8v14H8z M10 2.8h4v3.2h-4z M8 10h8v1.6H8z",
    medipack:  "M3.5 6.5h17v13h-17z M9 3.5h6v3H9z M10.5 9h3v3h3v3h-3v3h-3v-3h-3v-3h3z",
    ammo:      "M4.5 9.2 6.2 5.6 7.9 9.2V19H4.5z M10.3 9.2 12 5.6l1.7 3.6V19h-3.4z M16.1 9.2l1.7-3.6 1.7 3.6V19h-3.4z",
    binoculars:"M3.5 9h6.5v10.5H3.5z M14 9h6.5v10.5H14z M10 11h4v4h-4z M4.5 5.5h4.5V9H4.5z M15 5.5h4.5V9H15z",
    knife:     "M1.5 12.4 15.5 9.8h6.5l-2 2.8h-4.5L1.5 13.8z M15.5 9.2h1.2v4.2h-1.2z",
    pickup:    "M12 3 L21 12 L12 21 L3 12Z",

    /* vehicles, top-down, front up */
    tank:      "M5 5h14v17H5z M2.5 4h3.2v19H2.5z M18.3 4h3.2v19h-3.2z M12 9.2a4.2 4.2 0 1 0 .01 0Z M11 .5h2v8.8h-2z",
    apc:       "M5 2.5h14v19.5H5z M2.8 4.5h2.2v4H2.8z M2.8 10.8h2.2v4H2.8z M2.8 17h2.2v4H2.8z M19 4.5h2.2v4H19z M19 10.8h2.2v4H19z M19 17h2.2v4H19z M9 7h6v5H9z",
    truck:     "M6.5 1h11v6h-11z M5 8h14v15H5z M8 2.5h8v2.8H8z M7 10h10v11H7z",
    car:       "M7 1.5h10l1.2 4v14l-1.2 3H7l-1.2-3v-14z M8 6.5h8v4H8z M8.2 16h7.6v3.2H8.2z",
    helicopter:"M12 2.5a4 6.2 0 1 0 .01 0Z M11.2 14.2h1.6v8h-1.6z M8.2 21h7.6v1.6H8.2z M1 8.2h22v1.3H1z M11.35 -1h1.3v20h-1.3z",
    jet:       "M12 .5 13.8 6.5 22.5 13v2.2l-8.8-2.2-.6 6.2 3.2 2.6v1.4L12 22.3l-4.6 1v-1.4l3.2-2.6-.6-6.2-8.8 2.2V13l8.7-6.5z",
    locomotive:"M6 1h12v22H6z M8 3h8v6H8z M9 12h6v8H9z",
    wagon:     "M6 1h12v22H6z M8 3h8v18H8z M8 11.2h8v1.6H8z",
    forklift:  "M7 8h10v14H7z M8 1h1.8v7H8z M14.2 1H16v7h-1.8z M9 11h6v4H9z",
    cablecar:  "M5 6h14v12H5z M11 1h2v5h-2z M7 8h10v3H7z",
    samLauncher:"M5 4h14v18H5z M7 .8h3.2v13.4H7z M13.8 .8H17v13.4h-3.2z",
    missile:   "M12 .8l3 5.2v13.4l3 3.1H6l3-3.1V6z",

    /* nature and clutter */
    tree:      "M12 2.5c2.2 0 3.6 1.5 4 3.1 2 .3 3.6 2 3.6 4.1 0 1.3-.6 2.4-1.5 3.1.5.7.8 1.5.8 2.4 0 2.4-2 4.3-4.4 4.3-.9 0-1.8-.3-2.5-.8-.7.5-1.6.8-2.5.8-2.4 0-4.4-1.9-4.4-4.3 0-.9.3-1.7.8-2.4-.9-.7-1.5-1.8-1.5-3.1 0-2.1 1.6-3.8 3.6-4.1.4-1.6 1.8-3.1 4-3.1z M12 10.6a1.3 1.3 0 1 0 .01 0Z",
    bush:      "M8.5 6.5a3.8 3.8 0 0 1 7 0 3.8 3.8 0 0 1 2 5.5 3.8 3.8 0 0 1-2 5.5 3.8 3.8 0 0 1-7 0 3.8 3.8 0 0 1-2-5.5 3.8 3.8 0 0 1 2-5.5z",
    barrel:    "M12 3.5a8.5 8.5 0 1 0 .01 0Z M12 7.5a4.5 4.5 0 1 0 .01 0Z",
    crate:     "M3.5 3.5h17v17h-17z M6 6h12v12H6z M6 6l12 12 M18 6 6 18",
    lamp:      "M12 8.8a3.2 3.2 0 1 0 .01 0Z M12 1.5v3.5 M12 19v3.5 M1.5 12H5 M19 12h3.5 M4.6 4.6l2.4 2.4 M17 17l2.4 2.4 M19.4 4.6 17 7 M7 17l-2.4 2.4",
    pole:      "M12 9.5a2.5 2.5 0 1 0 .01 0Z M2 12h7.5 M14.5 12H22",
    computer:  "M3.5 4.5h17v11h-17z M5.8 6.8h12.4v6.4H5.8z M9 17.5h6v2.5H9z",
    camera:    "M3 8h12.5v8H3z M15.5 10l5.5-3v10l-5.5-3z",
    switch:    "M7 3.5h10v17H7z M10 6.5h4v5.5h-4z",
    alarmbtn:  "M5 4.5h14v15H5z M12 8.2a3.8 3.8 0 1 0 0 7.6 3.8 3.8 0 0 0 0-7.6z",
    siren:     "M8.5 15.5h-3v-7h3l7-4.5v16z M18 8.5a5 5 0 0 1 0 7",
    alarmlight:"M12 3.5a4.5 4.5 0 0 0-4.5 4.5v6h9V8A4.5 4.5 0 0 0 12 3.5z M5.5 17.5h13M9 20.5h6",
    alarmctl:  "M12 3.2a5.6 5.6 0 0 0-5.6 5.6c0 4.2-1.6 5.6-1.6 5.6h14.4s-1.6-1.4-1.6-5.6A5.6 5.6 0 0 0 12 3.2z M10 17.5a2 2 0 0 0 4 0",
    explosive: "M12 1.5l2.4 5.6L20 4.5l-2.4 5.6 5.4 2-5.4 1.9 2.4 5.5-5.6-2.5L12 22.5l-2.4-5.5L4 19.5l2.4-5.5-5.4-1.9 5.4-2L4 4.5l5.6 2.6z",

    /* events that are not a thing on the map: time passing, one event after another */
    clock:     "M12 2.8a9.2 9.2 0 1 0 .01 0Z M12 4.8a7.2 7.2 0 1 0 .01 0Z M11.1 6.6h1.8v5l3.4 2.1-.9 1.5-4.3-2.6z",
    after:     "M1.8 8.2h6.8v7.6H1.8z M15.4 8.2h6.8v7.6h-6.8z M9.6 11.1h2.6V9l3 3-3 3v-2.1H9.6z",
    node:      "M12 9a3 3 0 1 0 .01 0Z",
    dot:       "M12 9.5a2.5 2.5 0 1 0 .01 0Z"
  };

  var CACHE = {};
  function path(key) {
    if (!CACHE[key]) CACHE[key] = new Path2D(P[key] || P.dot);
    return CACHE[key];
  }

  /* Draw an icon centred on the current origin, sized to radius r (pixels).
     opts.fillAlpha: fill strength under the full-strength outline (default 1). */
  function draw(ctx, key, r, rot, opts) {
    var s = (r * 2) / 24, fa = opts && opts.fillAlpha != null ? opts.fillAlpha : 1;
    ctx.save();
    if (rot) ctx.rotate(-rot);
    ctx.scale(s, s);
    ctx.translate(-12, -12);
    var p = path(key);
    var a = ctx.globalAlpha;
    ctx.globalAlpha = a * fa;
    ctx.fill(p, "evenodd");
    ctx.globalAlpha = a;
    ctx.lineWidth = Math.max(0.6, ((opts && opts.line) || 1.3) / s);
    ctx.lineJoin = "round";
    ctx.stroke(p);
    ctx.restore();
  }

  /* Draw an icon stretched to w x h pixels (its 24-box maps onto that rect),
     centred on the current origin - for vehicles and trees at true size. */
  function drawBox(ctx, key, w, h, rot, opts) {
    var fa = opts && opts.fillAlpha != null ? opts.fillAlpha : 0.35;
    ctx.save();
    if (rot) ctx.rotate(-rot);
    ctx.translate(-w / 2, -h / 2);
    ctx.scale(w / 24, h / 24);
    var p = path(key);
    var a = ctx.globalAlpha;
    ctx.globalAlpha = a * fa;
    ctx.fill(p, "evenodd");
    ctx.globalAlpha = a;
    ctx.lineWidth = ((opts && opts.line) || 1.3) / Math.min(w / 24, h / 24);
    ctx.lineJoin = "round";
    ctx.stroke(p);
    ctx.restore();
  }

  /* What a model or item is, for icon choice. Returns an icon key, or null for
     "draw its real shape" (buildings, towers, walls, containers, furniture). */
  var PROP_RULES = [
    [/^T80_(TANK$|STATIONARY|DESTROYED)/, "tank"],
    [/^APC_TANK/, "apc"],
    [/^HELICOPTER(?!_PART)/, "helicopter"],
    [/^PLANE_/, "jet"],
    [/^TRAIN_ENGINE/, "locomotive"],
    [/^(TRAIN_)?WAGON|^TRAIN_CARRIAGE/, "wagon"],
    [/^FORKLIFT/, "forklift"],
    [/^CABLE_CAR/, "cablecar"],
    [/^SAM_LAUNCHER|^TERMINATOR/, "samLauncher"],
    [/^MISSILE$/, "missile"],
    [/^TRUCK/, "truck"],
    [/^JEEP|T8W|^RED_CAR|^LIMO/, "car"],
    [/^TREE/, "tree"],
    [/^BUSH/, "bush"],
    [/^BARREL|^RADIOACTIVE_WASTE/, "barrel"],
    [/CRATE|^BOX$|^METAL_BOX|^SIDE_BOX|SHELL_BOX/, "crate"],
    [/^FLOODLIGHT|^LAMP|^LIGHTS|^LARGE_LIGHTS|^STREETLAMP/, "lamp"],
    [/POLE/, "pole"],
    [/^COMPUTER|MONITOR|MAINFRAME|^RADIO$|^COMM_DEVICE/, "computer"],
    [/^CAMERA/, "camera"],
    [/SWITCH|^FUSEBOX/, "switch"]
  ];
  function propIcon(o) {
    var n = String(o.modelName || o.raw || o.model || "").toUpperCase();
    if (o.type === "camera") return "camera";
    if (o.type === "switch") return "switch";
    if (o.type === "terminal") return /SWITCH/.test(n) ? "switch" : "computer";
    for (var i = 0; i < PROP_RULES.length; i++) if (PROP_RULES[i][0].test(n)) return PROP_RULES[i][1];
    return null;
  }

  function weaponIcon(id) {
    id = String(id || "").toUpperCase();
    if (/MEDIPACK/.test(id)) return "medipack";
    if (/^AMMO_/.test(id)) return "ammo";
    if (/DRAGUNOV/.test(id)) return "sniperRifle";
    if (/AK47|M16|MINIMI/.test(id)) return "rifle";
    if (/MP5|UZI/.test(id)) return "smg";
    if (/SPAS|JACKHAMMER/.test(id)) return "shotgun";
    if (/COLT|GLOCK|DESERTEAGLE|PISTOL/.test(id)) return "pistol";
    if (/RPG|LAUNCHER|M203/.test(id)) return "launcher";
    if (/FLASHBANG/.test(id)) return "flashbang";
    if (/GRENADE/.test(id)) return "grenade";
    if (/MINE/.test(id)) return "mine";
    if (/BINOCULAR/.test(id)) return "binoculars";
    if (/KNIFE/.test(id)) return "knife";
    return "pickup";
  }

  function soldierIcon(ai) {
    ai = String(ai || "");
    if (/SNIPER/.test(ai)) return "sniper";
    if (/RPG|GUNNER|M2HB/.test(ai)) return "heavy";
    if (/CIVILIAN/.test(ai)) return "civilian";
    if (/EKK|PRIBOI|ANYA|OFFICER/.test(ai)) return "officer";
    return "contact";
  }

  function iconFor(o) {
    if (o.type === "player") return "player";
    if (o.type === "pickup") return weaponIcon(o.pickupId || o.model);
    if (o.type === "soldier") return soldierIcon(o.ai);
    if (o.type === "siren") return "siren";
    if (o.type === "alarmlight") return "alarmlight";
    if (o.type === "alarmctl") return "alarmctl";
    if (o.type === "switch" && o.own) return "alarmbtn";
    return propIcon(o) || "dot";
  }

  global.PlanIcons = {
    draw: draw, drawBox: drawBox, iconFor: iconFor, propIcon: propIcon,
    weaponIcon: weaponIcon, soldierIcon: soldierIcon, paths: P, keys: Object.keys(P)
  };
})(window);
