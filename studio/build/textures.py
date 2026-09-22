# A mission's own textures: the game's pictures read and written, and a PNG
# put in the place of one in a slot.
#
#   python -m studio.build.textures to-png <file.tex> <out.png>
#   python -m studio.build.textures from-png <in.png> <out.tex> [--format 1555|bgra]
#   python -m studio.build.textures replace --slot 15 --name 207_01_1 --png new.png
#   python -m studio.build.textures check [--game <game>]
#
# What the game's files say (levels 1 to 14, every texture checked by "check"):
# a texture is ILFF "LOOP" version 11, a 32-byte header of 16-bit fields:
#
#   +0  "LOOP"            +4  version, 11
#   +8  format: 2 is ARGB1555, 67 is B,G,R,A     +20 5 (every one of them)
#   +22 width   +24 height   +26 width again   +28 height again
#   +30 bytes a pixel: 2 or 4
#
# Then the pixels, row 0 first. The 16-bit ones stop there; the 32-bit ones
# ("<name>_argb8888.tex") carry a full mipmap chain after them, each level half
# the one before, down to 1 x 1. In ARGB1555 the top bit is the only alpha there
# is: a texture with none of them set is drawn opaque, so a picture with no
# transparency is written with every bit set.
#
# Where they live: <level>/textures/<level>.res, an ILFF archive of NAME and
# BODY chunk pairs in the palette's order (studio/build/models.py, which also
# knows the .dat and .mtp that name them). Replacing one keeps its name and its
# place, so the palette, the .dat and the .mtp stay as they are; only the
# picture changes, and it may be any size.
import json, pathlib, re, struct, sys, zlib

from studio.build import models as MODELS
from studio import paths, protect

HDR = 32
FMT = {2: 2, 4: 67}           # bytes a pixel -> the format field


