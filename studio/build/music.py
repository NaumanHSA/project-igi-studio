# The game's music, for a mission of the studio's to play another level's, the
# main menu's or the outro's instead of its map's own.
#
# A level plays missions/location0/level<N>/sounds/game_music.wav. The engine
# loads it by that name - no script names it; a level's scripts only turn the
# music off and on round a cutscene (Game_DisableMusic) - so a mission's slot
# gets the track chosen for it under that name, or its base level's own again.
#
# The game's sounds are ILSF: "ILSF", then u16 format, u16 bits, u16 channels,
# u16 flags, u32 sample rate, u32 frames, and the data. Formats 0 and 1 are
# 16-bit PCM - every level's music, 44.1 kHz stereo, flags 0x1003. Formats 2
# and 3 are IMA ADPCM with no blocks: a byte a stereo frame, its low nibble the
# left channel, both starting from 0 at step 0 - the main menu's music (format
# 3, in menusystem/SOUND/sounds.res) and the outro's (format 2,
# screens/intro/outro.wav). A compressed track goes into a slot as 16-bit PCM,
# as the levels' own music is.
#
# Fourteen levels, nine tracks: 1 and 7, 3, 6 and 10, 4 and 14, 8 and 13 play
# the same one. They are listed once, with every mission that plays them.
#
#   tracks(game)                         [{id, kind, label, missions, secs, peaks}]
#   preview(game, id)                    (RIFF header, file, offset, length): a WAV the browser plays
#   install(game, slot, id, base, log)   write the slot's game_music.wav
import array, hashlib, json, pathlib, re, struct, sys, threading

from studio import paths, protect

HEAD = struct.Struct("<4sHHHHII")        # ILSF, format, bits, channels, flags, rate, frames: 20 bytes
MUSIC_FLAGS = 0x1003                     # what every level's game_music.wav carries
MENU = (pathlib.Path("menusystem") / "SOUND" / "sounds.res", "LOCAL:menusystem/sound/menu_music.wav")
OUTRO = pathlib.Path("screens") / "intro" / "outro.wav"
PEAKS = 48                               # bars in a track's picture
TRACK_ID = re.compile(r"^(menu|outro|level([1-9]|1[0-4]))$")
_lock = threading.Lock()

STEP = [7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45, 50, 55, 60, 66, 73, 80, 88,
        97, 107, 118, 130, 143, 157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449, 494, 544, 598, 658,
        724, 796, 876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327, 3660,
        4026, 4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493, 10442, 11487, 12635, 13899, 15289, 16818,
        18500, 20350, 22385, 24623, 27086, 29794, 32767]
INDEX = [-1, -1, -1, -1, 2, 4, 6, 8, -1, -1, -1, -1, 2, 4, 6, 8]


def _tables():
    """What each nibble adds at each step, and the step it leaves: IMA's rule,
    worked out once."""
    diff, nxt = [0] * (89 * 16), [0] * (89 * 16)
    for i, step in enumerate(STEP):
        for n in range(16):
            d = step >> 3
            if n & 1:
                d += step >> 2
            if n & 2:
                d += step >> 1
            if n & 4:
                d += step
            diff[i * 16 + n] = -d if n & 8 else d
            nxt[i * 16 + n] = min(88, max(0, i + INDEX[n]))
    return diff, nxt


DIFF, NXT = _tables()


def info(b):
    tag, fmt, bits, ch, flags, rate, frames = HEAD.unpack_from(b, 0)
    if tag != b"ILSF":
        raise ValueError("not one of the game's sounds (ILSF)")
    return {"format": fmt, "bits": bits, "channels": ch, "flags": flags, "rate": rate, "frames": frames}


def _ima(data, channels, frames):
    """16-bit samples, interleaved, of block-less IMA ADPCM."""
    out = array.array("h", bytes(len(data) * 4))
    p0 = p1 = i0 = i1 = 0
    j = 0
    if channels == 2:
        for b in data:
            k = i0 + (b & 15)
            p0 += DIFF[k]
            i0 = NXT[k] << 4
            if p0 > 32767:
                p0 = 32767
            elif p0 < -32768:
                p0 = -32768
            k = i1 + (b >> 4)
            p1 += DIFF[k]
            i1 = NXT[k] << 4
            if p1 > 32767:
                p1 = 32767
            elif p1 < -32768:
                p1 = -32768
            out[j] = p0
            out[j + 1] = p1
            j += 2
    else:
        for b in data:
            for n in (b & 15, b >> 4):
                k = i0 + n
                p0 += DIFF[k]
                i0 = NXT[k] << 4
                if p0 > 32767:
                    p0 = 32767
                elif p0 < -32768:
                    p0 = -32768
                out[j] = p0
                j += 1
    del out[frames * channels:]
    if sys.byteorder == "big":
        out.byteswap()
    return out.tobytes()


