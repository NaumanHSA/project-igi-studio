# Keys the studio keeps for you, encrypted for your Windows account.
#
#   from studio import keystore
#   keystore.put("openai", "sk-...")     encrypted and saved
#   keystore.get("openai")               back, or "" when there is none
#   keystore.drop("openai")
#
# Windows' Data Protection API (DPAPI) does the encrypting: only the same
# Windows user on the same machine can read a key back, which is what
# Electron's safeStorage uses on Windows too. Doing it here rather than in the
# desktop shell keeps one path for both the app and a checkout run by hand.
#
# The file (secrets.json in the user's folder) holds only ciphertext. The
# settings file never holds a key.
import base64, ctypes, json, os, sys

from studio import paths

ENTROPY = b"Project IGI Studio / keys"


def _file():
    return paths.home() / "secrets.json"


if sys.platform == "win32":
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.windll.crypt32
    _kernel32 = ctypes.windll.kernel32
    _UI_FORBIDDEN = 0x1

    def _blob(data):
        buf = ctypes.create_string_buffer(data, len(data))
        return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    def _protect(data):
        src, _keep = _blob(data)
        ent, _keep2 = _blob(ENTROPY)
        out = _Blob()
        if not _crypt32.CryptProtectData(ctypes.byref(src), "Project IGI Studio", ctypes.byref(ent),
                                         None, None, _UI_FORBIDDEN, ctypes.byref(out)):
            raise OSError("Windows would not encrypt the key (error %d)" % ctypes.GetLastError())
        try:
            return ctypes.string_at(out.pbData, out.cbData)
        finally:
            _kernel32.LocalFree(out.pbData)

    def _unprotect(data):
        src, _keep = _blob(data)
        ent, _keep2 = _blob(ENTROPY)
        out = _Blob()
        if not _crypt32.CryptUnprotectData(ctypes.byref(src), None, ctypes.byref(ent),
                                           None, None, _UI_FORBIDDEN, ctypes.byref(out)):
            raise OSError("this key was saved by another Windows user or machine")
        try:
            return ctypes.string_at(out.pbData, out.cbData)
        finally:
            _kernel32.LocalFree(out.pbData)
    PROTECTED = True
else:
    # The game only runs on Windows, but the tests may not. Keys are then kept
    # as they are, and the store says so.
    def _protect(data):
        return data

    def _unprotect(data):
        return data
    PROTECTED = False


def _load():
    try:
        return json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(d):
    f = _file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
    os.replace(str(tmp), str(f))


def put(name, value):
    value = (value or "").strip()
    if not value:
        return drop(name)
    d = _load()
    d[name] = base64.b64encode(_protect(value.encode("utf-8"))).decode("ascii")
    _save(d)


def get(name):
    enc = _load().get(name)
    if not enc:
        return ""
    try:
        return _unprotect(base64.b64decode(enc)).decode("utf-8")
    except (OSError, ValueError):
        return ""


def drop(name):
    d = _load()
    if d.pop(name, None) is not None:
        _save(d)


def has(name):
    return bool(_load().get(name))


if __name__ == "__main__":
    # self-test in a throwaway home: a key goes in, is not readable in the file,
    # and comes back out
    import tempfile
    os.environ["IGISTUDIO_HOME"] = tempfile.mkdtemp(prefix="igistudio-keystore-")
    probe = "sk-test-" + "x" * 40
    put("probe", probe)
    raw = _file().read_text(encoding="utf-8")
    ok = get("probe") == probe and probe not in raw and "xxxxxxxx" not in raw
    drop("probe")
    ok = ok and get("probe") == ""
    print("keystore self-test: %s (encrypted with DPAPI: %s)" % ("passed" if ok else "FAILED", PROTECTED))
    raise SystemExit(0 if ok else 1)
