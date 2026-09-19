# Checks a copy of the game, and says which build it is.
#
#   from studio.setup import verify
#   r = verify.check(path)
#   r["ok"], r["missing"], r["profile"], r["fingerprint"]
#
# Two separate questions:
#
#   Is everything the studio needs there?  Missing pieces are named, so the
#   answer is "your install has no language/USA/objectives.res", not "failed".
#
#   Which build is it?  The files the studio reads are hashed into one
#   fingerprint. A known fingerprint names the build. An unknown one is
#   reported as unknown, loudly, rather than being treated as the retail game
#   and quietly producing a mission that will not load.
import hashlib, json, pathlib

HERE = pathlib.Path(__file__).resolve().parent
PROFILES = HERE / "profiles.json"

LEVELS = range(1, 15)

#: What a mission is built from. Anything missing here stops the setup.
def needed(game):
    game = pathlib.Path(game)
    out = [game / "missions" / "location0"]
    for n in LEVELS:
        lv = game / "missions" / "location0" / ("level%d" % n)
        out += [lv / "objects.qvm", lv / "graphs", lv / "terrain"]
    out.append(game / "language")
    return out


#: What the fingerprint is taken over: small files that change when the game
#: does, and never change by themselves.
def fingerprint_files(game):
    game = pathlib.Path(game)
    out = []
    for name in ("igi.exe", "pcgame.exe"):
        p = game / name
        if p.is_file():
            out.append(p)
    for n in LEVELS:
        out.append(game / "missions" / "location0" / ("level%d" % n) / "objects.qvm")
    for res in ("objectives.res", "messages.res", "missions.res"):
        for lang in sorted((game / "language").glob("*")) if (game / "language").is_dir() else []:
            p = lang / res
            if p.is_file():
                out.append(p)
    return [p for p in out if p.is_file()]


def _hash(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fingerprint(game):
    """(short id, {relative path: hash}) over the files a mission is built from."""
    game = pathlib.Path(game)
    parts = {}
    for p in fingerprint_files(game):
        parts[str(p.relative_to(game)).replace("\\", "/").lower()] = _hash(p)
    joined = "\n".join("%s %s" % (k, parts[k]) for k in sorted(parts))
    return hashlib.sha256(joined.encode()).hexdigest()[:16], parts


def profiles():
    try:
        return json.loads(PROFILES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"profiles": []}


def known(fp):
    for p in profiles().get("profiles", []):
        if p.get("id") == fp:
            return p
    return None


def differences(game, profile_id):
    """Which files differ from a known profile, when one is recorded in full."""
    p = known(profile_id)
    if not p or not p.get("files"):
        return []
    _, parts = fingerprint(game)
    out = []
    for name, want in p["files"].items():
        got = parts.get(name)
        if got is None:
            out.append("%s is missing" % name)
        elif got != want:
            out.append("%s is not the one this build ships" % name)
    for name in parts:
        if name not in p["files"]:
            out.append("%s is not part of this build" % name)
    return out


def check(game, deep=True):
    """Everything the setup wants to know about a folder."""
    game = pathlib.Path(game)
    r = {"path": str(game), "ok": False, "missing": [], "fingerprint": None,
         "profile": None, "profileName": None, "levels": 0}
    if not game.is_dir():
        r["missing"].append("the folder does not exist")
        return r
    for p in needed(game):
        if not p.exists():
            r["missing"].append(str(p.relative_to(game)).replace("\\", "/"))
    r["levels"] = sum(1 for n in LEVELS
                      if (game / "missions" / "location0" / ("level%d" % n) / "objects.qvm").is_file())
    r["custom"] = sorted(int(d.name[5:]) for d in (game / "missions" / "location0").glob("level*")
                         if d.name[5:].isdigit() and int(d.name[5:]) >= 15)
    if r["missing"]:
        return r
    if deep:
        fp, parts = fingerprint(game)
        r["fingerprint"], r["files"] = fp, parts
        p = known(fp)
        if p:
            r["profile"], r["profileName"] = p["id"], p.get("name")
        else:
            nearest = _nearest(parts)
            if nearest:
                r["nearest"], r["differs"] = nearest[0], nearest[1]
    r["ok"] = True
    return r


def _nearest(parts):
    """The recorded build this one is closest to, and how many files differ."""
    best = None
    for p in profiles().get("profiles", []):
        files = p.get("files") or {}
        if not files:
            continue
        differ = sum(1 for k, v in files.items() if parts.get(k) != v)
        differ += sum(1 for k in parts if k not in files)
        if best is None or differ < best[1]:
            best = (p.get("name") or p.get("id"), differ)
    return best


def record(game, name, notes=""):
    """Remember this install as a known build, with every file hash."""
    fp, parts = fingerprint(game)
    data = profiles()
    data.setdefault("profiles", [])
    data["profiles"] = [p for p in data["profiles"] if p.get("id") != fp]
    data["profiles"].append({"id": fp, "name": name, "notes": notes, "files": parts})
    PROFILES.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return fp


if __name__ == "__main__":
    import sys
    from studio import paths
    target = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else paths.game()
    r = check(target)
    print("%s\n  %s" % (r["path"], "usable" if r["ok"] else "not usable"))
    for m in r["missing"]:
        print("  missing: %s" % m)
    if r["ok"]:
        print("  %d built-in missions, custom slots: %s" % (r["levels"], r["custom"] or "none"))
        print("  fingerprint %s" % r["fingerprint"])
        print("  build: %s" % (r["profileName"] or "not one we know"))
        if r.get("nearest"):
            print("  closest known build: %s (%d file(s) differ)" % (r["nearest"], r["differs"]))
