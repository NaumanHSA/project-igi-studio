# Captures what correct QVM output looks like, while the IGI ToolKit is still here.
#
#   python -m studio corpus                 capture everything (about 900 scripts)
#   python -m studio corpus --levels 1,2    just these levels
#   python -m studio corpus --check         re-hash an existing corpus, change nothing
#
# For every script the game ships we keep three things:
#
#   corpus/qvm/level<N>/...      the original .qvm, byte for byte
#   corpus/qsc/level<N>/...      the ToolKit's decompilation of it
#   corpus/golden/level<N>/...   the ToolKit's recompilation of that .qsc
#
# Our own compiler (studio/qvm/read.py, studio/qvm/write.py) is then held to it:
# the reader must turn every qvm/ file into its qsc/ file, and the writer must
# turn every qsc/ file into its golden/ file byte for byte. The corpus is
# derived from the game, so it stays out of git and is rebuilt when needed.
import hashlib, json, pathlib, shutil, sys, time

from studio.qvm import toolkit as CQ      # the capture is the ToolKit's work, not ours

ROOT = pathlib.Path(__file__).resolve().parents[2]


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def sha(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()[:16]


def game_path():
    p = arg("--game")
    if p:
        return pathlib.Path(p)
    cfg = ROOT / "config.json"
    if cfg.exists():
        c = json.loads(cfg.read_text(encoding="utf-8"))
        if c.get("pristinePath"):
            return pathlib.Path(c["pristinePath"])
    raise SystemExit("no game path: pass --game, or set pristinePath in config.json")


def levels_of(game):
    want = arg("--levels")
    want = [int(x) for x in want.split(",")] if want else None
    out = []
    for d in sorted((game / "missions" / "location0").glob("level*")):
        try:
            n = int(d.name[5:])
        except ValueError:
            continue
        if want is None or n in want:
            out.append((n, d))
    return out


def capture_level(n, src, out, stats):
    """Copy, decompile and recompile one level's scripts. Returns entries."""
    qvm_dir, qsc_dir, gold_dir = out / "qvm" / src.name, out / "qsc" / src.name, out / "golden" / src.name
    entries = {}

    # the level's own scripts, then its AI scripts, each folder decompiled in one run
    groups = [("", [f for f in sorted(src.glob("*.qvm"))])]
    if (src / "ai").is_dir():
        groups.append(("ai", sorted((src / "ai").glob("*.qvm"))))

    for sub, files in groups:
        if not files:
            continue
        qd, sd, gd = qvm_dir / sub, qsc_dir / sub, gold_dir / sub
        qd.mkdir(parents=True, exist_ok=True)
        for f in files:
            shutil.copyfile(f, qd / f.name)
        try:
            CQ.decompile_dir(qd, sd)
        except CQ.CompileError as e:
            print("   decompile failed for %s/%s: %s" % (src.name, sub or ".", str(e)[:120]))
            stats["failed"] += len(files)
            continue
        gd.mkdir(parents=True, exist_ok=True)
        for f in files:
            key = "%s/%s%s" % (src.name, (sub + "/") if sub else "", f.stem)
            qsc = sd / (f.stem + ".qsc")
            e = {"qvm": sha(qd / f.name), "qvm_bytes": (qd / f.name).stat().st_size}
            if not qsc.exists():
                print("   no decompilation for %s" % key)
                stats["failed"] += 1
                entries[key] = e
                continue
            e["qsc"], e["qsc_bytes"] = sha(qsc), qsc.stat().st_size
            if "--no-recompile" not in sys.argv:
                try:
                    built = CQ.compile_qsc(qsc)
                    shutil.copyfile(built, gd / f.name)
                    e["golden"], e["golden_bytes"] = sha(gd / f.name), (gd / f.name).stat().st_size
                    e["roundtrip"] = e["golden"] == e["qvm"]
                    stats["roundtrip"] += 1 if e["roundtrip"] else 0
                except CQ.CompileError as ex:
                    print("   recompile failed for %s: %s" % (key, str(ex)[:120]))
                    stats["failed"] += 1
            stats["ok"] += 1
            entries[key] = e
    return entries


def check(out):
    man = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    bad = 0
    for key, e in man["entries"].items():
        for kind, folder in (("qvm", "qvm"), ("qsc", "qsc"), ("golden", "golden")):
            if kind not in e:
                continue
            ext = ".qsc" if kind == "qsc" else ".qvm"
            f = out / folder / (key + ext)
            if not f.exists() or sha(f) != e[kind]:
                print("  changed or missing: %s %s" % (kind, key))
                bad += 1
    print("\n%d entries, %d problems" % (len(man["entries"]), bad))
    return 1 if bad else 0


def main():
    out = pathlib.Path(arg("--out") or (ROOT / "corpus"))
    if "--check" in sys.argv:
        return check(out)
    if not CQ.available():
        raise SystemExit("gconv/dconv not found; the IGI ToolKit must be installed for a capture")
    game = game_path()
    levels = levels_of(game)
    if not levels:
        raise SystemExit("no level folders under %s" % (game / "missions" / "location0"))
    print("game   %s" % game)
    print("corpus %s" % out)
    print("levels %s\n" % ", ".join(str(n) for n, _ in levels))

    stats = {"ok": 0, "failed": 0, "roundtrip": 0}
    entries, t0 = {}, time.time()
    for n, src in levels:
        t = time.time()
        got = capture_level(n, src, out, stats)
        entries.update(got)
        print("level %-2d %4d scripts  %5.1fs" % (n, len(got), time.time() - t))

    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps({
        "game": str(game), "created": int(time.time()), "tool": "IGI ToolKit gconv/dconv",
        "entries": entries,
    }, indent=1), encoding="utf-8")
    print("\n%d captured, %d failed, %d recompiled byte for byte, %.0fs"
          % (stats["ok"], stats["failed"], stats["roundtrip"], time.time() - t0))
    print("manifest: %s" % (out / "manifest.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
