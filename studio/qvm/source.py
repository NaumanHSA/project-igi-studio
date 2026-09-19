# The game's own levels, as source, from the person's own copy of the game.
#
#   from studio.qvm import source
#   src = source.level_qsc(3)        missions/location0/level3/objects.qsc
#   ai  = source.level_ai(3)         that level's AI scripts, as a folder
#
# Everything the studio reads about a level comes through here, so the editor
# and the builder always see the same game: the one on this machine. It used
# to come from a script library that a third party toolkit installs, which on
# this machine turned out to be a different build of the game (two soldiers in
# level 3 wear other models there), and that is exactly the kind of quiet
# mismatch this avoids.
#
# A built-in level never changes, so its decompilation is kept. A custom slot
# changes with every Apply, so it is read afresh.
import pathlib

from studio import paths
from studio.qvm import compile as CQ

FIRST_CUSTOM = 15


def _sources(game=None, level=1):
    """Where to look for a level, in order of how trustworthy it is.

    A built-in level comes from our reference copy first: that is the game as
    it was when it was connected, and it is there even when the game is not. A
    custom slot is not in the reference, because the studio writes it, so it
    comes from the game.
    """
    if level < FIRST_CUSTOM:
        order = (paths.snapshot(), paths.setting("pristinePath"), game, paths.game())
    else:
        order = (game, paths.game())
    out = []
    for where in order:
        if where and str(where):
            p = pathlib.Path(where)
            if p not in out:
                out.append(p)
    return out


def level_qvm(level, game=None):
    """The compiled level script in the first copy of the game that has it."""
    for where in _sources(game, level):
        p = where / "missions" / "location0" / ("level%d" % level) / "objects.qvm"
        if p.is_file():
            return p
    return None


def level_qsc(level, game=None, cache=True):
    """The level as source, decompiled from the game if it is not cached yet."""
    out = paths.decompiled() / ("level%d" % level) / "objects.qsc"
    if cache and out.exists() and level < FIRST_CUSTOM:
        return out
    qvm = level_qvm(level, game)
    if qvm is None:
        raise FileNotFoundError(
            "level %d is not in any copy of the game the studio knows about.\n"
            "Point it at yours:  python -m studio setup --game <folder>" % level)
    return CQ.decompile_qvm(qvm, out.parent)


def level_ai(level, game=None, cache=True):
    """The level's AI scripts as source, in a folder."""
    out = paths.decompiled() / ("level%d" % level) / "ai"
    if cache and out.is_dir() and any(out.glob("*.qsc")) and level < FIRST_CUSTOM:
        return out
    for where in _sources(game, level):
        d = where / "missions" / "location0" / ("level%d" % level) / "ai"
        if d.is_dir() and any(d.glob("*.qvm")):
            CQ.decompile_dir(d, out)
            return out
    return out


def have(level, game=None):
    return level_qvm(level, game) is not None


if __name__ == "__main__":
    import sys
    lv = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    p = level_qsc(lv)
    print("level %d: %s (%d bytes)" % (lv, p, p.stat().st_size))
    a = level_ai(lv)
    print("AI scripts: %d in %s" % (len(list(a.glob("*.qsc"))), a))
