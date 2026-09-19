# The game's text resources: language/<lang>/objectives.res and messages.res.
#
# An ILFF "IRES" archive of chunk pairs - NAME (the key a script names) and
# CSTR (the text), NUL-terminated, padded to 4 bytes. Like the model archives,
# each chunk header carries NEXT, the distance to the following chunk, and 0 on
# the last one; the file header carries the file's length.
#
#   20-byte header: "ILFF", u32 file length, u32 4, u32 0, "IRES"
#   chunk:          tag, u32 payload length, u32 alignment (4), u32 NEXT, payload
#
# A mission's own strings (objective texts, map labels) go in under its own
# prefix, MS<slot>_, in every language folder the game has. Every Apply
# removes that prefix's keys and adds the current ones, so nothing piles up and
# no other key is ever touched. The first time a file is changed, the original
# is copied to backups/language/<lang>/.
#
#   set_mission_strings(game, 15, {"objectives.res": {"MS15_O1": "Steal the truck"}, "messages.res": {}})
#   python studio/build/lang.py dump <game>\language\USA\objectives.res
import pathlib, re, shutil, struct, sys

from studio import protect
from studio import paths

ROOT = pathlib.Path(__file__).resolve().parents[2]
FILES = ("objectives.res", "messages.res")


def read(path):
    """[(tag, text)] in archive order."""
    b = pathlib.Path(path).read_bytes()
    if b[:4] != b"ILFF" or b[16:20] != b"IRES":
        raise ValueError("%s is not a text resource archive" % path)
    out, off = [], 20
    while off + 16 <= len(b):
        tag = b[off:off + 4]
        ln, al, _ = struct.unpack_from("<III", b, off + 4)
        if al == 0 or off + 16 + ln > len(b):
            break
        out.append((tag, b[off + 16:off + 16 + ln]))
        off += 16 + ((ln + al - 1) // al) * al
    return out


def build(chunks):
    body = bytearray()
    for i, (tag, pay) in enumerate(chunks):
        last = i == len(chunks) - 1
        padded = pay if last else pay + b"\0" * (-len(pay) % 4)    # the game's files don't pad the last chunk
        nxt = 0 if last else 16 + len(padded)
        body += tag + struct.pack("<III", len(pay), 4, nxt) + padded
    return b"ILFF" + struct.pack("<III", 20 + len(body), 4, 0) + b"IRES" + bytes(body)


def strings(path):
    out, key = {}, None
    for tag, pay in read(path):
        s = pay.split(b"\0")[0].decode("latin1")
        if tag == b"NAME":
            key = s
        elif tag == b"CSTR" and key is not None:
            out[key] = s
            key = None
    return out


def _cstr(text):
    return str(text).replace("\r", " ").replace("\n", " ").encode("latin1", "replace") + b"\0"


def set_mission_strings(game, slot, tables, log=print):
    """Replace mission slot's strings in every language folder of the game."""
    prefix = "MS%d_" % int(slot)
    if int(slot) < protect.FIRST_CUSTOM:
        raise protect.ProtectedPath("refusing to write strings for built-in level %d" % slot)
    changed = 0
    for lang in sorted((pathlib.Path(game) / "language").iterdir()):
        for name in FILES:
            path = lang / name
            if not path.exists():
                continue
            protect.assert_language_file(path)
            table = tables.get(name) or {}
            for k in table:
                if not k.startswith(prefix) or len(k) > 31:
                    raise ValueError("string key %r must start with %s and fit 31 characters" % (k, prefix))
            chunks = read(path)
            kept, i = [], 0
            while i < len(chunks):
                tag, pay = chunks[i]
                if tag == b"NAME" and pay.split(b"\0")[0].decode("latin1").startswith(prefix):
                    i += 2 if i + 1 < len(chunks) and chunks[i + 1][0] == b"CSTR" else 1
                    continue
                kept.append((tag, pay))
                i += 1
            for k, text in table.items():
                kept.append((b"NAME", k.encode("latin1") + b"\0"))
                kept.append((b"CSTR", _cstr(text)))
            data = build(kept)
            if data == path.read_bytes():
                continue
            backup = paths.backups() / "language" / lang.name / name
            if not backup.exists():
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, backup)
            path.write_bytes(data)
            changed += 1
    if changed:
        n = sum(len(tables.get(f) or {}) for f in FILES)
        log("mission strings %s*: %d in %d language file(s)" % (prefix, n, changed))
    return changed


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "dump":
        for k, v in strings(sys.argv[2]).items():
            print("%-32s %s" % (k, v))
    elif len(sys.argv) > 2 and sys.argv[1] == "check":
        p = pathlib.Path(sys.argv[2])
        print("round trip identical:", build(read(p)) == p.read_bytes())
