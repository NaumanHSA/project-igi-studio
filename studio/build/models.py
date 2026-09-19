# Packs models from other levels into a level, so any building, object or
# soldier in the game can be placed anywhere - not only the ones that level
# shipped with.
#
#   python studio/build/models.py verify [location0 dir]
#       For every level: the .mtp must be exactly what its .dat compiles to, the
#       texture archive must be in palette order, and both archives must have an
#       intact chunk chain. A level that fails is never written to.
#   python studio/build/models.py import --slot 15 --models 400_19_1,437_01_1 [--game <game>]
#   python studio/build/models.py repair --slot 15       fix chunk chains, complete families
#   python studio/build/models.py restore --slot 15      undo every import
#
# A level loads models through four files that must agree:
#   levelN.dat              text, "machine generated": every model with the
#                           textures it uses, then every texture name, then "0"
#   levelN.mtp              IFF "MTP " compiled from the .dat (layout below)
#   models/levelN.res       ILFF archive of NAME/BODY chunks, one .mef per model
#   textures/levelN.res     ILFF archive of NAME/BODY chunks, one .tex per texture,
#                           in the palette's texture order
#
# .mtp sections (big-endian IFF chunk headers, little-endian payloads):
#   BANM, SNDS, SVOL, PALF  u32 0
#   MODS  u32 n, then n NUL-terminated model names, NUL-padded to 4 bytes
#   VNAM  u32 n, n u32 offsets, then the same names block as MODS;
#         offset[i] = sum over earlier models of (texture count + 1) * 4
#   INST  per model: u32 index, u32 texture count, u32 texture index...
#   TEXF  u32 t, then t NUL-terminated texture names, NUL-padded to 4 bytes
#   GTT   u32 t, then t pairs (u32 i, i32 -1)
#
# ILFF archive chunk: tag, u32 payload length, u32 alignment, u32 NEXT, payload
# padded to the alignment. NEXT is the distance to the following chunk - and 0
# on the last one, which is where the game stops reading. Appending after that
# 0 without fixing it leaves every appended model invisible to the game.
#
# Models come in families: everything sharing the first number group (416_01_1,
# its LODs 416_01_2..5, and parts like 416_02_1). The game needs all of them.
# A model can also be built from parts of OTHER families, named in its ATTA
# chunk (68 bytes a part: a 16-byte name, then its offset and matrix): the
# watchtower 405_01_1 carries the stairs 314_01_1. Those come along too, or the
# level dies loading with 'VirModel "314_01_1" not available'.
#
# Importing only APPENDS: new models after the existing ones, new textures after
# the existing ones, new chunks at the end of each archive. Nothing already in
# the level changes index, so everything that worked keeps working, and restore
# is a truncation back to the recorded sizes (plus the original last chunk).
#
# Source levels are read from their compiled .mtp, not their .dat: level 10's
# .dat lists more models than its own count says, the .mtp is consistent.
import json, pathlib, re, shutil, struct, sys

from studio import protect
from studio import paths

ROOT = pathlib.Path(__file__).resolve().parents[2]
NUL = b"\x00"


# ------------------------------------------------------------------ .dat / .mtp
def read_dat(path):
    text = open(path, encoding="latin1", newline="").read()
    nl = "\r\n" if "\r\n" in text else "\n"
    marker = "DO NOT EDIT!" + nl
    cut = text.index(marker) + len(marker) if marker in text else 0
    header = text[:cut]
    body = text[cut:]
    lead = body[:len(body) - len(body.lstrip("\r\n"))]
    lines = [l.strip() for l in body.splitlines() if l.strip()]
    it = iter(lines)
    models = []
    for _ in range(int(next(it))):
        name = next(it)
        models.append((name, [next(it) for _ in range(int(next(it)))]))
    textures = [next(it) for _ in range(int(next(it)))]
    return {"header": header + lead, "models": models, "textures": textures,
            "tail": list(it), "newline": nl}


def write_dat(d):
    nl = d["newline"]
    rows = [str(len(d["models"]))]
    for name, texs in d["models"]:
        rows += [name, str(len(texs))] + texs
    rows += [str(len(d["textures"]))] + d["textures"] + d["tail"]
    return d["header"] + nl.join(rows) + nl


def _iff(b):
    out, off = {}, 12
    while off + 8 <= len(b):
        tag = b[off:off + 4]
        ln = struct.unpack(">I", b[off + 4:off + 8])[0]
        out[tag] = b[off + 8:off + 8 + ln]
        off += 8 + ln + (ln & 1)
    return out