# ------------------------------------------------------------------ PNG
def read_png(data):
    """(w, h, rgba bytearray) of a PNG: 8 bits a channel, grey, palette, RGB or
    RGBA, not interlaced (what every picture tool writes)."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    off, idat, pal, trns, w = 8, bytearray(), None, None, None
    while off + 8 <= len(data):
        ln, tag = struct.unpack_from(">I4s", data, off)
        body = data[off + 8:off + 8 + ln]
        if tag == b"IHDR":
            w, h, depth, colour, comp, filt, inter = struct.unpack(">IIBBBBB", body)
            if depth != 8:
                raise ValueError("the PNG is %d bits a channel; save it as 8" % depth)
            if inter:
                raise ValueError("the PNG is interlaced; save it without interlacing")
            if colour not in (0, 2, 3, 6):
                raise ValueError("PNG colour type %d is not one we read" % colour)
        elif tag == b"PLTE":
            pal = body
        elif tag == b"tRNS":
            trns = body
        elif tag == b"IDAT":
            idat += body
        elif tag == b"IEND":
            break
        off += 12 + ln
    if w is None:
        raise ValueError("the PNG has no header")
    chans = {0: 1, 2: 3, 3: 1, 6: 4}[colour]
    raw, stride = zlib.decompress(bytes(idat)), w * chans
    if len(raw) < (stride + 1) * h:
        raise ValueError("the PNG is short: %d bytes for %d x %d" % (len(raw), w, h))
    # undo the per-row filters
    out, prev = bytearray(stride * h), bytearray(stride)
    for y in range(h):
        f = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - chans] if i >= chans else 0
            b = prev[i]
            c = prev[i - chans] if i >= chans else 0
            if f == 1:
                line[i] = (line[i] + a) & 255
            elif f == 2:
                line[i] = (line[i] + b) & 255
            elif f == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        out[y * stride:(y + 1) * stride] = line
        prev = line
    rgba = bytearray(w * h * 4)
    for i in range(w * h):
        if colour == 6:
            rgba[i * 4:i * 4 + 4] = out[i * 4:i * 4 + 4]
        elif colour == 2:
            rgba[i * 4:i * 4 + 3] = out[i * 3:i * 3 + 3]
            rgba[i * 4 + 3] = 255
        elif colour == 0:
            g = out[i]
            rgba[i * 4:i * 4 + 4] = bytes((g, g, g, 255))
        else:
            p = out[i]
            rgba[i * 4:i * 4 + 3] = pal[p * 3:p * 3 + 3] if pal else b"\0\0\0"
            rgba[i * 4 + 3] = trns[p] if trns and p < len(trns) else 255
    return w, h, rgba


def write_png(w, h, rgba):
    raw = b"".join(b"\0" + bytes(rgba[y * w * 4:(y + 1) * w * 4]) for y in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


# ------------------------------------------------------------------ the game's LOOP
def read_loop(b):
    """{w, h, bpp, rgba, mips} of a LOOP texture; mips is what follows the
    first picture (the 32-bit ones carry their mipmap chain there)."""
    if len(b) < HDR or b[:4] != b"LOOP":
        raise ValueError("not a LOOP texture")
    ver, fmt = struct.unpack_from("<H", b, 4)[0], struct.unpack_from("<H", b, 8)[0]
    w, h, bpp = struct.unpack_from("<H", b, 22)[0], struct.unpack_from("<H", b, 24)[0], struct.unpack_from("<H", b, 30)[0]
    if ver != 11 or bpp not in (2, 4) or not w or not h:
        raise ValueError("LOOP version %d, %d bytes a pixel: not one we read" % (ver, bpp))
    if len(b) < HDR + w * h * bpp:
        raise ValueError("the texture is short: %d bytes for %d x %d" % (len(b), w, h))
    rgba = bytearray(w * h * 4)
    if bpp == 2:
        px = struct.unpack_from("<%dH" % (w * h), b, HDR)
        solid = 0
        for i, v in enumerate(px):
            rgba[i * 4] = ((v >> 10) & 31) * 255 // 31
            rgba[i * 4 + 1] = ((v >> 5) & 31) * 255 // 31
            rgba[i * 4 + 2] = (v & 31) * 255 // 31
            rgba[i * 4 + 3] = 255 if v & 0x8000 else 0
            solid += 1 if v & 0x8000 else 0
        if not solid:                       # no alpha bits at all: opaque
            for i in range(3, len(rgba), 4):
                rgba[i] = 255
    else:
        for i in range(w * h):
            q = HDR + i * 4
            rgba[i * 4], rgba[i * 4 + 1], rgba[i * 4 + 2], rgba[i * 4 + 3] = b[q + 2], b[q + 1], b[q], b[q + 3]
    return {"w": w, "h": h, "bpp": bpp, "fmt": fmt, "rgba": rgba, "mips": bytes(b[HDR + w * h * bpp:])}


def _half(w, h, rgba):
    """The next mipmap level: each pixel the average of the four above it."""
    W, H = max(1, w // 2), max(1, h // 2)
    out = bytearray(W * H * 4)
    for y in range(H):
        y0, y1 = min(h - 1, y * 2), min(h - 1, y * 2 + 1)
        for x in range(W):
            x0, x1 = min(w - 1, x * 2), min(w - 1, x * 2 + 1)
            for c in range(4):
                out[(y * W + x) * 4 + c] = (rgba[(y0 * w + x0) * 4 + c] + rgba[(y0 * w + x1) * 4 + c] +
                                            rgba[(y1 * w + x0) * 4 + c] + rgba[(y1 * w + x1) * 4 + c] + 2) // 4
    return W, H, out


def _pixels(w, h, rgba, bpp, any_alpha):
    if bpp == 4:
        out = bytearray(w * h * 4)
        for i in range(w * h):
            out[i * 4] = rgba[i * 4 + 2]
            out[i * 4 + 1] = rgba[i * 4 + 1]
            out[i * 4 + 2] = rgba[i * 4]
            out[i * 4 + 3] = rgba[i * 4 + 3]
        return bytes(out)
    vals = []
    for i in range(w * h):
        r, g, b, a = rgba[i * 4], rgba[i * 4 + 1], rgba[i * 4 + 2], rgba[i * 4 + 3]
        v = ((r * 31 + 127) // 255) << 10 | ((g * 31 + 127) // 255) << 5 | ((b * 31 + 127) // 255)
        # the top bit is the whole of the alpha: on where the picture is solid
        if a >= 128 or not any_alpha:
            v |= 0x8000
        vals.append(v)
    return struct.pack("<%dH" % len(vals), *vals)


def write_loop(w, h, rgba, bpp=2):
    """A LOOP texture of a picture: 16 bits a pixel as the game's own mostly
    are, or 32 with the mipmap chain the 32-bit ones carry."""
    if bpp not in (2, 4):
        raise ValueError("2 or 4 bytes a pixel")
    if not (0 < w <= 4096 and 0 < h <= 4096):
        raise ValueError("a texture is up to 4096 x 4096")
    any_alpha = any(rgba[i] < 255 for i in range(3, len(rgba), 4))
    head = struct.pack("<4s14H", b"LOOP", 11, 0, FMT[bpp], 0, 0, 0, 0, 0, 5, w, h, w, h, bpp)
    out = bytearray(head + _pixels(w, h, rgba, bpp, any_alpha))
    if bpp == 4:
        mw, mh, m = w, h, rgba
        while mw > 1 or mh > 1:
            mw, mh, m = _half(mw, mh, m)
            out += _pixels(mw, mh, m, bpp, any_alpha)
    return bytes(out)


# ------------------------------------------------------------------ into a slot
def replace_in_res(res, stem, body, log=print):
    """Put body in the place of the texture named stem, keeping every chunk's
    name, order and padding: the palette, the .dat and the .mtp stay as they
    are. The archive is rewritten and its chain fixed."""
    res = pathlib.Path(res)
    protect.assert_writable(res)
    raw, entries = MODELS.res_entries(res)
    hit = [e for e in entries if e[0].lower() == stem.lower()]
    if not hit:
        raise ValueError("%s has no texture %s" % (res.name, stem))
    name_chunk = hit[0][1]
    old_body = hit[0][2]
    al = struct.unpack_from("<III", old_body, 4)[1] or 4
    pad = (-len(body)) % al
    new_body = struct.pack("<4sIII", b"BODY", len(body), al, 0) + body + b"\0" * pad
    out = bytearray(raw[:20])
    for stem_i, nc, bc in entries:
        out += nc
        out += new_body if (stem_i.lower() == stem.lower()) else bc
    struct.pack_into("<I", out, 4, len(out))       # ILFF carries its own length
    res.write_bytes(bytes(out))
    MODELS.fix_chain(res)
    if not MODELS.chain_ok(res):
        raise RuntimeError("%s: chunk chain broken after the replacement" % res)
    log("%s: %s is now %d bytes (was %d)" % (res.name, stem, len(body), len(old_body) - 16))
    return len(body)


def replace(slot_dir, name, png_path, bpp=None, log=print):
    """Put a PNG in the place of a texture of a mission's slot."""
    f = MODELS.level_files(slot_dir)
    if not f:
        raise ValueError("%s is not a level folder" % slot_dir)
    stem = MODELS.res_stem(name)
    w, h, rgba = read_png(pathlib.Path(png_path).read_bytes())
    if bpp is None:                                # keep the format it has
        _, entries = MODELS.res_entries(f["textures"])
        cur = [e for e in entries if e[0].lower() == stem.lower()]
        if not cur:
            raise ValueError("the slot has no texture %s" % stem)
        bpp = read_loop(cur[0][2][16:])["bpp"]
    body = write_loop(w, h, rgba, bpp)
    log("%s: %d x %d, %d bytes a pixel" % (stem, w, h, bpp))
    return replace_in_res(f["textures"], stem, body, log=log)


