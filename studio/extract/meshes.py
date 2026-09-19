# Every structure's 3D shape, for drawing it on the map the way the game's own
# map computer does: a top-down render of the model, not a box.
#
#   python studio/extract/meshes.py [--game <the pristine install>]
#       -> editor/data/meshes.json   {"models": {name: [offset, verts, faces, scale, source]}}
#       -> editor/data/meshes.bin    zlib: per model, verts as int16 x,y,z (x scale metres),
#                                    then faces as uint16 triples, padded to an even length
#
# A .mef holds the render mesh in D3DR (header), DNER (groups) and XTRV (vertices):
#   D3DR 56 bytes: [4, 1, faces, groups, verts, ...]; XTRV stride 40
#                  (position, normal, uv, lightmap uv); each DNER group is 16 u16
#                  (index count at [6], first vertex at [10], vertex count at [11])
#                  followed by its indices, relative to the first vertex.
#   D3DR 48 bytes: [4, faces, groups, verts, ...]; XTRV stride 32 (no lightmap uv);
#                  group headers are 14 u16 (count [6], first vertex [9], count [10]).
# Models with no render mesh (the underground rooms of level 14) fall back to
# their collision mesh (XTVC/ECFC). Every face is kept - the map draws only
# those facing up, the 3D preview needs the walls too.
#
# Characters and weapons (models 000-199) come too - see docs/PLAN-3d.md:
#   - weapons and items are plain meshes, most of them in the archive every
#     level of the location shares (missions/location0/common/models);
#   - characters are skinned: each vertex is in its bone's own space (bone
#     index in the last u16 of its 40-byte XTRV entry), and the skeleton is in
#     common/anims/<hierarchy>.iff. Summing the bone offsets with no rotation
#     gives the bind pose, a figure standing in an A-pose; posed() turns the
#     bones as the first frame of animation 0 has them instead (standing with a
#     rifle at ease). Baked with the feet at the origin, where a HumanSoldier's
#     position is.
#   - meshes.json "pickups" maps a pickup's id to the model the world shows,
#     from the weapon and ammo scripts.
#   - meshes.json "grips" gives, per character, where its weapon goes: bone 22
#     of every human skeleton (a chain off the spine, 20-21-22) is the gun's.
#     In the aiming animations it sits at the chest with no turn at all, the
#     right hand on the grip and the left on the fore-grip, so a weapon model
#     (barrel along +y, its origin at the grip) goes on it as it is. At ease
#     (animation 0) it holds the gun across the body. [x, y, z, then the
#     rotation row by row], in the character's space, feet at z = 0.
import json, math, pathlib, re, struct, sys, tempfile, zlib

from studio.build import surface
from studio import paths

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = paths.data()
SCALE = 4096.0