def read_mtp(path):
    """Models and their textures straight from a compiled palette."""
    s = _iff(open(path, "rb").read())
    n = struct.unpack_from("<I", s[b"MODS"], 0)[0]
    names = [x.decode("latin1") for x in s[b"MODS"][4:].split(NUL)[:n]]
    t = struct.unpack_from("<I", s[b"TEXF"], 0)[0]
    texf = [x.decode("latin1") for x in s[b"TEXF"][4:].split(NUL)[:t]]
    inst, off, models = s[b"INST"], 0, {}
    while off + 8 <= len(inst):
        idx, cnt = struct.unpack_from("<II", inst, off)
        tex = struct.unpack_from("<%dI" % cnt, inst, off + 8)
        if idx < len(names):
            models[names[idx]] = [texf[i] for i in tex]
        off += 8 + 4 * cnt
    return {"names": names, "models": models, "textures": texf}


def build_mtp(d):
    models, textures = d["models"], d["textures"]
    tix = {t: i for i, t in enumerate(textures)}

    def pad4(b):
        return b + NUL * (-len(b) % 4)
    names = pad4(b"".join(n.encode("latin1") + NUL for n, _ in models))
    offsets, acc, inst = [], 0, []
    for i, (_, texs) in enumerate(models):
        offsets.append(acc)
        acc += (len(texs) + 1) * 4
        inst.append(struct.pack("<II", i, len(texs)) + b"".join(struct.pack("<I", tix[t]) for t in texs))
    tnames = pad4(b"".join(t.encode("latin1") + NUL for t in textures))
    zero = struct.pack("<I", 0)
    secs = [
        (b"BANM", zero), (b"SNDS", zero), (b"SVOL", zero),
        (b"MODS", struct.pack("<I", len(models)) + names),
        (b"VNAM", struct.pack("<I", len(models)) + b"".join(struct.pack("<I", o) for o in offsets) + names),
        (b"INST", b"".join(inst)),
        (b"TEXF", struct.pack("<I", len(textures)) + tnames),
        (b"PALF", zero),
        (b"GTT ", struct.pack("<I", len(textures)) + b"".join(struct.pack("<Ii", i, -1) for i in range(len(textures)))),
    ]
    body = b"MTP "
    for tag, pay in secs:
        body += tag + struct.pack(">I", len(pay)) + pay + (NUL if len(pay) & 1 else b"")
    return b"FORM" + struct.pack(">I", len(body)) + body


