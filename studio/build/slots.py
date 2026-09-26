# Game mission slots: where a custom mission lives in the game.
#
# The game loads every missions/location0/*/mission.qvm (a DefineMission each),
# but its menu lists them by following each one's "next mission" from mission 1
# (IGI.exe's Config_FillMissionSelectionBox and Config_FillMissionPictureBox),
# stopping at config.qvm's GOActiveMission. So a mission the chain does not reach
# is never listed, and a link to a mission that is not there crashes the main
# menu (the picture box walks the whole chain and does not check).
# Levels 1-14 are the built-in missions. A custom mission gets a slot of its own,
# level15 and up: a copy of its base level's folder (terrain, models, textures,
# sounds, lightmaps, graphs, AI scripts) with a mission.qvm naming it.
#
#   list_slots(game)                      -> [{"level", "custom", "marker", ...}]
#   free_slot(game)                       the number after the last mission in the game
#   create_slot(game, n, base_level, name, description, mission_id)
#   write_definition(game, n, base_level, name, description)
#   read_definition(game, n)              -> {"name", "description", "next", "base"} as the game lists it
#   relink(game)                          each of our missions leads on to the next one in the game,
#                                         and the campaign's last to the first of them (link_campaign)
#   move_slots(game, {old: new})          renumber missions the studio made, and all that carries the number
#   remove_slot(game, n)                  moves the folder to backups/slots/removed/
#   discard_slot(game, n)                 deletes a slot made a moment ago that never got its mission
#   read_marker(game, n) / write_marker(game, n, data)
#
# DefineMission's fifth argument is that link: the mission finishing this one
# leads to. The game ships level 14 leading to none. The studio links the
# campaign's last mission to the first custom one, each of ours to the next
# mission in the game, and the last to none; with no custom mission left, level
# 14 is put back as it shipped.
# The game only offers missions up to its config.qvm's GOActiveMission, which
# studio/build/unlock.py raises when a slot is filled and settles when one goes.
# Every write goes through protect.py.
import json, pathlib, re, shutil, sys, tempfile, time

from studio.qvm import compile as CQ
from studio.qvm import read as QR
from studio.qvm import write as QW
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
    """A new mission goes after the last one in the game, never into a gap
    before it: the game plays them in number order."""
    top = max((s["level"] for s in list_slots(game) if s["custom"]), default=protect.FIRST_CUSTOM - 1)
    n = top + 1
    while slot_dir(game, n).exists():           # a folder with no mission in it is still in the way
        n += 1
    return n


def next_after(game, n):
    """The mission that follows slot n in the game, or None when n is the last."""
    return min((s["level"] for s in list_slots(game) if s["level"] > n), default=None)


def _q(s, limit):
    """A string safe inside a QSC literal."""
    s = re.sub(r'["\\\r\n\t]', " ", str(s or "")).strip()
    return s[:limit]


R_DEFINE = re.compile(r'DefineMission\((\d+),\s*"((?:[^"\\]|\\.)*)",\s*"((?:[^"\\]|\\.)*)",\s*"[^"]*",\s*'
                      r'([A-Z_]+|\d+),.*?"level(\d+)",\s*"mission\d+\.spr"\)', re.S)


def read_definition(game, n):
    """How the game lists slot n, read from its mission.qvm: {"number", "name",
    "description", "next" (a mission number or None), "base"}, or None."""
    f = slot_dir(game, n) / "mission.qvm"
    try:
        m = R_DEFINE.search(QR.decompile(QR.parse(f)))
    except (OSError, QR.QVMError):
        return None
    if not m:
        return None
    nxt = m.group(4)
    return {"number": int(m.group(1)), "name": m.group(2), "description": m.group(3),
            "next": int(nxt) if nxt.isdigit() else None, "base": int(m.group(5))}


