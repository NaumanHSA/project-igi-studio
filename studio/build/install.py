# Installs a built mission into a game slot: the script, the models it needs,
# the height maps, the ground textures, the mission's strings, the AI scripts
# and the navigation graphs.
#
#   from studio.build import install
#   install.install_level(stage_dir, game_path, level)
#
# Every write goes through studio/protect.py, which refuses anything that is
# not a custom slot this studio created.
import json, pathlib, re, shutil

from studio import protect
from studio.build import lang
from studio.build import models as MI
from studio.qvm.compile import compile_qsc, CompileError
from studio import paths


def install_level(stage_dir, game_path, level, log=print):
    """Compile a generated plan and write it into a level slot.

    Returns (installed_objects_qvm, [installed_ai_qvm...]).
    AI scripts from the previous plan are removed via the manifest that plan left
    behind - never by id range, since the game ships AI scripts numbered 3001-3333.
    """
    stage, game = pathlib.Path(stage_dir), pathlib.Path(game_path)
    dest = game / "missions" / "location0" / ("level%d" % level)
    protect.assert_writable(dest)           # never a built-in mission
    if not dest.is_dir():
        raise CompileError("level slot not found: %s" % dest)

    obj = compile_qsc(stage / "objects.qsc")
    # Models from other levels go in before the script that uses them. If the
    # import fails nothing else has been written yet.
    needed = stage / "models_needed.json"
    if needed.exists():
        MI.import_models(dest, json.load(needed.open()), game / "missions" / "location0", log=log)
    # height maps: the base level's plus the plan's flattened ground
    hmp = stage / "terrain" / "terrain.hmp"
    if (dest / "terrain").is_dir():
        target = protect.assert_writable(dest / "terrain" / "terrain.hmp")
        if hmp.exists():
            if not target.exists() or target.read_bytes() != hmp.read_bytes():
                shutil.copyfile(hmp, target)
                log("installed terrain.hmp  (%s bytes)" % format(hmp.stat().st_size, ","))
        elif (stage / "terrain" / "terrain.hmp.remove").exists() and target.exists():
            target.unlink()
            log("removed terrain.hmp (no flattened ground any more)")
    # the ground's texture masks: the base level's plus the plan's paint
    bit = stage / "terrain" / "terrain.bit"
    if bit.exists() and (dest / "terrain").is_dir():
        target = protect.assert_writable(dest / "terrain" / "terrain.bit")
        if not target.exists() or target.read_bytes() != bit.read_bytes():
            shutil.copyfile(bit, target)
            log("installed terrain.bit  (%s bytes)" % format(bit.stat().st_size, ","))
    # the mission's own strings (objective texts, map labels), under MS<slot>_
    lang_file = stage / "language.json"
    if lang_file.exists():
        tables = json.load(lang_file.open(encoding="utf-8"))
        if int(tables.get("slot", level)) != int(level):
            log("mission strings skipped: they were built for slot %s, not %d - apply again" % (tables.get("slot"), level))
        else:
            lang.set_mission_strings(game, level, tables, log=log)
    shutil.copyfile(obj, dest / "objects.qvm")
    log("installed objects.qvm  (%s bytes)" % format(obj.stat().st_size, ","))

    ai_dst = dest / "ai"
    ai_dst.mkdir(exist_ok=True)
    manifest = ai_dst / "_mission_studio.json"
    legacy = ai_dst / "_loopworks.json"      # left by installs from before the rename
    # Scripts a previous plan installed are only stale if their soldier is gone.
    # A plan built on top of this slot inherits the previous plan's soldiers as
    # part of its base level; deleting their scripts (what this used to do) left
    # e.g. HumanAI 3019 with no script and the mission unable to load.
    in_build = {int(i) for i in re.findall(r'Task_New\((\d+), "HumanAI"',
                                           (stage / "objects.qsc").read_text(encoding="latin1"))}
    kept = set()
    for m in (manifest, legacy):
        if not m.exists():
            continue
        try:
            prev = json.load(m.open()).get("aiScripts", [])
        except Exception:
            prev = []
        for i in prev:
            if i in in_build:
                kept.add(i)
            else:
                f = ai_dst / ("%d.qvm" % i)
                if f.exists():
                    f.unlink()
    if legacy.exists():
        legacy.unlink()

    installed = []
    for s in sorted((stage / "ai").glob("*.qsc")):
        q = compile_qsc(s)
        shutil.copyfile(q, ai_dst / (s.stem + ".qvm"))
        installed.append(s.stem)
    if installed:
        log("installed %d AI script(s): %s" % (len(installed), ", ".join(installed)))
    info = {}
    src_manifest = stage / "ai" / "_manifest.json"
    if src_manifest.exists():
        info = json.load(src_manifest.open())
    info["aiScripts"] = sorted(kept | {int(s) for s in installed})
    json.dump(info, manifest.open("w"), indent=2)

    install_graphs(stage, dest, level, log)
    return dest / "objects.qvm", installed


def install_graphs(stage, dest, level, log=print):
    """Copy staged navmesh graphs into the slot, backing up the originals once.

    The staged set always matches the script that was just built (its AIGraph
    node and edge counts came from the same files), so the slot receives all of
    them together or none.
    """
    staged = sorted((pathlib.Path(stage) / "graphs").glob("graph*.dat"))
    if not staged:
        return []
    gdst = pathlib.Path(dest) / "graphs"
    protect.assert_writable(gdst)
    gdst.mkdir(exist_ok=True)
    backup = paths.backups() / "graphs" / ("level%d" % level)
    if not backup.exists():
        backup.mkdir(parents=True)
        for f in gdst.glob("graph*.dat"):
            shutil.copyfile(f, backup / f.name)
        log("backed up level %d's original graphs to %s" % (level, backup))
    changed = []
    for f in staged:
        target = gdst / f.name
        new = f.read_bytes()
        if not target.exists() or target.read_bytes() != new:
            target.write_bytes(new)
            changed.append(f.name)
    log("graphs: %d staged, %d changed%s" % (len(staged), len(changed),
        (" (" + ", ".join(changed) + ")") if changed else ""))
    return changed


def verify_level(stage_dir, game_path, level):
    """Every HumanAI in the built script needs a script file. Returns a list of problems."""
    stage, game = pathlib.Path(stage_dir), pathlib.Path(game_path)
    ai_dst = game / "missions" / "location0" / ("level%d" % level) / "ai"
    qsc = (stage / "objects.qsc").read_text(encoding="latin1")
    ids = sorted({int(m) for m in re.findall(r'Task_New\((\d+), "HumanAI"', qsc)})
    problems = []
    missing = [i for i in ids if not (ai_dst / ("%d.qvm" % i)).exists()]
    if missing:
        problems.append("missing AI scripts for HumanAI: %s"
                        % ", ".join(str(i) for i in missing))
    over = [i for i in ids if i > 4095]
    if over:
        problems.append("task ids above 4095: %s" % ", ".join(str(i) for i in over))
    return ids, problems
