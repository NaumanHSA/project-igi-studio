# A mission's own picture in the game's mission list (Select Mission): the
# 168 x 124 picture beside the list.
#
# The game's are in menusystem/missionsprites.res, an ILFF "IRES" archive: for
# each mission a NAME "LOCAL:menusystem/mission<N>.spr" and a BODY, the sprite
# - an 84-byte LOOP header, 168 x 124 pixels of ARGB1555 (all opaque), and a
# 40-byte trailer - then a NAME "LOCAL:menusystem" and a PATH, every sprite's
# name joined with ";". A mission's DefineMission names its sprite
# ("mission15.spr" for slot 15), and until now nothing answered to a custom
# mission's: the list showed no picture.
#
# A mission of the studio's with a picture of its own has it added under its
# number, as the game's own are made (their header, their commonest trailer),
# and taken out again when it leaves the game or the picture is removed. No
# other entry is touched - every other one is checked to come out byte for
# byte - and the file as it was is kept in backups/menusystem/ the first time
# it is changed (protect.assert_menu_sprites).
#
#   set_cover(game, slot, png_bytes or None, log)
#   move(game, {old: new}, log)
import collections, pathlib, shutil, struct

from studio import paths, protect
from studio.build import lang
from studio.build import textures as TEX

W, H = 168, 124
REL = pathlib.Path("menusystem") / "missionsprites.res"
PIXELS = W * H * 2


def _name(n):
    return "LOCAL:menusystem/mission%d.spr" % int(n)


def _order(sprite_entry):
    """The game's own first, as they are; then the studio's by number."""
    n = _number(sprite_entry[0]) or 0
    return n if n >= protect.FIRST_CUSTOM else 0


def _number(name):
    s = name.lower()
    if s.startswith("local:menusystem/mission") and s.endswith(".spr"):
        try:
            return int(s[len("local:menusystem/mission"):-4])
        except ValueError:
            return None
    return None