# ------------------------------------------------------------------ .res archives
def _headers(path):
    """(offset, tag, payload length, alignment, next, padded chunk length) for every chunk."""
    out = []
    with open(path, "rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        off = 20
        while off + 16 <= size:
            fh.seek(off)
            tag = fh.read(4)
            ln, al, nxt = struct.unpack("<III", fh.read(12))
            if al == 0 or off + 16 + ln > size:
                break
            full = 16 + ((ln + al - 1) // al) * al
            out.append((off, tag, ln, al, nxt, full))
            off += full
    return out


def chain_ok(path):
    h = _headers(path)
    return bool(h) and all(c[4] == c[5] for c in h[:-1]) and h[-1][4] == 0


def fix_chain(path):
    """Every chunk points at the next; the last one says 0. Returns chunks changed."""
    protect.assert_writable(path)
    h = _headers(path)
    changed = 0
    with open(path, "r+b") as fh:
        for i, c in enumerate(h):
            want = 0 if i == len(h) - 1 else c[5]
            if c[4] != want:
                fh.seek(c[0] + 12)
                fh.write(struct.pack("<I", want))
                changed += 1
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(4)
        fh.write(struct.pack("<I", size))
    return changed


# ------------------------------------------------------------------ lightmaps
# A level bakes a lightmap for every object it ships, and a model's render
# groups say whether they are lit that way: field 13 of each DNER group header
# is 12 for "lit by the level's lightmap", 0 for "lit dynamically". A model
# copied into another level has no lightmap there, and the engine then draws
# NOTHING - the object is in the world, it makes its sounds, and it cannot be
# seen (found 2026-09-18 with a siren and an alarm light in a level 3 mission).
# The same models ship with 0 in levels that light them dynamically - level 6's
# siren is byte-identical to level 1's apart from this flag - so an imported
# model gets the flag switched off. Lengths do not change, so the archive's
# chunk chain is untouched.
def _mef_chunks(mef, start=20):
    """[(tag, payload start, payload length)] of a .mef body."""
    out, off = [], start
    while off + 16 <= len(mef):
        tag = mef[off:off + 4]
        ln, al, _ = struct.unpack_from("<III", mef, off + 4)
        if al == 0 or off + 16 + ln > len(mef):
            break
        out.append((tag, off + 16, ln))
        off += 16 + ((ln + al - 1) // al) * al
    return out


def parts_of(mef):
    """The models a .mef is built from (its ATTA chunk)."""
    out = []
    for tag, off, ln in _mef_chunks(mef):
        if tag != b"ATTA":
            continue
        for i in range(ln // 68):
            name = mef[off + i * 68:off + i * 68 + 16].split(NUL)[0].decode("latin1").strip()
            if name and name not in out:
                out.append(name)
    return out


def _body(bc):
    """A .mef out of its archive BODY chunk."""
    return bc[16:16 + struct.unpack_from("<I", bc, 4)[0]]


def with_parts(wanted, find):
    """wanted, and every model they are built from, over and over: (all, parts).
    find(name) gives a model's .mef, or None."""
    out, parts, queue = [], set(), list(wanted)
    while queue:
        m = queue.pop(0)
        if m in out:
            continue
        out.append(m)
        mef = find(m)
        for part in (parts_of(mef) if mef else []):
            if part not in out:
                parts.add(part)
                queue.append(part)
    return out, parts


def unlight_mef(mef):
    """The same model, lit dynamically instead of by a lightmap it does not have."""
    chunks = _mef_chunks(mef)
    d3 = next(((o, n) for t, o, n in chunks if t == b"D3DR"), None)
    if not d3 or d3[1] != 56:
        return mef, 0                     # 48-byte header: no lightmap to start with
    out, changed = bytearray(mef), 0
    for tag, off, ln in chunks:
        if tag != b"DNER":
            continue
        u = list(struct.unpack_from("<%dH" % (ln // 2), mef, off))
        pos = 0
        while pos + 16 <= len(u):
            cnt = u[pos + 6]
            if u[pos + 13]:
                struct.pack_into("<H", out, off + (pos + 13) * 2, 0)
                changed += 1
            pos += 16 + cnt
        if pos != len(u):
            return mef, 0                 # a layout this does not understand: leave it alone
    return bytes(out), changed


def unlight_archive(models_res, names, log=print):
    """Switch the lightmap flag off for models already in a level's archive."""
    raw, entries = res_entries(models_res)
    want, out, hits = set(names), bytearray(raw), 0
    for stem, nc, bc in entries:
        if stem not in want:
            continue
        body, n = unlight_mef(bc[16:16 + struct.unpack_from("<I", bc, 4)[0]])
        if not n:
            continue
        at = raw.find(bc)
        if at < 0:
            continue
        out[at + 16:at + 16 + len(body)] = body
        hits += 1
    if hits:
        protect.assert_writable(models_res)
        open(models_res, "wb").write(bytes(out))
        log("lightmaps: %d imported model(s) switched to dynamic light (they are invisible otherwise)" % hits)
    return hits


def res_entries(path):
    """[(stem, name chunk, body chunk)] in archive order; chunks include padding."""
    b = open(path, "rb").read()
    out, off, pending = [], 20, None
    while off + 16 <= len(b):
        tag = b[off:off + 4]
        ln, al, _ = struct.unpack_from("<III", b, off + 4)
        if al == 0 or off + 16 + ln > len(b):
            break
        end = off + 16 + ((ln + al - 1) // al) * al
        if tag == b"NAME":
            raw = b[off + 16:off + 16 + ln].split(NUL)[0].decode("latin1")
            pending = (res_stem(raw), b[off:end])
        elif tag == b"BODY" and pending:
            out.append((pending[0], pending[1], b[off:end]))
            pending = None
        off = end
    return b, out


def res_stem(name):
    return re.sub(r"^.*[/\\]", "", name).rsplit(".", 1)[0]


def level_files(level_dir):
    level_dir = pathlib.Path(level_dir)
    dat = next(iter(sorted(level_dir.glob("*.dat"))), None)
    if dat is None:
        return None
    base = dat.stem
    return {"dir": level_dir, "base": base, "dat": dat, "mtp": level_dir / (base + ".mtp"),
            "models": level_dir / "models" / (base + ".res"),
            "textures": level_dir / "textures" / (base + ".res")}


def check_level(f):
    """(ok, reason, dat) - whether this level's files are in a shape we can write to."""
    try:
        d = read_dat(f["dat"])
    except (StopIteration, ValueError) as e:
        return False, ".dat does not parse (%s)" % type(e).__name__, None
    if build_mtp(d) != open(f["mtp"], "rb").read():
        return False, ".mtp is not what the .dat compiles to", d
    if write_dat(d) != open(f["dat"], encoding="latin1", newline="").read():
        return False, ".dat does not round-trip", d
    _, tex = res_entries(f["textures"])
    if [s for s, *_ in tex] != d["textures"]:
        return False, "texture archive is not in palette order", d
    for key in ("models", "textures"):
        if not chain_ok(f[key]):
            return False, "%s archive has a broken chunk chain (run repair)" % key, d
    return True, "", d


def verify(root):
    good = []
    for lv in sorted(pathlib.Path(root).glob("level*"), key=lambda p: int(re.sub(r"\D", "", p.name) or 0)):
        f = level_files(lv)
        if not f or not f["mtp"].exists():
            continue
        ok, why, d = check_level(f)
        src = read_mtp(f["mtp"])
        _, mods = res_entries(f["models"])
        have = {s for s, *_ in mods}
        missing = [n for n in src["names"] if n not in have and n not in ("waypoint", "dummy")]
        print("%-8s %s  %d models (%d .mef, %d not in archive), %d textures%s"
              % (lv.name, "writable" if ok else "read-only", len(src["names"]), len(mods), len(missing),
                 len(src["textures"]), "" if ok else "  - " + why))
        if ok:
            good.append(lv.name)
    return good


# ------------------------------------------------------------------ import
def family_prefix(name):
    return name.split("_", 1)[0]


def find_sources(location0, skip):
    """Every other level, read from its compiled palette, with a lazy archive index."""
    out = []
    for lv in sorted(pathlib.Path(location0).glob("level*"), key=lambda p: int(re.sub(r"\D", "", p.name) or 0)):
        if lv.name in skip:
            continue
        f = level_files(lv)
        if not f or not f["mtp"].exists() or not f["models"].exists():
            continue
        try:
            out.append((f, read_mtp(f["mtp"])))
        except (KeyError, struct.error):
            continue
    return out


def import_models(slot_dir, wanted, location0, log=print, backup_root=None):
    """Append the wanted models' whole families (with textures) to a level."""
    protect.assert_writable(slot_dir)
    f = level_files(slot_dir)
    ok, why, d = check_level(f)
    if not ok:
        raise RuntimeError("level %s cannot take imported models: %s" % (f["dir"].name, why))
    have = {n for n, _ in d["models"]}
    wanted = [m for m in dict.fromkeys(wanted) if m]
    sources = find_sources(location0, skip={f["dir"].name})
    cache = {}

    def archive(path):
        if path not in cache:
            cache[path] = {s: (nc, bc) for s, nc, bc in res_entries(path)[1]}
        return cache[path]
    def find(name):
        # this level's own copy first, else the first level that ships it
        own = archive(f["models"])
        if name in own:
            return _body(own[name][1])
        for sf, sm in sources:
            if name in sm["models"]:
                a = archive(sf["models"])
                if name in a:
                    return _body(a[name][1])
        return None
    # what they are built from, all the way down
    wanted, parts = with_parts(wanted, find)
    if not [m for m in wanted if m not in have] and not _incomplete(f, d, wanted, location0):
        return []

    backup_root = pathlib.Path(backup_root or (paths.backups() / "models"))
    record = backup_root / f["dir"].name / "import.json"
    if not record.exists():
        record.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(f["dat"], record.parent / f["dat"].name)
        shutil.copyfile(f["mtp"], record.parent / f["mtp"].name)
        rec = {"imported": []}
        for key in ("models", "textures"):
            h = _headers(f[key])
            rec[key + "_size"] = f[key].stat().st_size
            rec[key + "_head"] = open(f[key], "rb").read(20).hex()
            rec[key + "_last"] = [h[-1][0], h[-1][4]]
        json.dump(rec, record.open("w"), indent=2)
        log("backed up %s's model list; archives restore by truncation" % f["dir"].name)
    rec = json.load(record.open())

    tex_have = set(d["textures"])
    new_models, new_mef, new_tex, done = [], [], [], []

    for want in wanted:
        src = None
        for sf, sm in sources:
            if want in sm["models"] and want in archive(sf["models"]):
                src = (sf, sm)
                break
        if not src:
            if want in have:
                continue
            if want in parts:
                # a part no level packs: the location's shared archive has it, or the game does without
                log("part %s is in no level's archive - left to the shared one" % want)
                continue
            raise RuntimeError("no level ships model %s" % want)
        sf, sm = src
        prefix = family_prefix(want)
        members = [n for n in sm["names"] if family_prefix(n) == prefix]
        added = 0
        for name in members:
            if name in have or name not in archive(sf["models"]):
                continue
            texs = sm["models"].get(name, [])
            for t in texs:
                if t not in tex_have:
                    chunk = archive(sf["textures"]).get(t)
                    if not chunk:
                        raise RuntimeError("texture %s of model %s is missing from %s" % (t, name, sf["textures"]))
                    new_tex.append(chunk)
                    d["textures"].append(t)
                    tex_have.add(t)
            nc, bc = archive(sf["models"])[name]
            body, lit = unlight_mef(bc[16:16 + struct.unpack_from("<I", bc, 4)[0]])
            if lit:
                bc = bc[:16] + body + bc[16 + len(body):]
            new_mef.append((nc, bc))
            new_models.append((name, texs))
            have.add(name)
            done.append(name)
            added += 1
        if added:
            log("importing family %s_* for %s from %s (%d model file%s)"
                % (prefix, want, sf["dir"].name, added, "" if added == 1 else "s"))

    if not done:
        return []
    d["models"].extend(new_models)
    _append(f["models"], new_mef)
    _append(f["textures"], new_tex)
    open(f["dat"], "w", encoding="latin1", newline="").write(write_dat(d))
    open(f["mtp"], "wb").write(build_mtp(d))
    ok, why, _ = check_level(f)
    if not ok:
        raise RuntimeError("after import the level no longer checks out: %s - run restore" % why)
    rec["imported"] = sorted(set(rec["imported"]) | set(done))
    json.dump(rec, record.open("w"), indent=2)
    # models imported before this was understood are still lightmapped: fix them too
    unlight_archive(f["models"], rec["imported"], log=log)
    log("imported %d model file(s), %d texture(s) into %s" % (len(new_mef), len(new_tex), f["dir"].name))
    return done


_INDEX = {}


def res_index(path):
    """{stem: chunk bytes} of an archive, read from its NAME chunks only (a
    texture archive is hundreds of MB; its bodies are never read here)."""
    path = pathlib.Path(path)
    st = path.stat()
    key = (str(path), st.st_size, st.st_mtime)
    if key not in _INDEX:
        out, pending = {}, None
        with open(path, "rb") as fh:
            for off, tag, ln, al, nxt, full in _headers(path):
                if tag == b"NAME":
                    fh.seek(off + 16)
                    pending = (res_stem(fh.read(ln).split(NUL)[0].decode("latin1")), full)
                elif tag == b"BODY" and pending:
                    out[pending[0]] = pending[1] + full
                    pending = None
        _INDEX[key] = out
    return _INDEX[key]


def estimate(level_dir, wanted, location0):
    """What import_models would copy into level_dir for these models, without
    writing anything: [{model, source, files, textures, bytes}] and totals."""
    f = level_files(level_dir)
    d = read_dat(f["dat"])
    have = {n for n, _ in d["models"]}
    tex_have = set(d["textures"])
    rows, seen = [], set()
    sources = None
    for want in dict.fromkeys(wanted):
        if not want or want in have or family_prefix(want) in seen:
            continue
        if sources is None:
            sources = find_sources(location0, skip={f["dir"].name})
        for sf, sm in sources:
            if want not in sm["models"]:
                continue
            mods = res_index(sf["models"])
            if want not in mods:
                continue
            texs = res_index(sf["textures"])
            members = [n for n in sm["names"] if family_prefix(n) == family_prefix(want)
                       and n not in have and n in mods]
            size, ntex = 0, 0
            for n in members:
                size += mods[n]
                for t in sm["models"].get(n, []):
                    if t not in tex_have and t in texs:
                        tex_have.add(t)
                        size += texs[t]
                        ntex += 1
            rows.append({"model": want, "source": sf["dir"].name, "files": len(members),
                         "textures": ntex, "bytes": size})
            seen.add(family_prefix(want))
            break
        else:
            rows.append({"model": want, "source": None, "files": 0, "textures": 0, "bytes": 0})
    return {"models": rows, "bytes": sum(r["bytes"] for r in rows),
            "textures": sum(r["textures"] for r in rows)}


def _incomplete(f, d, wanted, location0):
    """True if a wanted model is present but some of its family (from its source) is not."""
    have = {n for n, _ in d["models"]}
    for sf, sm in find_sources(location0, skip={f["dir"].name}):
        for w in wanted:
            if w in sm["models"]:
                fam = [n for n in sm["names"] if family_prefix(n) == family_prefix(w)]
                if any(n not in have for n in fam):
                    return True
    return False


def _append(path, chunks):
    """Add chunk pairs at the end, keeping the chain the game walks intact."""
    protect.assert_writable(path)
    if not chunks:
        return
    h = _headers(path)
    with open(path, "r+b") as fh:
        declared = struct.unpack("<I", fh.read(8)[4:8])[0]
        fh.seek(0, 2)
        if fh.tell() != declared:
            raise RuntimeError("%s: length field %d does not match size %d" % (path, declared, fh.tell()))
        for nc, bc in chunks:
            fh.write(nc + bc)
    fix_chain(path)
    if not chain_ok(path):
        raise RuntimeError("%s: chunk chain still broken after append" % path)


def repair(slot_dir, location0, log=print, backup_root=None):
    """Fix chunk chains left by earlier imports and complete partially imported families."""
    protect.assert_writable(slot_dir)
    f = level_files(slot_dir)
    for key in ("models", "textures"):
        n = fix_chain(f[key])
        log("%s archive: %s" % (key, "%d chunk link(s) fixed" % n if n else "chain intact"))
    backup_root = pathlib.Path(backup_root or (paths.backups() / "models"))
    record = backup_root / f["dir"].name / "import.json"
    if record.exists():
        rec = json.load(record.open())
        # an older record did not know the original last chunk; it had NEXT = 0
        for key in ("models", "textures"):
            if key + "_last" not in rec:
                rec[key + "_last"] = [_last_before(f[key], rec[key + "_size"]), 0]
        json.dump(rec, record.open("w"), indent=2)
        heads = sorted({family_prefix(n) for n in rec.get("imported", [])})
        reps = [next(n for n in rec["imported"] if family_prefix(n) == p) for p in heads]
        import_models(slot_dir, reps, location0, log=log, backup_root=backup_root)


def _last_before(path, size):
    last = None
    for c in _headers(path):
        if c[0] + c[5] <= size:
            last = c[0]
    return last


def restore(slot_dir, backup_root=None):
    protect.assert_writable(slot_dir)
    f = level_files(slot_dir)
    backup_root = pathlib.Path(backup_root or (paths.backups() / "models"))
    record = backup_root / f["dir"].name / "import.json"
    if not record.exists():
        print("nothing imported into %s" % f["dir"].name)
        return
    rec = json.load(record.open())
    for key in ("models", "textures"):
        size, head = rec[key + "_size"], bytes.fromhex(rec[key + "_head"])
        last = rec.get(key + "_last") or [_last_before(f[key], size), 0]
        with open(f[key], "r+b") as fh:
            fh.truncate(size)
            fh.seek(0)
            fh.write(head)
            if last[0] is not None:
                fh.seek(last[0] + 12)
                fh.write(struct.pack("<I", last[1]))
    shutil.copyfile(record.parent / f["dat"].name, f["dat"])
    shutil.copyfile(record.parent / f["mtp"].name, f["mtp"])
    record.unlink()
    print("restored %s: removed %d imported model(s)" % (f["dir"].name, len(rec["imported"])))


if __name__ == "__main__":
    argv = sys.argv

    def arg(n, dflt=None):
        return argv[argv.index(n) + 1] if n in argv else dflt

    game = pathlib.Path(arg("--game") or paths.require_game())
    loc0 = game / "missions" / "location0"
    cmd = argv[1] if len(argv) > 1 else ""
    slot = loc0 / ("level%s" % arg("--slot", "15"))
    if cmd == "verify":
        root = argv[2] if len(argv) > 2 and not argv[2].startswith("--") else str(paths.pristine() / "missions" / "location0")
        print("%d level(s) writable" % len(verify(root)))
    elif cmd == "import":
        import_models(slot, arg("--models", "").split(","), loc0)
    elif cmd == "repair":
        repair(slot, loc0)
    elif cmd == "restore":
        restore(slot)
    else:
        sys.exit("usage: model_import.py verify|import|repair|restore [--slot N] [--game DIR]")
