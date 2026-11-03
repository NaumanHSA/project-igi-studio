# Looking at a running IGI.exe from outside: its windows, a picture of its window,
# and the text of a fatal error it put up. No injection, and nothing written to it.
# Used by the mission tests (studio/build/testrun.py). Windows only.
#
#   pids_of(path)        the processes running exactly that exe
#   windows_of(pid)      their top-level windows
#   game_window(pid)     the one the game draws in
#   capture(hwnd, size)  (width, height, PNG bytes), or None
#   signature(hwnd, size)  a tiny copy of what it shows, to tell one screen from another
#   click(hwnd, x, y)    a real click at a point of its window
#   dialogs_of(pid)      any dialog boxes it is showing, as text
#   end(pid)             closes it
import ctypes as C
import ctypes.wintypes as W
import os, struct, time, zlib

_u32 = C.WinDLL("user32", use_last_error=True) if os.name == "nt" else None
_g32 = C.WinDLL("gdi32", use_last_error=True) if os.name == "nt" else None
_k32 = C.WinDLL("kernel32", use_last_error=True) if os.name == "nt" else None

_WNDENUM = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
PW_RENDERFULLCONTENT = 2
TH32CS_SNAPPROCESS = 2
PROCESS_QUERY_LIMITED = 0x1000
PROCESS_TERMINATE = 1


class _PE32(C.Structure):
    _fields_ = [("dwSize", W.DWORD), ("cntUsage", W.DWORD), ("th32ProcessID", W.DWORD), ("th32DefaultHeapID", C.c_size_t),
                ("th32ModuleID", W.DWORD), ("cntThreads", W.DWORD), ("th32ParentProcessID", W.DWORD),
                ("pcPriClassBase", C.c_long), ("dwFlags", W.DWORD), ("szExeFile", C.c_wchar * 260)]


if _k32:
    _k32.CreateToolhelp32Snapshot.restype = W.HANDLE
    _k32.CreateToolhelp32Snapshot.argtypes = [W.DWORD, W.DWORD]
    _k32.Process32FirstW.argtypes = [W.HANDLE, C.POINTER(_PE32)]
    _k32.Process32NextW.argtypes = [W.HANDLE, C.POINTER(_PE32)]
    _k32.CloseHandle.argtypes = [W.HANDLE]
    _k32.OpenProcess.restype = W.HANDLE
    _k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    _k32.TerminateProcess.argtypes = [W.HANDLE, W.UINT]
    _k32.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
    _u32.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
    _u32.GetClassNameW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
    _u32.GetWindowRect.argtypes = [W.HWND, C.POINTER(W.RECT)]
    _u32.GetClientRect.argtypes = [W.HWND, C.POINTER(W.RECT)]
    _u32.IsWindowVisible.argtypes = [W.HWND]
    _u32.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
    _u32.EnumWindows.argtypes = [_WNDENUM, W.LPARAM]
    _u32.EnumChildWindows.argtypes = [W.HWND, _WNDENUM, W.LPARAM]
    _u32.GetDC.restype = W.HDC
    _u32.GetDC.argtypes = [W.HWND]
    _u32.ReleaseDC.argtypes = [W.HWND, W.HDC]
    _u32.PrintWindow.argtypes = [W.HWND, W.HDC, W.UINT]
    _u32.ClientToScreen.argtypes = [W.HWND, C.POINTER(W.POINT)]
    _g32.CreateCompatibleDC.restype = W.HDC
    _g32.CreateCompatibleDC.argtypes = [W.HDC]
    _g32.CreateCompatibleBitmap.restype = W.HBITMAP
    _g32.CreateCompatibleBitmap.argtypes = [W.HDC, C.c_int, C.c_int]
    _g32.SelectObject.restype = W.HGDIOBJ
    _g32.SelectObject.argtypes = [W.HDC, W.HGDIOBJ]
    _g32.DeleteObject.argtypes = [W.HGDIOBJ]
    _g32.DeleteDC.argtypes = [W.HDC]
    _g32.BitBlt.argtypes = [W.HDC, C.c_int, C.c_int, C.c_int, C.c_int, W.HDC, C.c_int, C.c_int, W.DWORD]
    _g32.GetDIBits.argtypes = [W.HDC, W.HBITMAP, W.UINT, W.UINT, C.c_void_p, C.c_void_p, W.UINT]


def _norm(p):
    return os.path.normcase(os.path.abspath(str(p)))


def _image_of(pid):
    h = _k32.OpenProcess(PROCESS_QUERY_LIMITED, False, pid)
    if not h:
        return None
    try:
        n = W.DWORD(32768)
        buf = C.create_unicode_buffer(n.value)
        return buf.value if _k32.QueryFullProcessImageNameW(h, 0, buf, C.byref(n)) else None
    finally:
        _k32.CloseHandle(h)


