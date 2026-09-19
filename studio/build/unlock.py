# Which missions the game offers. The game's own settings, config.qvm in its
# folder, say how far the player has come: GOActiveMission(N) lets the mission
# list offer missions 1 to N. The game as it shipped says 1, so on a fresh
# install a mission built into slot 15 is installed and never offered.
#
#   from studio.build import unlock
#   unlock.reach(game, 15)      N is at least 15 now, never lowered
#   unlock.settle(game)         N is no further than the last mission there is
#   unlock.active(game)         N, or None
#
# Applying a mission raises N to its slot; nothing the player has reached is
# ever taken away. Taking a slot out lowers N only when it points past the last
# mission left, to that mission. The file is rebuilt with our own compiler,
# which rebuilds the game's config.qvm byte for byte, and is backed up first.
# The game keeps its settings in memory and writes them back when it closes, so
# the studio does this again just before it starts the game.
import pathlib, re, shutil, subprocess, tempfile

from studio import paths, protect
from studio.qvm import compile as CQ

R_ACTIVE = re.compile(r"GOActiveMission\((\d+)\);")


def _config(game):
    return pathlib.Path(game) / "config.qvm"


def _read(game):
    """(source, N) of the game's config.qvm, or (None, None)."""
    q = _config(game)
    if not q.exists():
        return None, None
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="igi-config-"))
    try:
        src = CQ.decompile_qvm(q, tmp).read_text(encoding="latin1")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    m = R_ACTIVE.search(src)
    return src, (int(m.group(1)) if m else None)


def active(game):
    try:
        return _read(game)[1]
    except Exception:
        return None


def running():
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq IGI.exe", "/NH"], capture_output=True, text=True,
                             creationflags=0x08000000).stdout
        return "igi.exe" in out.lower()
    except OSError:
        return False


def _write(game, src, n, log):
    q = protect.assert_config_file(_config(game))
    backup = paths.backups() / "config" / "config.qvm"
    if not backup.exists():
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(q, backup)
        log("backed up the game's settings (config.qvm) to %s" % backup)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="igi-config-"))
    try:
        edited = tmp / "config.qsc"
        edited.write_bytes(R_ACTIVE.sub("GOActiveMission(%d);" % n, src, count=1).encode("latin1"))
        built = CQ.compile_qsc(edited)
        # the one line changed, and nothing else
        check = CQ.decompile_qvm(pathlib.Path(built), tmp / "check").read_text(encoding="latin1")
        before, after = src.splitlines(), check.splitlines()
        changed = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
        if len(before) != len(after) or len(changed) != 1 or not R_ACTIVE.fullmatch(after[changed[0]].strip()):
            raise RuntimeError("the game's settings did not rebuild cleanly, so they were left as they were")
        shutil.copyfile(built, q)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def reach(game, slot, log=print):
    """Let the game's mission list offer missions up to `slot`. True if it changed."""
    src, n = _read(game)
    if src is None or n is None:
        log("the game's settings (config.qvm) were not found, so mission %d may not be in its list" % slot)
        return False
    if n >= slot:
        return False
    _write(game, src, slot, log)
    log("the game's mission list now goes up to mission %d (it went up to %d)" % (slot, n))
    if running():
        log("the game is running: it writes its own settings back when it closes, and the studio "
            "sets this again the next time it starts the game")
    return True


def reach_all(game, log=print):
    """Every custom mission in the game, offered."""
    from studio.build import slots as SL
    top = max((s["level"] for s in SL.list_slots(game) if s["custom"]), default=0)
    return reach(game, top, log) if top else False


def settle(game, log=print):
    """After a slot is taken out: N no further than the last mission left."""
    from studio.build import slots as SL
    src, n = _read(game)
    if src is None or n is None:
        return False
    last = max((s["level"] for s in SL.list_slots(game)), default=1)
    if n <= last:
        return False
    _write(game, src, last, log)
    log("the game's mission list now ends at mission %d, the last one left" % last)
    return True