def _read(b):
    """[(tag, payload)] of an archive held in memory (lang.read reads a file)."""
    if b[:4] != b"ILFF" or b[16:20] != b"IRES":
        raise ValueError("not a resource archive")
    out, off = [], 20
    while off + 16 <= len(b):
        tag = b[off:off + 4]
        ln, al, _ = struct.unpack_from("<III", b, off + 4)
        if al == 0 or off + 16 + ln > len(b):
            break
        out.append((tag, b[off + 16:off + 16 + ln]))
        off += 16 + ((ln + al - 1) // al) * al
    return out


def _split(chunks):
    """The sprites [(name, body)], and the folder's NAME chunk before the PATH."""
    out, i = [], 0
    while i + 1 < len(chunks) and chunks[i][0] == b"NAME" and chunks[i + 1][0] == b"BODY":
        out.append((chunks[i][1].split(b"\0")[0].decode("latin1"), chunks[i + 1][1]))
        i += 2
    rest = chunks[i:]
    if len(rest) != 2 or rest[0][0] != b"NAME" or rest[1][0] != b"PATH":
        raise ValueError("the mission pictures are not laid out as the game ships them")
    return out, rest[0]


def _build(sprites, folder):
    chunks = []
    for name, body in sprites:
        chunks.append((b"NAME", name.encode("latin1") + b"\0"))
        chunks.append((b"BODY", body))
    chunks.append(folder)
    chunks.append((b"PATH", ";".join(n for n, _ in sprites).encode("latin1") + b"\0"))
    return lang.build(chunks)


def _template(sprites):
    """The header and the trailer of the game's own pictures: 84 bytes before the
    pixels and 40 after (12 of the 14 share one trailer; that is the one taken)."""
    own = [b for n, b in sprites if (_number(n) or 0) < protect.FIRST_CUSTOM and len(b) == 84 + PIXELS + 40]
    if not own:
        raise ValueError("the game's own mission pictures are not there to copy")
    head = collections.Counter(b[:84] for b in own).most_common(1)[0][0]
    tail = collections.Counter(b[84 + PIXELS:] for b in own).most_common(1)[0][0]
    return head, tail


def _resize(w, h, rgba):
    """168 x 124 RGB of a picture of any size: each pixel the average of the ones it covers."""
    out = bytearray(W * H * 3)
    for ty in range(H):
        y0 = ty * h // H
        y1 = max(y0 + 1, (ty + 1) * h // H)
        for tx in range(W):
            x0 = tx * w // W
            x1 = max(x0 + 1, (tx + 1) * w // W)
            r = g = b = n = 0
            for y in range(y0, y1):
                row = y * w
                for x in range(x0, x1):
                    k = (row + x) * 4
                    r += rgba[k]
                    g += rgba[k + 1]
                    b += rgba[k + 2]
                    n += 1
            o = (ty * W + tx) * 3
            out[o], out[o + 1], out[o + 2] = r // n, g // n, b // n
    return out


def sprite(png, sprites):
    """The game's sprite of a picture (PNG bytes), made as its own are."""
    w, h, rgba = TEX.read_png(png)
    rgb = _resize(w, h, rgba)
    head, tail = _template(sprites)
    px = bytearray(PIXELS)
    for i in range(W * H):
        r, g, b = rgb[i * 3], rgb[i * 3 + 1], rgb[i * 3 + 2]
        v = 0x8000 | ((r * 31 + 127) // 255) << 10 | ((g * 31 + 127) // 255) << 5 | ((b * 31 + 127) // 255)
        struct.pack_into("<H", px, i * 2, v)
    return head + bytes(px) + tail


def _write(path, raw, sprites, folder, log):
    """Write the archive, having checked it: every picture that was not to change
    is as it was, and the PATH names them all."""
    new = _build(sprites, folder)
    if new == raw:
        return False
    before = dict(_split(_read(raw))[0])
    after, _ = _split(_read(new))
    for name, body in after:
        if (_number(name) or 0) < protect.FIRST_CUSTOM and before.get(name) != body:
            raise RuntimeError("the game's own picture %s would have changed, so nothing was written" % name)
    for name, body in before.items():
        if (_number(name) or 0) < protect.FIRST_CUSTOM and name not in dict(after):
            raise RuntimeError("the game's own picture %s would have gone, so nothing was written" % name)
    backup = paths.backups() / "menusystem" / "missionsprites.res"
    if not backup.exists():
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, backup)
    path.write_bytes(new)
    return True


def _open(game):
    path = protect.assert_menu_sprites(pathlib.Path(game) / REL)
    raw = path.read_bytes()
    sprites, folder = _split(_read(raw))
    return path, raw, sprites, folder


def set_cover(game, slot, png, log=print):
    """Put slot's picture in the game's mission list (png: PNG bytes), or take
    it out (None). True when the file changed."""
    slot = int(slot)
    if slot < protect.FIRST_CUSTOM:
        raise protect.ProtectedPath("refusing to change built-in mission %d's picture" % slot)
    path, raw, sprites, folder = _open(game)
    name = _name(slot)
    had = any(n.lower() == name.lower() for n, _ in sprites)
    keep = [(n, b) for n, b in sprites if n.lower() != name.lower()]
    if png is not None:
        keep.append((name, sprite(png, sprites)))
        keep.sort(key=_order)
    changed = _write(path, raw, keep, folder, log)
    if changed:
        log("mission %d's picture in the game's list: %s" % (slot, "yours" if png is not None else "taken out"))
    elif png is None and not had:
        return False
    return changed


def move(game, moves, log=print):
    """Renumbered missions keep their pictures: {old: new}."""
    moves = {int(a): int(b) for a, b in moves.items() if int(a) != int(b)}
    if not moves:
        return False
    path, raw, sprites, folder = _open(game)
    bodies = {_number(n): b for n, b in sprites if (_number(n) or 0) in moves}
    if not bodies:
        return False
    keep = [(n, b) for n, b in sprites if (_number(n) or 0) not in moves and (_number(n) or 0) not in moves.values()]
    for old, body in bodies.items():
        keep.append((_name(moves[old]), body))
    keep.sort(key=_order)
    changed = _write(path, raw, keep, folder, log)
    if changed:
        log("the missions' pictures moved with them: %s" % ", ".join("%d -> %d" % (a, moves[a]) for a in sorted(bodies)))
    return changed


def has_cover(game, slot):
    try:
        _, _, sprites, _ = _open(game)
    except (OSError, ValueError, protect.ProtectedPath):
        return False
    return any(n.lower() == _name(slot).lower() for n, _ in sprites)
