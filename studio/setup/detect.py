# Finds copies of Project I.G.I. on this machine.
#
#   from studio.setup import detect
#   for hit in detect.find():
#       print(hit["path"], hit["where"])
#
# We look where installers put the game, not everywhere: the registry's
# uninstall entries, GOG's and Steam's own records, and the handful of folders
# people install games into. A folder counts as the game when it holds the
# level data and the executable, which is what verify.py then checks properly.
import os, pathlib, re, sys

EXE = ("igi.exe", "pcgame.exe")
NAME = re.compile(r"i\.?\s*g\.?\s*i", re.I)          # "IGI", "I.G.I.", "Project I.G.I"

COMMON = [
    r"%ProgramFiles(x86)%\Innerloop\Project IGI",
    r"%ProgramFiles(x86)%\Codemasters\Project IGI",
    r"%ProgramFiles(x86)%\Project IGI",
    r"%ProgramFiles%\Project IGI",
    r"%ProgramFiles(x86)%\GOG Galaxy\Games\Project IGI",
    r"%ProgramFiles(x86)%\Steam\steamapps\common\Project IGI",
    r"C:\Games\IGI", r"C:\IGI", r"C:\Program Files\IGI",
]


def looks_like_game(path):
    """A folder is a copy of the game when the level data and an exe are there."""
    p = pathlib.Path(path)
    if not (p / "missions" / "location0" / "level1" / "objects.qvm").is_file():
        return False
    return any((p / e).is_file() for e in EXE) or (p / "missions").is_dir()


def _reg_values(root, key):
    import winreg
    out = {}
    try:
        with winreg.OpenKey(root, key) as k:
            for i in range(winreg.QueryInfoKey(k)[1]):
                name, value, _ = winreg.EnumValue(k, i)
                out[name] = value
    except OSError:
        pass
    return out


def _reg_subkeys(root, key):
    import winreg
    try:
        with winreg.OpenKey(root, key) as k:
            return [winreg.EnumKey(k, i) for i in range(winreg.QueryInfoKey(k)[0])]
    except OSError:
        return []


def from_registry():
    """Uninstall entries and GOG's own records that name the game."""
    if sys.platform != "win32":
        return []
    import winreg
    hits = []
    roots = [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")]
    for root, base in roots:
        for sub in _reg_subkeys(root, base):
            v = _reg_values(root, base + "\\" + sub)
            name = str(v.get("DisplayName") or "")
            if not NAME.search(name):
                continue
            for field in ("InstallLocation", "InstallPath", "Path"):
                p = v.get(field)
                if p:
                    hits.append((str(p).strip('"'), "installed: %s" % name))
    for base in (r"SOFTWARE\GOG.com\Games", r"SOFTWARE\WOW6432Node\GOG.com\Games"):
        for sub in _reg_subkeys(winreg.HKEY_LOCAL_MACHINE, base):
            v = _reg_values(winreg.HKEY_LOCAL_MACHINE, base + "\\" + sub)
            if NAME.search(str(v.get("gameName") or "")) and v.get("path"):
                hits.append((str(v["path"]), "GOG: %s" % v.get("gameName")))
    return hits


def from_steam():
    """Steam's library folders, then any game folder whose name mentions IGI."""
    if sys.platform != "win32":
        return []
    import winreg
    hits, libs = [], []
    steam = _reg_values(winreg.HKEY_CURRENT_USER, r"SOFTWARE\Valve\Steam").get("SteamPath")
    if not steam:
        return []
    steam = pathlib.Path(str(steam))
    libs.append(steam)
    vdf = steam / "steamapps" / "libraryfolders.vdf"
    if vdf.is_file():
        try:
            for m in re.finditer(r'"path"\s*"([^"]+)"', vdf.read_text(encoding="utf-8", errors="replace")):
                libs.append(pathlib.Path(m.group(1).replace("\\\\", "\\")))
        except OSError:
            pass
    for lib in libs:
        common = lib / "steamapps" / "common"
        if not common.is_dir():
            continue
        try:
            for d in common.iterdir():
                if d.is_dir() and NAME.search(d.name):
                    hits.append((str(d), "Steam: %s" % d.name))
        except OSError:
            pass
    return hits


def from_common():
    return [(os.path.expandvars(p), "a usual place") for p in COMMON]


def find(extra=()):
    """Every copy of the game we can find, best guess first, without duplicates."""
    from studio import paths
    named = []
    for p, why in ((paths.setting("gamePath"), "the studio's settings"),
                   (paths.setting("pristinePath"), "the studio's settings (the original)")):
        if p:
            named.append((os.path.expandvars(str(p)), why))
    candidates = named + [(str(e), "you named it") for e in extra]
    candidates += from_registry() + from_steam() + from_common()

    out, seen = [], set()
    for p, why in candidates:
        try:
            rp = pathlib.Path(p).resolve()
        except OSError:
            continue
        if rp in seen or not rp.is_dir():
            continue
        seen.add(rp)
        if looks_like_game(rp):
            out.append({"path": str(rp), "where": why})
    return out


if __name__ == "__main__":
    hits = find(sys.argv[1:])
    if not hits:
        print("no copy of the game found; point the studio at one with:\n"
              "  python -m studio setup --game <folder>")
    for h in hits:
        print("%-44s %s" % (h["path"], h["where"]))