def _processes():
    snap = _k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    out = []
    e = _PE32()
    e.dwSize = C.sizeof(_PE32)
    try:
        ok = _k32.Process32FirstW(snap, C.byref(e))
        while ok:
            out.append((e.th32ProcessID, e.szExeFile))
            ok = _k32.Process32NextW(snap, C.byref(e))
    finally:
        _k32.CloseHandle(snap)
    return out


def pids_of(path):
    """The processes running exactly this exe: never another copy of the game."""
    want, name = _norm(path), os.path.basename(str(path)).lower()
    out = []
    for pid, exe in _processes():
        if exe.lower() == name:
            img = _image_of(pid)
            if img and _norm(img) == want:
                out.append(pid)
    return out


def any_game_running(name="IGI.exe"):
    """Any copy of the game at all: it takes the display and input for itself, so
    only one can run at a time."""
    return [pid for pid, exe in _processes() if exe.lower() == name.lower()]


def _text(h):
    b = C.create_unicode_buffer(1024)
    _u32.GetWindowTextW(h, b, 1024)
    return b.value


def _class(h):
    b = C.create_unicode_buffer(256)
    _u32.GetClassNameW(h, b, 256)
    return b.value


def windows_of(pid):
    out = []

    def each(h, _):
        p = W.DWORD()
        _u32.GetWindowThreadProcessId(h, C.byref(p))
        if p.value == pid and _u32.IsWindowVisible(h):
            r = W.RECT()
            _u32.GetClientRect(h, C.byref(r))
            out.append({"hwnd": h, "class": _class(h), "title": _text(h), "w": r.right - r.left, "h": r.bottom - r.top})
        return True
    _u32.EnumWindows(_WNDENUM(each), 0)
    return out


def game_window(pid):
    """The biggest window that is not a dialog."""
    ws = [w for w in windows_of(pid) if w["class"] != "#32770" and w["w"] > 100 and w["h"] > 100]
    return max(ws, key=lambda w: w["w"] * w["h"])["hwnd"] if ws else None


def dialogs_of(pid):
    """What a dialog box of the game's says: a fatal error is one of these."""
    out = []
    for w in windows_of(pid):
        if w["class"] != "#32770":
            continue
        parts = []

        def child(h, _):
            if _class(h).lower() == "static":
                t = _text(h).strip()
                if t:
                    parts.append(t)
            return True
        _u32.EnumChildWindows(w["hwnd"], _WNDENUM(child), 0)
        out.append({"title": w["title"], "text": "\n".join(parts)})
    return out


def _png(w, h, bgra):
    """A PNG of a top-down BGRA buffer, with nothing but the standard library."""
    rows = bytearray()
    stride = w * 4
    for y in range(h):
        row = bgra[y * stride:(y + 1) * stride]
        out = bytearray(w * 3)
        out[0::3] = row[2::4]
        out[1::3] = row[1::4]
        out[2::3] = row[0::4]
        rows.append(0)
        rows += out

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(bytes(rows), 6)) + chunk(b"IEND", b""))


def _grab(hwnd, w, h, from_screen):
    wdc = _u32.GetDC(hwnd if not from_screen else None)
    mem = _g32.CreateCompatibleDC(wdc)
    bmp = _g32.CreateCompatibleBitmap(wdc, w, h)
    old = _g32.SelectObject(mem, bmp)
    try:
        if from_screen:
            p = W.POINT(0, 0)
            _u32.ClientToScreen(hwnd, C.byref(p))
            if not _g32.BitBlt(mem, 0, 0, w, h, wdc, p.x, p.y, 0x00CC0020):      # SRCCOPY
                return None
        elif not _u32.PrintWindow(hwnd, mem, PW_RENDERFULLCONTENT | 1):          # 1: the client area
            return None
        info = struct.pack("<IiiHHIIiiII", 40, w, -h, 1, 32, 0, 0, 0, 0, 0, 0)    # top-down BGRA
        info = C.create_string_buffer(info + b"\0" * 8)
        buf = C.create_string_buffer(w * h * 4)
        if not _g32.GetDIBits(mem, bmp, 0, h, buf, info, 0):
            return None
        return buf.raw
    finally:
        _g32.SelectObject(mem, old)
        _g32.DeleteObject(bmp)
        _g32.DeleteDC(mem)
        _u32.ReleaseDC(hwnd if not from_screen else None, wdc)


