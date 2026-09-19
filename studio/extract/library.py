# The built-in missions as the game presents them: cover picture, name,
# description, and what kind of map each one is.
#
#   python studio/extract/library.py [--game <game>]
#       -> editor/data/covers/mission1.png ... mission14.png
#       -> editor/data/builtins.json
#
# Covers come from menusystem/missionsprites.res: one 168x124 LOOP texture per
# mission, ARGB1555, pixels from offset 84. Names and descriptions come from
# language/USA/missions.res (NAME "LOCAL:USA/Mission N Name" + CSTR pairs).
import json, pathlib, re, struct, sys, zlib

from studio.build import models as MI
from studio import paths

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = paths.data()

# What each map looks like - read off the covers and the level scripts (RainEffect,
# FlatSky, GlobalLight). "group" is how the empty-map picker sorts them; an
# underground level has no open map to start from.
ENVIRONMENT = {
    1: ("Dry hills", "evening", "hills"),
    2: ("Green hills", "overcast", "hills"),
    3: ("Airfield", "night, rain", "night"),
    4: ("Dry hills", "dusk", "hills"),
    5: ("Green mountains", "clear sky", "mountains"),
    6: ("Green hills", "overcast", "hills"),
    7: ("Snowy forest", "night", "snow"),
    8: ("Snowfield", "day", "snow"),
    9: ("Green valley", "overcast", "hills"),
    10: ("Rocky mountains", "overcast", "mountains"),
    11: ("Snowy mountains", "night", "snow"),
    12: ("Snowy mountains", "dusk", "snow"),
    13: ("Industrial plain", "red sunset", "sunset"),
    14: ("Underground complex", "indoors", "indoors"),
}
GROUPS = [("hills", "Hills and grassland"), ("mountains", "Mountains"), ("snow", "Snow"),
          ("night", "Night"), ("sunset", "Sunset"), ("indoors", "Indoors")]


def png(path, w, h, rgb):
    rows = b"".join(b"\x00" + rgb[y * w * 3:(y + 1) * w * 3] for y in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    pathlib.Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                                   + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


def loop_texture_rgb(body):
    """A 16-bit LOOP texture (the mission sprites) as (w, h, RGB bytes)."""
    b = body[16:]                                  # past the BODY chunk header
    if b[:4] != b"LOOP":
        raise ValueError("not a LOOP texture")
    w, h, bpp = struct.unpack_from("<III", b, 40)
    if bpp != 2:
        raise ValueError("unexpected %d bytes per pixel" % bpp)
    px = b[84:84 + w * h * 2]
    out = bytearray(w * h * 3)
    for i in range(w * h):
        v = px[2 * i] | px[2 * i + 1] << 8
        out[3 * i] = ((v >> 10) & 31) * 255 // 31
        out[3 * i + 1] = ((v >> 5) & 31) * 255 // 31
        out[3 * i + 2] = (v & 31) * 255 // 31
    return w, h, bytes(out)


def mission_texts(path):
    """{mission number: (name, description)} from the language pack."""
    raw = open(path, "rb").read()
    out, key, off = {}, None, 20
    while off + 16 <= len(raw):
        tag = raw[off:off + 4]
        ln, al, _ = struct.unpack_from("<III", raw, off + 4)
        if al == 0:
            break
        val = raw[off + 16:off + 16 + ln].split(b"\0")[0].decode("latin1")
        if tag == b"NAME":
            key = val
        elif tag == b"CSTR" and key:
            m = re.search(r"Mission (\d+) (Name|Desc)$", key)
            if m:
                rec = out.setdefault(int(m.group(1)), ["", ""])
                rec[0 if m.group(2) == "Name" else 1] = val
            key = None
        off += 16 + ((ln + al - 1) // al) * al
    return out


def main(argv):
    game = pathlib.Path(argv[argv.index("--game") + 1] if "--game" in argv else str(paths.require_game()))
    covers = DATA / "covers"
    covers.mkdir(parents=True, exist_ok=True)
    _, sprites = MI.res_entries(game / "menusystem" / "missionsprites.res")
    have_cover = set()
    for name, _, body in sprites:
        m = re.fullmatch(r"mission(\d+)", name)
        if not m:
            continue
        w, h, rgb = loop_texture_rgb(body)
        png(covers / (name + ".png"), w, h, rgb)
        have_cover.add(int(m.group(1)))
    texts = mission_texts(game / "language" / "USA" / "missions.res")
    index = {}
    ip = DATA / "index.json"
    if ip.exists():
        index = {r["level"]: r for r in json.load(ip.open()).get("levels", [])}
    out = []
    for n in range(1, 15):
        label, when, group = ENVIRONMENT[n]
        name, desc = texts.get(n, ("Mission %d" % n, ""))
        out.append({"level": n, "name": name, "description": desc,
                    "environment": {"label": label, "when": when, "group": group},
                    "cover": ("covers/mission%d.png" % n) if n in have_cover else None,
                    "emptyMap": group != "indoors",
                    "objects": (index.get(n) or {}).get("objects"),
                    "graphs": len((index.get(n) or {}).get("graphs") or [])})
    json.dump({"missions": out, "groups": [{"id": g, "label": l} for g, l in GROUPS]},
              (DATA / "builtins.json").open("w"), indent=1)
    print("wrote %d covers and builtins.json" % len(have_cover))
    for r in out:
        print("  %2d  %-22s %-34s %s, %s" % (r["level"], r["name"], r["description"][:34],
                                            r["environment"]["label"], r["environment"]["when"]))


if __name__ == "__main__":
    main(sys.argv[1:])