def write_definition(game, n, base_level, name, description):
    """mission.qvm: how the game's mission list shows this slot, and the mission
    finishing it leads on to (the next one in the game, if there is one). Its
    picture is the one the mission has of its own in the game's list
    (covers.py, mission<n>.spr), else its base level's: the list shows the
    picture DefineMission names, and a slot with a picture of its own showed its
    base mission's, as that is the one it named."""
    d = protect.assert_writable(slot_dir(game, n))
    nxt = next_after(game, n)
    from studio.build import covers         # it reads the game's menu files
    pic = n if covers.has_cover(game, n) else base_level
    src = ('DefineMission(%d, "%s", "%s", "", %s, "missions/location0/level%d", '
           '"missions/location0/common", "missions/location0/level%d", "location0", "level%d", "mission%d.spr");\r\n'
           % (n, _q(name, 40) or "Mission %d" % n, _q(description, 120),
              nxt if nxt is not None else "MISSION_NEXT_MISSION_UNDEFINED", n, n, base_level, pic))
    data = QW.compile_text(src.encode("latin1", "replace").decode("latin1"))
    if not (d / "mission.qvm").exists() or (d / "mission.qvm").read_bytes() != data:
        (d / "mission.qvm").write_bytes(data)


def relink(game, log=print):
    """Each mission the studio made leads on to the next one in the game. Run
    after a slot is added, taken out or moved. Slots it did not make are left
    as they are."""
    changed = []
    for s in list_slots(game):
        if not s["custom"] or not s["marker"]:
            continue
        d = read_definition(game, s["level"])
        if d is None or d["next"] == next_after(game, s["level"]):
            continue
        write_definition(game, s["level"], d["base"], d["name"], d["description"])
        changed.append(s["level"])
    if changed:
        log("%s %s now lead%s on to the next one in the game"
            % ("missions" if len(changed) > 1 else "mission", ", ".join(map(str, changed)), "" if len(changed) > 1 else "s"))
    link_campaign(game, log)
    return changed


R_NEXT = re.compile(r'(DefineMission\(\s*\d+\s*,\s*"(?:[^"\\]|\\.)*"\s*,\s*"(?:[^"\\]|\\.)*"\s*,\s*"[^"]*"\s*,\s*)'
                    r'([A-Z_]+|-?\d+)')


def campaign_last(game):
    """The built-in mission the campaign ends on: the links from mission 1,
    followed while they stay among the game's own (level 14, as it ships)."""
    n, seen = 1, set()
    while True:
        d = read_definition(game, n)
        if d is None:
            return None
        nxt = d["next"]
        if (nxt is None or nxt >= protect.FIRST_CUSTOM or nxt in seen
                or not (slot_dir(game, nxt) / "mission.qvm").is_file()):
            return n
        seen.add(n)
        n = nxt


def link_campaign(game, log=print):
    """The campaign's last mission leads on to the first custom mission, so the
    game's list reaches them all - or, with none left, to none, as it shipped.
    Only that link is changed, and the rest of the file is checked to come out
    the same. True when it was changed."""
    last = campaign_last(game)
    if last is None:
        return False
    first = min((s["level"] for s in list_slots(game) if s["custom"]), default=None)
    f = slot_dir(game, last) / "mission.qvm"
    text = QR.decompile(QR.parse(f))
    m = R_NEXT.search(text)
    want = str(first) if first is not None else "MISSION_NEXT_MISSION_UNDEFINED"
    if not m or m.group(2) == want:
        return False
    fixed = text[:m.start(2)] + want + text[m.end(2):]
    data = QW.compile_text(fixed)
    if QR.decompile(QR.parse(data)) != fixed:
        raise RuntimeError("mission %d's definition did not rebuild cleanly, so it was left as it was" % last)
    protect.assert_mission_link(f)
    backup = paths.backups() / "builtin" / ("level%d" % last) / "mission.qvm"
    if not backup.exists():
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(f, backup)
    f.write_bytes(data)
    log("mission %d, the game's last own mission, now leads on to %s"
        % (last, "mission %d" % first if first is not None else "none, as it shipped"))
    return True


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
    relink(game, log)
    return dest