# ------------------------------------------------------------------ a mission's own
# A mission may carry textures of its own: pictures put in the place of the
# level's. The plan names them (studio/build/plan.py writes each as a LOOP file
# into <stage>/textures/, with the names in textures.json); install_level lays
# them into the slot. Apply builds from the untouched base every time, so the
# slot keeps a note of what was replaced last time and those are put back from
# the base level first: a texture dropped from the plan comes back as it was.
STAGE_LIST = "textures.json"
SLOT_NOTE = "studio-textures.json"


def stage(out_dir, entries, log=print):
    """Write a plan's textures into the stage. entries: [{name, png bytes,
    bpp}]. Returns the names staged."""
    out = pathlib.Path(out_dir) / "textures"
    out.mkdir(parents=True, exist_ok=True)
    names = []
    for e in entries:
        stem = MODELS.res_stem(e["name"])
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,60}", stem):
            raise ValueError("%s is not a texture name" % e["name"])
        w, h, rgba = read_png(e["png"])
        (out / (stem + ".tex")).write_bytes(write_loop(w, h, rgba, e.get("bpp") or 2))
        names.append(stem)
        log("texture %s: %d x %d" % (stem, w, h))
    (out / STAGE_LIST).write_text(json.dumps(names), encoding="utf-8")
    return names