def pcm(b):
    """(channels, rate, 16-bit little-endian PCM) of an ILSF sound."""
    h = info(b)
    if h["bits"] != 16:
        raise ValueError("a %d-bit sound is not one the studio reads" % h["bits"])
    ch, data = h["channels"], b[HEAD.size:]
    if h["format"] in (0, 1):
        return ch, h["rate"], data[:h["frames"] * ch * 2]
    if h["format"] in (2, 3):
        return ch, h["rate"], _ima(data, ch, h["frames"])
    raise ValueError("sound format %d is not one the studio reads" % h["format"])


def ilsf(ch, rate, data, flags=MUSIC_FLAGS):
    """16-bit PCM as the game's own sound file."""
    return HEAD.pack(b"ILSF", 1, 16, ch, flags, rate, len(data) // (2 * ch)) + data


def riff_header(ch, rate, nbytes):
    return (b"RIFF" + struct.pack("<I", 36 + nbytes) + b"WAVE" +
            b"fmt " + struct.pack("<IHHIIHH", 16, 1, ch, rate, rate * ch * 2, ch * 2, 16) +
            b"data" + struct.pack("<I", nbytes))


# ---------------------------------------------------------------- the tracks
def _level_file(game, n):
    return pathlib.Path(game) / "missions" / "location0" / ("level%d" % n) / "sounds" / "game_music.wav"


def _res_entry(path, name):
    """The body of one entry of a resource archive, or None."""
    b = pathlib.Path(path).read_bytes()
    off, pending = 20, None
    while off + 16 <= len(b):
        tag = b[off:off + 4]
        ln, al, _ = struct.unpack_from("<III", b, off + 4)
        if al == 0 or off + 16 + ln > len(b):
            break
        if tag == b"NAME":
            pending = b[off + 16:off + 16 + ln].split(b"\0")[0].decode("latin1")
        elif tag == b"BODY" and pending is not None:
            if pending.lower() == name.lower():
                return b[off + 16:off + 16 + ln]
            pending = None
        off += 16 + ((ln + al - 1) // al) * al
    return None


def source(game, tid):
    """The track as the game has it (ILSF bytes)."""
    if not TRACK_ID.match(tid or ""):
        raise ValueError("no such track: %r" % tid)
    game = pathlib.Path(game)
    if tid == "menu":
        body = _res_entry(game / MENU[0], MENU[1])
        if body is None:
            raise FileNotFoundError("the main menu's music is not in %s" % (game / MENU[0]))
        return body
    if tid == "outro":
        return (game / OUTRO).read_bytes()
    return _level_file(game, int(tid[5:])).read_bytes()


def _stamp(game, tid):
    """What a cached picture of the track was made from."""
    game = pathlib.Path(game)
    f = game / MENU[0] if tid == "menu" else game / OUTRO if tid == "outro" else _level_file(game, int(tid[5:]))
    st = f.stat()
    return [st.st_size, int(st.st_mtime)]


def _cache():
    d = paths.work() / "music"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _index():
    try:
        return json.loads((_cache() / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _peaks(ch, data, n=PEAKS):
    """How loud each stretch of it is, 0-1: n bars, from samples spread through each."""
    frames = len(data) // (2 * ch)
    if not frames:
        return [0.0] * n
    a = array.array("h")
    out = []
    for k in range(n):
        f0, f1 = frames * k // n, frames * (k + 1) // n
        step = max(1, (f1 - f0) // 1500)
        a = array.array("h", data[f0 * ch * 2:f1 * ch * 2])
        if sys.byteorder == "big":
            a.byteswap()
        vals = a[::step * ch]
        out.append((sum(v * v for v in vals) / max(1, len(vals))) ** 0.5)
    top = max(out) or 1.0
    return [round(v / top, 3) for v in out]


def _meta(game, tid):
    """{hash, secs, peaks, channels, rate} of a track, cached against its file."""
    idx = _index()
    st = _stamp(game, tid)
    m = idx.get(tid)
    if m and m.get("stamp") == st:
        return m
    raw = source(game, tid)
    h = info(raw)
    ch, rate, data = pcm(raw)
    m = {"stamp": st, "hash": hashlib.sha1(raw).hexdigest()[:16], "channels": ch, "rate": rate,
         "secs": round(len(data) / (2 * ch) / float(rate), 1), "peaks": _peaks(ch, data), "format": h["format"]}
    if h["format"] not in (0, 1):
        # a compressed one is played back from its decoded copy
        (_cache() / (tid + ".pcm")).write_bytes(data)
    with _lock:
        idx = _index()
        idx[tid] = m
        (_cache() / "index.json").write_text(json.dumps(idx), encoding="utf-8")
    return m


def _mission_names():
    try:
        b = json.loads((paths.data() / "builtins.json").read_text(encoding="utf-8"))
        rows = b.get("missions") if isinstance(b, dict) else b
        return {int(r["level"]): r.get("name") or "Mission %d" % r["level"] for r in rows or []}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def tracks(game):
    """Every track a mission can have, the same one once: the main menu's, the
    missions' (each with every mission that plays it), the outro's."""
    game = pathlib.Path(game)
    names = _mission_names()
    out = []

    def add(tid, kind, label, missions):
        try:
            m = _meta(game, tid)
        except (OSError, ValueError) as e:
            return None
        out.append({"id": tid, "kind": kind, "label": label, "missions": missions, "secs": m["secs"],
                    "peaks": m["peaks"], "hash": m["hash"]})
        return m

    add("menu", "menu", "Main menu", [])
    seen = {}
    for n in range(1, 15):
        if not _level_file(game, n).is_file():
            continue
        try:
            h = _meta(game, "level%d" % n)["hash"]
        except (OSError, ValueError):
            continue
        seen.setdefault(h, []).append(n)
    for h, levels in sorted(seen.items(), key=lambda kv: kv[1][0]):
        add("level%d" % levels[0], "mission", names.get(levels[0]) or "Mission %d" % levels[0],
            [{"n": n, "name": names.get(n) or "Mission %d" % n} for n in levels])
    add("outro", "outro", "Outro", [])
    return out


def track_of_level(game, n):
    """The listed track a level plays (the first level that plays the same)."""
    h = _meta(game, "level%d" % n)["hash"]
    for k in range(1, 15):
        if _level_file(game, k).is_file() and _meta(game, "level%d" % k)["hash"] == h:
            return "level%d" % k
    return "level%d" % n


def preview(game, tid):
    """A WAV of the track for the browser: (its 44-byte header, the file its
    samples are in, where they start, how many bytes) - a level's music is its
    own file past the game's header; a compressed one, its decoded copy."""
    m = _meta(game, tid)
    ch, rate = m["channels"], m["rate"]
    if m["format"] in (0, 1):
        f = pathlib.Path(game) / MENU[0] if tid == "menu" else \
            pathlib.Path(game) / OUTRO if tid == "outro" else _level_file(game, int(tid[5:]))
        n = min(f.stat().st_size - HEAD.size, int(round(m["secs"] * rate)) * ch * 2)
        n -= n % (ch * 2)
        if tid in ("menu", "outro"):
            raise ValueError("unexpected: an uncompressed %s" % tid)
        return riff_header(ch, rate, n), f, HEAD.size, n
    f = _cache() / (tid + ".pcm")
    if not f.is_file():
        (_cache() / "index.json").unlink(missing_ok=True)
        m = _meta(game, tid)
    n = f.stat().st_size
    return riff_header(ch, rate, n), f, 0, n


def game_music(game, tid):
    """The track as a slot's game_music.wav: a level's as it is, a compressed one as 16-bit PCM."""
    raw = source(game, tid)
    h = info(raw)
    if h["format"] in (0, 1):
        return raw
    ch, rate, data = pcm(raw)
    return ilsf(ch, rate, data)


def install(game, slot, tid, base_level, log=print):
    """Give slot its music: the track chosen for it, or its base level's own.
    Written only when it differs. True when it was written."""
    game = pathlib.Path(game)
    if tid:
        data, what = game_music(game, tid), _label(game, tid)
    else:
        data, what = _level_file(game, int(base_level)).read_bytes(), "its map's own (mission %d)" % int(base_level)
    dest = protect.assert_writable(game / "missions" / "location0" / ("level%d" % int(slot)) / "sounds" /
                                   "game_music.wav")
    if dest.is_file() and dest.stat().st_size == len(data) and dest.read_bytes() == data:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    log("music: %s (%s MB)" % (what, format(round(len(data) / 1e6, 1))))
    return True


def _label(game, tid):
    if tid == "menu":
        return "the main menu's"
    if tid == "outro":
        return "the outro's"
    n = int(tid[5:])
    name = _mission_names().get(n)
    return "mission %d's%s" % (n, " (%s)" % name if name else "")


if __name__ == "__main__":
    g = paths.game()
    for t in tracks(g):
        print("%-8s %-8s %6.1f s  %-24s %s" % (t["id"], t["kind"], t["secs"], t["label"],
                                            ", ".join("%d %s" % (m["n"], m["name"]) for m in t["missions"])))
