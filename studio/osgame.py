# Running the game, on whichever system the studio is on. One place for it, so no
# other module has to know that Windows runs IGI.exe itself and a Mac runs it
# through Wine.
#
#   from studio import osgame
#   osgame.game_running()               is any copy of IGI.exe running?
#   osgame.start(exe, ["Window"])       start it, detached from the studio
#   osgame.HIDDEN                       creationflags for a helper with no window
#   osgame.wine()                       the Wine program on a Mac, or None
#
# On a Mac the game folder lives inside a Wine prefix (a CrossOver bottle, a
# Whisky bottle or a plain ~/.wine): somewhere under its drive_c. The prefix is
# found from the game's own path, so the game starts in the bottle it was
# installed in.
import os, pathlib, shutil, subprocess, sys

WINDOWS = os.name == "nt"
MAC = sys.platform == "darwin"

#: CREATE_NO_WINDOW: a helper process with no console window (Windows only)
HIDDEN = 0x08000000 if WINDOWS else 0
_DETACHED = 0x00000008 | 0x00000200          # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

# Where Wine is when it is not on PATH: the apps people install it with.
WINE_APPS = [
    "/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/bin/wine",
    "/Applications/Wine Stable.app/Contents/Resources/wine/bin/wine",
    "/Applications/Wine Staging.app/Contents/Resources/wine/bin/wine",
    "/Applications/Wine Devel.app/Contents/Resources/wine/bin/wine",
    os.path.expanduser("~/Library/Application Support/com.isaacmarovitz.Whisky/Libraries/Wine/bin/wine64"),
]


def wine():
    """The Wine program to run the game with, or None. IGISTUDIO_WINE, or the
    settings' winePath, win over looking for it."""
    from studio import paths
    named = os.environ.get("IGISTUDIO_WINE") or paths.setting("winePath")
    if named:
        return str(named) if os.path.isfile(str(named)) else None
    for name in ("wine", "wine64"):
        found = shutil.which(name)
        if found:
            return found
    return next((p for p in WINE_APPS if os.path.isfile(p)), None)


def wine_prefix(folder):
    """The Wine prefix a folder is in: the folder that holds its drive_c."""
    p = pathlib.Path(str(folder)).resolve()
    for parent in [p] + list(p.parents):
        if parent.name.lower() == "drive_c":
            return parent.parent
    return None


def command(exe, args=()):
    """How to start this Windows program here: (argv, env or None)."""
    if WINDOWS:
        return [str(exe)] + list(args), None
    w = wine()
    if not w:
        raise OSError("Wine was not found. Install CrossOver, Wine (brew install --cask wine-stable) or Whisky, "
                      "or name its wine program as winePath in the settings.")
    env = dict(os.environ)
    prefix = wine_prefix(pathlib.Path(exe).parent)
    if prefix and "CrossOver.app" in w:
        # CrossOver keeps one bottle per folder under Bottles/ and picks it by name
        return [w, "--bottle", prefix.name, str(exe)] + list(args), env
    if prefix:
        env["WINEPREFIX"] = str(prefix)
    return [w, str(exe)] + list(args), env


def start(exe, args=(), cwd=None):
    """Start the game (or any Windows program), detached from the studio."""
    argv, env = command(exe, args)
    cwd = str(cwd or pathlib.Path(exe).parent)
    if WINDOWS:
        return subprocess.Popen(argv, cwd=cwd, creationflags=_DETACHED)
    return subprocess.Popen(argv, cwd=cwd, env=env, start_new_session=True,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _commands():
    """The command lines of every process (not Windows)."""
    try:
        out = subprocess.run(["ps", "-axww", "-o", "command="], capture_output=True, text=True).stdout
    except OSError:
        return []
    return out.splitlines()


def running(name):
    """Is a program with this file name running? Under Wine the Windows program's
    name is in the command line of the process that runs it."""
    if WINDOWS:
        try:
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq %s" % name, "/NH"], capture_output=True,
                                 text=True, creationflags=HIDDEN).stdout
            return name.lower() in out.lower()
        except OSError:
            return False
    low = name.lower()
    return any(low in line.lower() for line in _commands())


def game_running():
    return running("IGI.exe")


def mac_app_running(bundle):
    """Is this Mac app (e.g. "Claude.app") open?"""
    want = "/%s/contents/macos/" % bundle.lower()
    return MAC and any(want in line.lower() for line in _commands())