def discard_slot(game, n, log=print):
    """Take out a slot made a moment ago whose mission never got into it (its
    Apply failed). It holds nothing but a copy of its base level, so it is
    deleted, not kept: left in, the game would list the base level under the
    mission's name."""
    d = protect.assert_deletable_slot(slot_dir(game, n))
    shutil.rmtree(d)
    for kind in ("models", "graphs"):           # restore points the failed Apply may have begun
        shutil.rmtree(paths.backups() / kind / ("level%d" % n), ignore_errors=True)
    from studio.build import lang
    lang.set_mission_strings(game, n, {}, log=lambda x: None)
    _drop_picture(game, n, log)
    log("took the new slot level%d out of the game again: nothing of this mission is in it" % n)
    relink(game, log)
    try:
        from studio.build import unlock
        unlock.settle(game, log)
    except Exception as e:
        log("the game's mission list was left as it was: %s" % e)


# ---------------------------------------------------------------- order
# A mission's number is carried by more than its folder: the definition names
# it (DefineMission's number and its paths), its own strings are MS<n>_* in its
# script and in the language files, its marker records it, and its restore
# points in backups are kept under level<n>. Moving a mission moves all of it.
def _mission_strings(game, n):
    """{file: {key: text}} of slot n's own strings, as the first language folder has them."""
    from studio.build import lang
    prefix, out = "MS%d_" % n, {}
    for lg in sorted((pathlib.Path(game) / "language").iterdir()):
        for name in lang.FILES:
            p = lg / name
            if name in out or not p.is_file():
                continue
            got = {k: v for k, v in lang.strings(p).items() if k.startswith(prefix)}
            if got:
                out[name] = got
    return out


def _renumber_scripts(d, old, new):
    """MS<old>_ becomes MS<new>_ in the slot's scripts. Only a script that names
    one is rebuilt."""
    was = ("MS%d_" % old).encode()
    for f in [d / "objects.qvm"] + sorted((d / "ai").glob("*.qvm")):
        if not f.is_file() or was not in f.read_bytes():
            continue
        text = QR.decompile(QR.parse(f))
        fixed = text.replace('"MS%d_' % old, '"MS%d_' % new)
        if fixed != text:
            protect.assert_writable(f)
            f.write_bytes(QW.compile_text(fixed))


def _drop_picture(game, n, log):
    """A mission leaving the game takes its picture out of the game's list."""
    try:
        from studio.build import covers
        covers.set_cover(game, n, None, log=log)
    except (OSError, ValueError, RuntimeError, protect.ProtectedPath) as e:
        log("mission %d's picture stays in the game's list: %s" % (n, e))


def mine(game, n):
    """Did the studio make slot n (it carries our marker)?"""
    return (slot_dir(game, n) / protect.MARKER).is_file()


