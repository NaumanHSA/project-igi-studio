# Game mission slots: where a custom mission lives in the game.
#
# The game lists every missions/location0/*/mission.qvm that calls DefineMission.
# Levels 1-14 are the built-in missions. A custom mission gets a slot of its own,
# level15 and up: a copy of its base level's folder (terrain, models, textures,
# sounds, lightmaps, graphs, AI scripts) with a mission.qvm naming it.
#
#   list_slots(game)                      -> [{"level", "custom", "marker", ...}]
#   create_slot(game, n, base_level, name, description, mission_id)
#   write_definition(game, n, base_level, name, description)
#   remove_slot(game, n)                  moves the folder to backups/slots/removed/
#   read_marker(game, n) / write_marker(game, n, data)
#
# The game only offers missions up to its config.qvm's GOActiveMission, which
# studio/build/unlock.py raises when a slot is filled and settles when one goes.
# Every write goes through protect.py.
import json, pathlib, re, shutil, sys, tempfile, time

from studio.qvm import compile as CQ
from studio import protect
from studio import paths

ROOT = pathlib.Path(__file__).resolve().parents[2]


def loc0(game):
    return pathlib.Path(game) / "missions" / "location0"


def slot_dir(game, n):
    return loc0(game) / ("level%d" % n)


def read_marker(game, n):
    f = slot_dir(game, n) / protect.MARKER
    try:
        return json.load(f.open(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_marker(game, n, data):
    d = protect.assert_writable(slot_dir(game, n))
    (d / protect.MARKER).write_text(json.dumps(data, indent=2), encoding="utf-8")


def list_slots(game):
    out = []
    for d in loc0(game).glob("level*"):
        m = re.fullmatch(r"level(\d+)", d.name)
        if not m or not (d / "mission.qvm").exists():
            continue
        n = int(m.group(1))
        dat = next(iter(sorted(d.glob("*.dat"))), None)
        out.append({"level": n, "custom": n >= protect.FIRST_CUSTOM, "marker": read_marker(game, n),
                    "base": dat.stem if dat else None})
    return sorted(out, key=lambda r: r["level"])


def free_slot(game):
    n = protect.FIRST_CUSTOM
    while slot_dir(game, n).exists():
        n += 1
    return n


def _q(s, limit):
    """A string safe inside a QSC literal."""
    s = re.sub(r'["\\\r\n\t]', " ", str(s or "")).strip()
    return s[:limit]


def write_definition(game, n, base_level, name, description):
    """mission.qvm: how the game's mission list shows this slot."""
    d = protect.assert_writable(slot_dir(game, n))
    src = ('DefineMission(%d, "%s", "%s", "", MISSION_NEXT_MISSION_UNDEFINED, "missions/location0/level%d", '
           '"missions/location0/common", "missions/location0/level%d", "location0", "level%d", "mission%d.spr");\r\n'
           % (n, _q(name, 40) or "Mission %d" % n, _q(description, 120), n, n, base_level, base_level))
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="mission-def-")) / "mission.qsc"
    tmp.write_bytes(src.encode("latin1", "replace"))
    q = CQ.compile_qsc(tmp)
    shutil.copyfile(q, d / "mission.qvm")
    shutil.rmtree(tmp.parent, ignore_errors=True)


def create_slot(game, n, base_level, name, description, mission_id, log=print):
    """Copy the base level's folder into a new slot and name it in the game's list."""
    if not (1 <= int(base_level) <= 14):
        raise ValueError("a mission's base must be a built-in level, not %r" % base_level)
    dest = protect.assert_writable(slot_dir(game, n))
    if dest.exists():
        raise FileExistsError("slot level%d already exists" % n)
    src = slot_dir(game, base_level)
    if not (src / "mission.qvm").exists():
        raise FileNotFoundError("built-in level %d not found at %s" % (base_level, src))
    shutil.copytree(src, dest)
    # restore points recorded for whatever used this slot number before belong to
    # that slot (kept whole in backups/slots/removed) - not to this fresh copy
    for kind in ("models", "graphs"):
        stale = paths.backups() / kind / ("level%d" % n)
        if stale.exists():
            stale.rename(stale.with_name("level%d-before-%s" % (n, time.strftime("%Y%m%d-%H%M%S"))))
    write_definition(game, n, base_level, name, description)
    write_marker(game, n, {"missionId": mission_id, "base": base_level, "created": int(time.time() * 1000)})
    log("created mission slot level%d from level %d" % (n, base_level))
    return dest


def remove_slot(game, n, log=print):
    """Take a slot out of the game. The folder is kept in backups, not deleted."""
    d = protect.assert_deletable_slot(slot_dir(game, n))
    keep = paths.backups() / "slots" / "removed" / ("level%d-%s" % (n, time.strftime("%Y%m%d-%H%M%S")))
    keep.parent.mkdir(parents=True, exist_ok=True)
    try:
        d.rename(keep)                          # same drive: instant
    except OSError:
        shutil.move(str(d), str(keep))
    log("removed mission slot level%d from the game (kept in %s)" % (n, keep))
    # its objective texts and map labels (MS<n>_*) go too, so a later mission in
    # this slot starts clean
    try:
        from studio.build import lang as lang_res
        if lang_res.set_mission_strings(game, n, {}, log=lambda x: None):
            log("removed mission %d's strings from the language files" % n)
    except (OSError, ValueError) as e:
        log("mission %d's strings stay in the language files: %s" % (n, e))
    # the game's mission list no longer reaches past the last mission left
    try:
        from studio.build import unlock
        unlock.settle(game, log)
    except Exception as e:
        log("the game's mission list was left as it was: %s" % e)
    return keep
