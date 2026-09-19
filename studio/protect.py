# The one gate every write into a game folder goes through.
#
# Built-in missions are never written: not the original install, not levels
# 1-14 of the working copy, not the folders every mission shares (common,
# menusystem, ...). Only a custom mission slot - missions/location0/level<N>
# with N >= 15 - can be written, and only a slot Project IGI Studio created (it
# carries our marker) can be deleted. One exception: a mission's own strings
# (objective texts, map labels) are added to the working game's
# language/<lang>/objectives.res and messages.res under the mission's MS<slot>_
# prefix; studio/build/lang.py touches no other key and backs the files up first.
#
#   import protect
#   protect.assert_writable(path)          raises ProtectedPath if it is not a custom slot
#   protect.assert_deletable_slot(dir)     ... and it must be a whole slot we made
#   protect.assert_language_file(path)     objectives.res / messages.res of a working game
import json, os, pathlib, re
from studio import paths

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIRST_CUSTOM = 15               # levels 1-14 are the game's own missions
MARKER = "_mission_studio.json" # written into every slot the studio creates;
                                # the name is kept from the old product name so that
                                # slots installed by earlier versions are still ours


class ProtectedPath(PermissionError):
    pass


def pristine_roots():
    """Everything that is read and never written.

    Our own reference copy of the levels, whatever the settings still name as
    an original, and anything else the person asked us to keep off. The
    working game is never in this list, or nothing could ever be applied.
    """
    cfg = paths.config()
    roots = [str(paths.snapshot()), cfg.get("pristinePath")]
    roots += list(cfg.get("protectedPaths") or [])
    try:
        working = paths.game().resolve() if paths.game_set() else None
    except OSError:
        working = None
    out, seen = [], set()
    for r in roots:
        if not r or not str(r).strip():
            continue                      # an empty setting is not "the whole disk"
        try:
            r = pathlib.Path(os.path.expandvars(str(r))).resolve()
        except OSError:
            continue
        if r in seen or r == working:
            continue
        seen.add(r)
        out.append(r)
    return out


def slot_of(path):
    """(level number, slot folder) when path is inside missions/location0/level<N>, else None."""
    p = pathlib.Path(path).resolve()
    parts = [x.lower() for x in p.parts]
    for i in range(len(parts) - 2):
        if parts[i] == "missions" and parts[i + 1] == "location0":
            m = re.fullmatch(r"level(\d+)", parts[i + 2])
            if m:
                return int(m.group(1)), pathlib.Path(*p.parts[:i + 3])
    return None


def assert_writable(path, what="write to"):
    p = pathlib.Path(path).resolve()
    for root in pristine_roots():
        if p == root or root in p.parents:
            raise ProtectedPath("refusing to %s %s: the studio only ever reads that" % (what, p))
    # One game is written to: the one the studio is connected to. A custom slot
    # anywhere else on the disk is still somebody's game, not ours.
    try:
        game = paths.game().resolve() if paths.game_set() else None
    except OSError:
        game = None
    if game is not None and not (p == game or game in p.parents):
        raise ProtectedPath("refusing to %s %s: the studio writes to %s and nowhere else"
                            % (what, p, game))
    s = slot_of(p)
    if s is None:
        raise ProtectedPath("refusing to %s %s: only a custom mission slot "
                            "(missions/location0/level%d or higher) may be changed" % (what, p, FIRST_CUSTOM))
    if s[0] < FIRST_CUSTOM:
        raise ProtectedPath("refusing to %s %s: level %d is a built-in mission" % (what, p, s[0]))
    return p


def assert_language_file(path):
    """The one exception outside mission slots: a working game's objectives.res or
    messages.res, which a mission's own strings are added to under its MS<slot>_
    prefix (studio/build/lang.py - it never changes another key). The original
    install is still refused."""
    p = pathlib.Path(path).resolve()
    for root in pristine_roots():
        if p == root or root in p.parents:
            raise ProtectedPath("refusing to write %s: that is the original game install" % p)
    if (p.name.lower() not in ("objectives.res", "messages.res") or p.parent.parent.name.lower() != "language"
            or not (p.parent.parent.parent / "missions" / "location0").is_dir()):
        raise ProtectedPath("refusing to write %s: only a game's language/<lang>/objectives.res "
                            "or messages.res takes mission strings" % p)
    return p