def move_slots(game, moves, log=print):
    """Renumber missions the studio made: moves {old: new}. Nothing is written
    until every move has been checked, and if a folder cannot be moved the ones
    already moved are put back."""
    moves = {int(a): int(b) for a, b in moves.items() if int(a) != int(b)}
    if not moves:
        return {}
    for old, new in moves.items():
        if not mine(game, old) or not (slot_dir(game, old) / "mission.qvm").is_file():
            raise ValueError("mission %d was not made by the studio, so it stays where it is" % old)
        if new < protect.FIRST_CUSTOM:
            raise ValueError("mission %d would become %d, a built-in mission" % (old, new))
        if slot_dir(game, new).exists() and new not in moves:
            raise ValueError("mission %d cannot become %d: that number is taken" % (old, new))
    if len(set(moves.values())) != len(moves):
        raise ValueError("two missions cannot take the same number")
    strings = {old: _mission_strings(game, old) for old in moves}

    # the folders, and their restore points, by way of numbers nothing uses
    done = []

    def rename(a, b):
        # a folder written a moment ago can still be held by the virus scanner
        # or the search indexer, for a second or two
        for wait in (0.2, 0.4, 0.8, 1.6, 3.2, 0):
            try:
                a.rename(b)
                break
            except PermissionError:
                if not wait:
                    raise
                time.sleep(wait)
        done.append((a, b))

    parking = {}
    try:
        for old in moves:
            t = 90000 + old
            while slot_dir(game, t).exists():
                t += 1
            parking[old] = t
            rename(protect.assert_deletable_slot(slot_dir(game, old)), protect.assert_writable(slot_dir(game, t)))
            for kind in ("models", "graphs"):
                b = paths.backups() / kind / ("level%d" % old)
                if b.exists():
                    rename(b, b.with_name("level%d" % t))
        for old, new in moves.items():
            t = parking[old]
            rename(protect.assert_writable(slot_dir(game, t)), protect.assert_writable(slot_dir(game, new)))
            for kind in ("models", "graphs"):
                b = paths.backups() / kind / ("level%d" % t)
                if b.exists():
                    rename(b, b.with_name("level%d" % new))
    except OSError as e:
        for a, b in reversed(done):
            try:
                b.rename(a)
            except OSError:
                pass
        raise RuntimeError("the missions could not be moved (%s), so they were left as they were. "
                           "Is the game, or a window onto its folder, still open?" % e)

    # what inside each one names its number
    from studio.build import lang
    for old, new in moves.items():
        d = slot_dir(game, new)
        _renumber_scripts(d, old, new)
        mk = read_marker(game, new) or {}
        for rec in (mk, mk.get("mission") or {}):
            if isinstance(rec.get("installed"), dict):
                rec["installed"]["slot"] = new
        if isinstance(mk.get("mission"), dict):
            mk["mission"]["slot"] = new
        write_marker(game, new, mk)
    for old in moves:
        lang.set_mission_strings(game, old, {}, log=lambda x: None)
    for old, new in moves.items():
        tables = {name: {"MS%d_" % new + k[len("MS%d_" % old):]: v for k, v in table.items()}
                  for name, table in strings[old].items()}
        if tables:
            lang.set_mission_strings(game, new, tables, log=lambda x: None)
    # the pictures in the game's mission list, under their new numbers
    try:
        from studio.build import covers
        covers.move(game, moves, log=log)
    except (OSError, ValueError, RuntimeError, protect.ProtectedPath) as e:
        log("the missions' pictures stay under their old numbers: %s" % e)
    # definitions last, once every number is where it is going
    for old, new in moves.items():
        d = read_definition(game, new)
        if d:
            write_definition(game, new, d["base"], d["name"], d["description"])
        log("mission %d is now mission %d" % (old, new))
    relink(game, log)
    try:
        from studio.build import unlock
        unlock.settle(game, log)
        unlock.reach_all(game, log)
    except Exception as e:
        log("the game's mission list was left as it was: %s" % e)
    return moves


def order_slots(game, order, log=print):
    """Put the studio's missions in the game in this order (their slot numbers,
    first to last). They take the numbers from 15 up, in turn; a mission the
    studio did not make keeps its number and is stepped around."""
    ours = [s["level"] for s in list_slots(game) if s["custom"] and mine(game, s["level"])]
    order = [int(n) for n in order]
    if sorted(order) != sorted(ours):
        raise ValueError("the order must name each of the studio's missions in the game once")
    pinned = {int(m.group(1)) for d in loc0(game).glob("level*")
              for m in [re.fullmatch(r"level(\d+)", d.name)] if m and int(m.group(1)) not in ours}
    numbers, n = [], protect.FIRST_CUSTOM
    while len(numbers) < len(order):
        if n not in pinned:
            numbers.append(n)
        n += 1
    return move_slots(game, dict(zip(order, numbers)), log)


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
    _drop_picture(game, n, log)
    relink(game, log)
    # the game's mission list no longer reaches past the last mission left
    try:
        from studio.build import unlock
        unlock.settle(game, log)
    except Exception as e:
        log("the game's mission list was left as it was: %s" % e)
    return keep