def install(stage_dir, dest_dir, base_dir, log=print):
    """Put the staged textures into a slot, and any the plan no longer has back
    as the base level's. Returns (replaced, restored)."""
    stage_t = pathlib.Path(stage_dir) / "textures"
    dest = pathlib.Path(dest_dir)
    f = MODELS.level_files(dest)
    if not f or not f["textures"].exists():
        return [], []
    listed = stage_t / STAGE_LIST
    want = json.loads(listed.read_text(encoding="utf-8")) if listed.exists() else []
    note = dest / "textures" / SLOT_NOTE
    had = []
    if note.exists():
        try:
            had = json.loads(note.read_text(encoding="utf-8"))
        except ValueError:
            had = []
    base = MODELS.level_files(base_dir) if base_dir else None
    restored = []
    for stem in [s for s in had if s not in want]:
        if not base or not base["textures"].exists():
            continue
        _, entries = MODELS.res_entries(base["textures"])
        hit = [e for e in entries if e[0].lower() == stem.lower()]
        if not hit:
            continue
        replace_in_res(f["textures"], stem, hit[0][2][16:], log=lambda *_: None)
        restored.append(stem)
        log("texture %s: the level's own again" % stem)
    done = []
    for stem in want:
        body = (stage_t / (stem + ".tex")).read_bytes()
        try:
            replace_in_res(f["textures"], stem, body, log=lambda *_: None)
        except ValueError as e:
            # the level has no texture of that name (a plan moved to another
            # level, say): say so and leave the rest of the build alone
            log("texture %s: not in this level, so it is left out (%s)" % (stem, e))
            continue
        done.append(stem)
        log("texture %s: the mission's own (%s bytes)" % (stem, format(len(body), ",")))
    want = done
    if want or restored:
        protect.assert_writable(note)
        if want:
            note.write_text(json.dumps(want), encoding="utf-8")
        elif note.exists():
            note.unlink()
    return want, restored


# ------------------------------------------------------------------ the check
def check(game=None, log=print):
    """Read every texture of every level and write it back: the 16-bit ones must
    come out byte for byte, the 32-bit ones pixel for pixel (their mipmaps are
    the game's own, ours are made anew)."""
    game = pathlib.Path(game or paths.game())
    loc = game / "missions" / "location0"
    bad = 0
    for lv in sorted(p for p in loc.glob("level*") if p.is_dir()):
        f = MODELS.level_files(lv)
        if not f or not f["textures"].exists():
            continue
        _, entries = MODELS.res_entries(f["textures"])
        n = same = px = 0
        for stem, _nc, bc in entries:
            body = bc[16:]
            try:
                t = read_loop(body)
            except ValueError:
                continue
            n += 1
            again = write_loop(t["w"], t["h"], t["rgba"], t["bpp"])
            if t["bpp"] == 2 and again == body[:len(again)] and len(again) == HDR + t["w"] * t["h"] * 2:
                same += 1
            elif read_loop(again)["rgba"] == t["rgba"]:
                # the same picture: a 16-bit one whose alpha bits are all clear
                # is drawn opaque, and ours says opaque the way the rest do
                px += 1
            else:
                bad += 1
                log("  %s %s: the picture changed" % (lv.name, stem))
        log("%-9s %4d textures: %d the same byte for byte, %d the same picture" % (lv.name, n, same, px))
    log("check: " + ("every texture came back" if not bad else "%d did not come back" % bad))
    # (one of the game's own, level 8's 700_12_1, has no alpha bits set at all:
    #  the same picture, written the way the other 6,900 write "opaque")
    return bad == 0


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__ or "")
        return 0
    cmd, rest = argv[0], argv[1:]

    def opt(name, dflt=None):
        return rest[rest.index(name) + 1] if name in rest else dflt
    if cmd == "to-png":
        t = read_loop(pathlib.Path(rest[0]).read_bytes())
        pathlib.Path(rest[1]).write_bytes(write_png(t["w"], t["h"], t["rgba"]))
        print("%s: %d x %d, %d bytes a pixel -> %s" % (rest[0], t["w"], t["h"], t["bpp"], rest[1]))
    elif cmd == "from-png":
        w, h, rgba = read_png(pathlib.Path(rest[0]).read_bytes())
        bpp = 4 if opt("--format", "1555") in ("bgra", "argb8888", "4") else 2
        pathlib.Path(rest[1]).write_bytes(write_loop(w, h, rgba, bpp))
        print("%s: %d x %d -> %s, %d bytes a pixel" % (rest[0], w, h, rest[1], bpp))
    elif cmd == "replace":
        slot = opt("--slot")
        game = pathlib.Path(opt("--game") or paths.game())
        d = pathlib.Path(slot) if slot and pathlib.Path(slot).is_dir() else game / "missions" / "location0" / ("level%s" % slot)
        replace(d, opt("--name"), opt("--png"), 4 if opt("--format") in ("bgra", "argb8888", "4") else (2 if opt("--format") else None))
    elif cmd == "check":
        return 0 if check(opt("--game")) else 1
    else:
        print("commands: to-png, from-png, replace, check")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