def assert_restore(target, source):
    """The only way a built-in mission may be written: putting it back.

    A repair copies a file from an untouched install over the same file in the
    working game. That can only ever make the game more like the original, so
    it is allowed where an ordinary write is refused. The rules: the source is
    inside an install we protect, the target is inside the working game, the
    two sit at the same place in the tree, and the target is a built-in
    mission's file. Anything else raises."""
    src, dst = pathlib.Path(source).resolve(), pathlib.Path(target).resolve()
    if not src.is_file():
        raise ProtectedPath("refusing to restore %s: there is nothing to restore it from" % dst)
    root = next((r for r in pristine_roots() if r == src or r in src.parents), None)
    if root is None:
        raise ProtectedPath("refusing to restore %s: %s is not in an untouched install" % (dst, src))
    game = paths.game().resolve()
    if not (dst == game or game in dst.parents):
        raise ProtectedPath("refusing to restore %s: that is not in the working game" % dst)
    if src.relative_to(root) != dst.relative_to(game):
        raise ProtectedPath("refusing to restore %s: it would come from %s, a different file"
                            % (dst, src.relative_to(root)))
    s = slot_of(dst)
    if s is None or s[0] >= FIRST_CUSTOM:
        raise ProtectedPath("refusing to restore %s: only a built-in mission is put back this way" % dst)
    return dst


def assert_deletable_slot(slot_dir):
    p = assert_writable(slot_dir, "delete")
    n, whole = slot_of(p)
    if whole != p:
        raise ProtectedPath("refusing to delete %s: only a whole mission slot can be deleted" % p)
    if not (p / MARKER).exists():
        raise ProtectedPath("refusing to delete %s: Project IGI Studio did not create it" % p)
    return p


if __name__ == "__main__":
    # self-test: every built-in place is refused, a custom slot is allowed
    game = paths.game()
    loc0 = game / "missions" / "location0"
    refused = [loc0 / ("level%d" % n) / "objects.qvm" for n in range(1, 15)]
    refused += [loc0 / "common" / "x", game / "menusystem" / "missionsprites.res", game / "IGI.exe",
                game / "language" / "USA" / "missions.res",
                # our own reference copy: read, never written
                paths.snapshot() / "missions" / "location0" / "level15" / "objects.qvm",
                # a custom slot in somebody else's copy of the game is still not ours
                pathlib.Path("D:/some-other-install/missions/location0/level15/objects.qvm"),
                pathlib.Path.home() / "missions" / "location0" / "level20" / "objects.qvm",
                loc0 / "level1x" / "objects.qvm", loc0]
    bad = 0
    for p in refused:
        try:
            assert_writable(p)
            print("NOT REFUSED:", p)
            bad += 1
        except ProtectedPath:
            pass
    for p in (loc0 / "level15" / "objects.qvm", loc0 / "level16" / "graphs" / "graph1.dat"):
        try:
            assert_writable(p)
        except ProtectedPath as e:
            print("WRONGLY REFUSED:", p, e)
            bad += 1
    for p in (game / "language" / "USA" / "objectives.res", game / "language" / "english" / "messages.res"):
        try:
            assert_language_file(p)
        except ProtectedPath as e:
            print("WRONGLY REFUSED:", p, e)
            bad += 1
    for p in (paths.pristine() / "language" / "USA" / "objectives.res", game / "language" / "USA" / "missions.res",
              game / "IGI.exe"):
        try:
            assert_language_file(p)
            print("NOT REFUSED:", p)
            bad += 1
        except ProtectedPath:
            pass
    try:
        assert_deletable_slot(loc0 / "level1")
        print("NOT REFUSED: delete level1")
        bad += 1
    except ProtectedPath:
        pass
    print("protect self-test: %d of %d checks passed" % (len(refused) + 8 - bad, len(refused) + 8))
    raise SystemExit(1 if bad else 0)