def _is_black(buf, w, h):
    """All one colour, near enough: what an old game's surface gives some ways of asking."""
    if not buf:
        return True
    step = max(4, (w * h // 400)) * 4
    seen = set()
    for i in range(0, len(buf) - 3, step):
        seen.add(buf[i:i + 3])
        if len(seen) > 3:
            return False
    return True


def _frame(hwnd, size=None):
    """(width, height, BGRA) of what the game draws. The compatibility layer's window
    has its own title bar and border drawn inside it: size is the game's own size, and
    only that part is kept. Asked of the window, which works behind other windows; if
    that gives nothing but black, read off the screen, which needs it uncovered."""
    r = W.RECT()
    if not _u32.GetClientRect(hwnd, C.byref(r)):
        return None
    w, h = r.right - r.left, r.bottom - r.top
    if w <= 0 or h <= 0:
        return None
    buf = _grab(hwnd, w, h, False)
    if _is_black(buf, w, h):
        alt = _grab(hwnd, w, h, True)
        if alt:
            buf = alt
    if not buf:
        return None
    gw, gh = size or (None, None)
    if not gw or not gh or gw > w or gh > h or (gw, gh) == (w, h):
        return w, h, buf
    x0 = (w - gw) // 2                   # the border is even at the sides and the bottom
    y0 = h - gh - x0
    rows = [buf[(y0 + y) * w * 4 + x0 * 4:(y0 + y) * w * 4 + (x0 + gw) * 4] for y in range(gh)]
    return gw, gh, b"".join(rows)


def capture(hwnd, size=None):
    """(width, height, PNG bytes), or None."""
    f = _frame(hwnd, size)
    return (f[0], f[1], _png(f[0], f[1], f[2])) if f else None


def signature(hwnd, size=None, nx=32, ny=24):
    """A tiny grey copy of what it shows, to tell one screen from another."""
    f = _frame(hwnd, size)
    if not f:
        return None
    w, h, b = f
    out = []
    for j in range(ny):
        y = int((j + 0.5) * h / ny)
        for i in range(nx):
            x = int((i + 0.5) * w / nx)
            p = (y * w + x) * 4
            out.append((b[p] + 2 * b[p + 1] + b[p + 2]) // 4)
    return out


def green_in(hwnd, size, box):
    """How many pixels in a box of the game's picture are bright green: the menus' text."""
    f = _frame(hwnd, size)
    if not f:
        return 0
    w, h, b = f
    x0, y0, x1, y1 = max(0, box[0]), max(0, box[1]), min(w, box[2]), min(h, box[3])
    n = 0
    for y in range(y0, y1):
        row = y * w * 4
        for x in range(x0, x1):
            p = row + x * 4
            bl, g, r = b[p], b[p + 1], b[p + 2]
            if g >= 170 and g > r * 1.25 and g > bl * 1.6:
                n += 1
    return n


def difference(a, b):
    """0 for the same screen, up to 255: the average change over the tiny copies."""
    if not a or not b or len(a) != len(b):
        return 255.0
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def brightness(a):
    return sum(a) / len(a) if a else 0.0


# ------------------------------------------------------------------ input, for the menu's two clicks
class _MOUSEINPUT(C.Structure):
    _fields_ = [("dx", C.c_long), ("dy", C.c_long), ("mouseData", W.DWORD), ("dwFlags", W.DWORD), ("time", W.DWORD),
                ("dwExtraInfo", C.c_size_t)]


class _INPUT(C.Structure):
    class _U(C.Union):
        _fields_ = [("mi", _MOUSEINPUT), ("pad", C.c_byte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", W.DWORD), ("u", _U)]


_MOVE, _DOWN, _UP = 1, 2, 4
_parked = []


def _mouse(flags, dx=0, dy=0):
    i = _INPUT(type=0)
    i.mi = _MOUSEINPUT(dx, dy, 0, flags, 0, 0)
    _u32.SendInput(1, C.byref(i), C.sizeof(_INPUT))


def foreground():
    return _u32.GetForegroundWindow()


def front(hwnd):
    """The window in front: the game reads its input only then. The Alt press is what
    lets a program in the background hand the foreground over."""
    _u32.keybd_event(0x12, 0, 0, 0)
    _u32.keybd_event(0x12, 0, 2, 0)
    _u32.SetForegroundWindow(W.HWND(hwnd))


def give_back_foreground(hwnd):
    if hwnd:
        front(hwnd)
    park()


def click(hwnd, x, y):
    """A real click at a point of the window: the cursor there, a small real move so that
    a game reading movement sees it, then the button. The cursor goes back with park()."""
    if not _parked:
        p = W.POINT()
        _u32.GetCursorPos(C.byref(p))
        _parked.append((p.x, p.y))
    p = W.POINT(x, y)
    _u32.ClientToScreen(W.HWND(hwnd), C.byref(p))
    _u32.SetCursorPos(p.x, p.y)
    time.sleep(0.12)
    for d in (2, 2, 2, -2, -2, -2):
        _mouse(_MOVE, d, 0)
        time.sleep(0.03)
    time.sleep(0.2)
    _mouse(_DOWN)
    time.sleep(0.12)
    _mouse(_UP)


def park():
    """The cursor back where the person left it."""
    if _parked:
        _u32.SetCursorPos(*_parked.pop())


def end(pid):
    h = _k32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if not h:
        return False
    try:
        return bool(_k32.TerminateProcess(h, 0))
    finally:
        _k32.CloseHandle(h)