def ilff(buf, start=20):
    off = start
    while off + 16 <= len(buf):
        tag = buf[off:off + 4]
        ln, al, _ = struct.unpack_from("<III", buf, off + 4)
        if al == 0 or off + 16 + ln > len(buf):
            return
        yield tag, buf[off + 16:off + 16 + ln]
        off += 16 + ((ln + al - 1) // al) * al


def unpack_res(path):
    out, cur = {}, None
    for tag, pay in ilff(path.read_bytes()):
        if tag == b"NAME":
            cur = pay.split(b"\0")[0].decode("latin1").split("/")[-1]
        elif tag == b"BODY" and cur:
            out[cur] = pay
    return out


def render_mesh(mef):
    """(vertices in metres, triangles as index triples) or None."""
    ch = {}
    for tag, pay in ilff(mef, 20):
        ch.setdefault(tag, []).append(pay)
    if b"D3DR" not in ch or b"XTRV" not in ch or b"DNER" not in ch:
        return None
    dd = ch[b"D3DR"][0]
    d = struct.unpack_from("<%di" % (len(dd) // 4), dd)
    if len(dd) == 56:
        nv, hdr, stride, at_vs, at_vc = d[4], 16, 40, 10, 11
    elif len(dd) == 48:
        nv, hdr, stride, at_vs, at_vc = d[3], 14, 32, 9, 10
    else:
        return None
    xt = ch[b"XTRV"][0]
    if nv <= 0 or len(xt) != nv * stride:
        return None
    verts = [tuple(c / SCALE for c in struct.unpack_from("<3f", xt, i * stride)) for i in range(nv)]
    n = ch[b"DNER"][0]
    u = struct.unpack_from("<%dH" % (len(n) // 2), n)
    tris, pos = [], 0
    while pos + hdr <= len(u):
        cnt, vs, vc = u[pos + 6], u[pos + at_vs], u[pos + at_vc]
        idx = u[pos + hdr:pos + hdr + cnt]
        if cnt % 3 or vs + vc > nv or (idx and max(idx) >= vc):
            return None
        for k in range(0, cnt, 3):
            tris.append((vs + idx[k], vs + idx[k + 1], vs + idx[k + 2]))
        pos += hdr + cnt
    if pos != len(u) or not tris:
        return None
    return verts, tris


# A building is often only a stub with its real shape hanging off it: the ATTA
# chunk lists the parts it is built from, 68 bytes each - a 16-byte model name,
# the part's position (game units, /4096 for metres) and a 3x3 matrix. Level
# 14's nuclear coolant system is 84 faces on its own and 7,108 with its parts,
# which is why it used to read as an empty square on the plan. The matrix is
# applied the way Direct3D does it, a row vector times the matrix.
def attachments(mef):
    """[(model name, (x, y, z) in metres, 9 matrix floats)] of one model."""
    out = []
    for tag, pay in ilff(mef, 20):
        if tag != b"ATTA":
            continue
        for i in range(len(pay) // 68):
            e = pay[i * 68:(i + 1) * 68]
            name = e[:16].split(b"\0")[0].decode("latin1").strip()
            if not name:
                continue
            v = struct.unpack_from("<12f", e, 16)
            out.append((name, (v[0] / SCALE, v[1] / SCALE, v[2] / SCALE), v[3:12]))
    return out


# Parts numbered 1000 and up are effects, not structure: the muzzle flashes
# (1000_01_1 ... 1013_01_1) hang off the barrels of twelve weapons and the sentry
# gun, and the game shows them only while firing - drawn always, they are a flat
# panel across the muzzle.
def is_effect(name):
    head = name.split("_")[0]
    return head.isdigit() and int(head) >= 1000


def assembled(models, name, depth=0, seen=()):
    """(verts, tris) of a model with the parts it is built from merged in."""
    mef = models.get(name + ".mef")
    if mef is None or name in seen or depth > 4:
        return None
    mesh = render_mesh(mef)
    verts = list(mesh[0]) if mesh else []
    tris = list(mesh[1]) if mesh else []
    for part, (tx, ty, tz), m in attachments(mef):
        if is_effect(part):
            continue
        sub = assembled(models, part, depth + 1, seen + (name,))
        if not sub or len(verts) + len(sub[0]) > 120000:
            continue
        base = len(verts)
        for (x, y, z) in sub[0]:
            verts.append((m[0] * x + m[3] * y + m[6] * z + tx,
                          m[1] * x + m[4] * y + m[7] * z + ty,
                          m[2] * x + m[5] * y + m[8] * z + tz))
        for (a, b, c) in sub[1]:
            tris.append((base + a, base + b, base + c))
    return (verts, tris) if tris else None


def collision_as_mesh(mef):
    tris = surface.collision_all(mef)
    if not tris:
        return None
    verts, out = [], []
    for t in tris:
        base = len(verts)
        verts.extend(t)
        out.append((base, base + 1, base + 2))
    return verts, out


def compact(verts, tris):
    """Drop degenerate faces, merge vertices closer than 1 cm."""
    keep = []
    for a, b, c in tris:
        p, q, r = verts[a], verts[b], verts[c]
        ux, uy, uz = q[0] - p[0], q[1] - p[1], q[2] - p[2]
        wx, wy, wz = r[0] - p[0], r[1] - p[1], r[2] - p[2]
        nx, ny, nz = uy * wz - uz * wy, uz * wx - ux * wz, ux * wy - uy * wx
        if math.sqrt(nx * nx + ny * ny + nz * nz) < 1e-5:
            continue
        keep.append((a, b, c))
    ext = max((abs(c) for v in verts for c in v), default=1.0)
    scale = 0.01 if ext < 320 else 0.02 if ext < 650 else 0.05
    slot, vout, fout = {}, [], []
    for tri in keep:
        f = []
        for i in tri:
            key = tuple(int(round(c / scale)) for c in verts[i])
            if key not in slot:
                slot[key] = len(vout)
                vout.append(key)
            f.append(slot[key])
        if len(set(f)) == 3:
            fout.append(tuple(f))
    return vout, fout, scale


def wanted(name):
    """Structures, vehicles, props and trees - not characters, weapons or items."""
    stem = name[:-4]
    head = stem.split("_")[0]
    if head.isdigit() and int(head) < 200:
        return False
    return True


def small_kind(name):
    """'character' or 'item' for the most detailed of models 000-199, else None."""
    stem = name[:-4] if name.endswith(".mef") else name
    head = stem.split("_")[0]
    if not (head.isdigit() and int(head) < 200 and stem.endswith("_1")):
        return None
    if int(head) < 100:
        return None if head in NOT_HUMAN else "character"
    return "item"


# ---------------------------------------------------------------- characters
# The skeleton a model is built on (HumanSoldier "Bone Heirachy"): the player 0,
# Anya and Ekk 6, every other human 1. Model 005 is not a person (56 bones) and
# does not come out of the bind pose as one; it is left out.
SKELETON_OF = {"000": "000", "012": "006", "015": "006"}
NOT_HUMAN = {"005"}


def _iff(b, o=0, end=None, path=(), out=None):
    """EA IFF - big-endian chunk lengths - as a flat list of (form path, tag, payload)."""
    out = [] if out is None else out
    end = len(b) if end is None else min(end, len(b))
    while o + 8 <= end:
        tag = b[o:o + 4]
        ln = struct.unpack_from(">I", b, o + 4)[0]
        if tag == b"FORM":
            _iff(b, o + 12, o + 8 + ln, path + (b[o + 8:o + 12].decode("latin1"),), out)
        else:
            out.append(("/".join(path), tag.decode("latin1"), b[o + 8:o + 8 + ln]))
        o += 8 + ln + (ln & 1)
    return out


def skeleton(path):
    """Each bone's position in the bind pose, metres: the offsets (TLST) summed
    down the parent list (PLST). Only the header form is read (FORM BOBH)."""
    b = path.read_bytes()
    d = {}
    for p, tag, pay in _iff(b[:4096]):
        if p.endswith("BOBH") and tag not in d:
            d[tag] = pay
    n = struct.unpack_from("<2i", d["BOSH"])[1]
    par = struct.unpack_from("<%di" % n, d["PLST"])
    pos = []
    for i in range(n):
        o = tuple(v / SCALE for v in struct.unpack_from("<3f", d["TLST"], i * 12))
        pos.append(o if par[i] < 0 else tuple(pos[par[i]][k] + o[k] for k in range(3)))
    return pos


def _qmat(q):
    x, y, z, w = q
    return ((1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
            (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
            (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)))


def _mm(a, b):
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))


def _mv(a, v):
    return tuple(sum(a[i][k] * v[k] for k in range(3)) for i in range(3))


def posed(path, anim=0):
    """Each bone's position (metres) and rotation in the first frame of one of
    the skeleton file's animations, instead of the bind pose's A-pose: animation 0
    of every hierarchy is standing with a rifle at ease (1 runs, 2 walks, 3-5 aim,
    6-7 kneel). The animations (FORM BOAL, one FORM BOAN each) hold per bone a
    BORH (key count) and BORD, 13 floats a key: the rotation as a quaternion
    (x, y, z, w), its time, and two tangent quaternions. A bone's rotation is its
    parent's times its own; its offset (TLST) turns with its parent. None when
    the file has no such animation."""
    items = _iff(path.read_bytes())
    d = {}
    for p, tag, pay in items:
        if p.endswith("BOBH") and tag not in d:
            d[tag] = pay
    n = struct.unpack_from("<2i", d["BOSH"])[1]
    par = struct.unpack_from("<%di" % n, d["PLST"])
    off = [tuple(v / SCALE for v in struct.unpack_from("<3f", d["TLST"], i * 12)) for i in range(n)]
    k, rots = -1, None
    for p, tag, pay in items:
        if tag == "BOAH":
            k += 1
            if k == anim:
                rots = []
            elif k > anim:
                break
        elif tag == "BORD" and k == anim and len(pay) >= 16:
            rots.append(struct.unpack_from("<4f", pay, 0))
    if not rots or len(rots) != n:
        return None
    R, P = [None] * n, [None] * n
    for i in range(n):
        L = _qmat(rots[i])
        if par[i] < 0:
            R[i], P[i] = L, off[i]
        else:
            R[i] = _mm(R[par[i]], L)
            o = _mv(R[par[i]], off[i])
            P[i] = tuple(P[par[i]][j] + o[j] for j in range(3))
    return [(P[i], R[i]) for i in range(n)]


def place_on_bone(bone, x, y, z):
    """A vertex in its bone's own space (raw units) in the figure's: the bind
    pose's (x, y, z) offset, or a posed bone's (position, rotation)."""
    if len(bone) == 2:
        p, r = bone
        v = _mv(r, (x / SCALE, y / SCALE, z / SCALE))
        return (p[0] + v[0], p[1] + v[1], p[2] + v[2])
    return (bone[0] + x / SCALE, bone[1] + y / SCALE, bone[2] + z / SCALE)


GUN_BONE = 22


def skinned_mesh(mef, bones, feet=None):
    """(verts, tris) of a character on its bones (bind pose or posed), feet at z = 0.
    feet, a list, gets how far below the skeleton's origin the feet were."""
    ch = {}
    for tag, pay in ilff(mef, 20):
        ch.setdefault(tag, []).append(pay)
    if b"D3DR" not in ch or b"XTRV" not in ch or b"DNER" not in ch:
        return None
    dd = ch[b"D3DR"][0]
    d = struct.unpack_from("<%di" % (len(dd) // 4), dd)
    xt = ch[b"XTRV"][0]
    nv = d[5] if len(d) > 5 else 0
    if nv <= 0 or len(xt) % nv:
        return None
    st = len(xt) // nv
    verts = []
    for i in range(nv):
        x, y, z = struct.unpack_from("<3f", xt, i * st)
        b = struct.unpack_from("<H", xt, i * st + st - 2)[0]
        if b >= len(bones):
            return None
        verts.append(place_on_bone(bones[b], x, y, z))
    n = ch[b"DNER"][0]
    u = struct.unpack_from("<%dH" % (len(n) // 2), n)
    tris, pos = [], 0
    while pos + 14 <= len(u):
        cnt, vs, vc = u[pos + 6], u[pos + 9], u[pos + 10]
        idx = u[pos + 14:pos + 14 + cnt]
        if cnt % 3 or vs + vc > nv:
            return None
        for k in range(0, cnt, 3):
            tris.append((vs + idx[k], vs + idx[k + 1], vs + idx[k + 2]))
        pos += 14 + cnt
    if pos != len(u) or not tris:
        return None
    z0 = min(v[2] for v in verts)
    if feet is not None:
        feet.append(z0)
    return [(x, y, z - z0) for x, y, z in verts], tris


def grip_of(bones, z0):
    """Where a character holds its weapon (see "grips" above), or None."""
    if not bones or len(bones) <= GUN_BONE or len(bones[GUN_BONE]) != 2:
        return None
    p, r = bones[GUN_BONE]
    return [round(p[0], 4), round(p[1], 4), round(p[2] - z0, 4)] + [round(r[i][j], 4) for i in range(3) for j in range(3)]


# ---------------------------------------------------------------- pickups
def pickup_models(game):
    """{pickup id: model}: the first model a weapon script's DefineWeaponType
    names (the one seen in the world), and the model an ammo script names."""
    try:
        from studio.qvm import compile as compile_qsc
    except ImportError:
        return {}
    out = {}
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="igi_pickups_"))
    for folder, script in (("weapons", "weapon.qvm"), ("ammo", "ammo.qvm")):
        base = game / folder
        if not base.is_dir():
            continue
        for d in sorted(base.iterdir()):
            q = d / script
            if not q.exists():
                continue
            try:
                src = compile_qsc.decompile_qvm(q, tmp / (folder + "_" + d.name)).read_text(encoding="latin1")
            except Exception:
                continue
            m = re.search(r'Define(?:Weapon|Ammo)Type\((.*?)\);', src, re.S)
            if not m:
                continue
            strs = re.findall(r'"([^"]*)"', m.group(1))
            pid = next((x for x in strs if re.match(r"(WEAPON|AMMO)_ID_", x)), None)
            model = next((x for x in strs if re.fullmatch(r"\d{3}_\d{2}_\d", x)), None)
            if pid and model:
                out[pid] = model
    return out


def main(argv):
    game = pathlib.Path(argv[argv.index("--game") + 1] if "--game" in argv else str(paths.pristine()))
    models, small = {}, {}
    archives = [game / "missions" / "location0" / ("level%d" % lv) / "models" / ("level%d.res" % lv)
                for lv in range(1, 15)]
    archives.append(game / "missions" / "location0" / "common" / "models" / "location0.res")
    for p in archives:
        if not p.exists():
            continue
        for k, v in unpack_res(p).items():
            if not k.endswith(".mef"):
                continue
            if wanted(k):
                models.setdefault(k, v)
            elif small_kind(k):
                small.setdefault(k, v)
    skeletons = {}
    for f in sorted((game / "common" / "anims").glob("*.iff")):
        try:
            # standing at ease (animation 0), or the bind pose if it has none
            skeletons[f.stem] = posed(f) or skeleton(f)
        except (KeyError, struct.error):
            pass
    blob, index, src_count, grips = bytearray(), {}, {"render": 0, "collision": 0, "skinned": 0}, {}
    built = 0
    kinds = {}
    everything = dict(models)
    everything.update(small)
    for name in sorted(everything):
        mef = models.get(name) or small[name]
        kind = small_kind(name) if name in small else None
        if kind == "character":
            bones = skeletons.get(SKELETON_OF.get(name[:3], "001"))
            feet = []
            mesh, src = (skinned_mesh(mef, bones, feet) if bones else None), "skinned"
            grip = grip_of(bones, feet[0]) if mesh else None
            if grip:
                grips[name[:-4]] = grip
        else:
            mesh, src = assembled(everything, name[:-4]), "render"
            if mesh and attachments(mef):
                built += 1
        if mesh is None and kind != "character":
            mesh, src = collision_as_mesh(mef), "collision"
        if mesh is None:
            continue
        if kind:
            kinds[name[:-4]] = kind
        vs, fs, scale = compact(*mesh)
        if not fs or len(vs) > 65535:
            continue
        index[name[:-4]] = [len(blob), len(vs), len(fs), scale, src[0]]
        src_count[src] += 1
        for v in vs:
            blob += struct.pack("<3h", *[max(-32768, min(32767, c)) for c in v])
        for f in fs:
            blob += struct.pack("<3H", *f)
    if built:
        print("  %d model(s) assembled from their parts" % built)
    (OUT / "meshes.bin").write_bytes(zlib.compress(bytes(blob), 9))
    pickups = {k: v for k, v in pickup_models(game).items() if v in index}
    (OUT / "meshes.json").write_text(json.dumps({"v": 2, "models": index, "kinds": kinds, "pickups": pickups,
                                                "grips": {k: v for k, v in grips.items() if k in index}},
                                                separators=(",", ":")))
    print("%d models (%d render, %d collision, %d characters), %d pickups mapped, %.1f MB raw, %.1f MB packed" % (
        len(index), src_count["render"], src_count["collision"], src_count["skinned"], len(pickups), len(blob) / 1e6,
        (OUT / "meshes.bin").stat().st_size / 1e6))


if __name__ == "__main__":
    main(sys.argv[1:])
