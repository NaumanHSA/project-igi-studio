# Reads the player's live position out of a running IGI.exe, for the editor's
# live view and for stamping objects where you stand.
#
#   python studio/server/live_pos.py scan  --at 5994.03,-13667.28,42583.02
#       Stand still, read the F11 overlay, pass those numbers. Prints candidate
#       addresses (run again after moving: the address in both lists is yours).
#   python studio/server/live_pos.py watch --level 3
#       Calibrates from level 3's player start (be standing there), then prints
#       the live position; walk a few steps to lock on.
#
#   from live_pos import LiveReader
#   r = LiveReader(); r.calibrate((x, y, z)); r.read() -> {"status", "pos", ...}
#
# No injection and no writing - this only reads, with PROCESS_VM_READ.
#
# Finding the address without typing anything: when a mission starts, the
# player stands exactly at the level's start, which the level data gives. Every
# place in memory holding those three numbers (as float or double, in game units
# or the script's x4096) is a candidate. When the player walks, the candidates
# that follow - and stay near the start's height and inside the level - are the
# player's position; the others (the start marker itself, stale copies) stay
# put or go wild and are dropped.
#
# The scan does not step through memory four bytes at a time in Python: the two
# most significant bytes of a coordinate within a metre of the target take one
# or two values, so the scan asks bytes.find for those (C speed) and only
# unpacks the few thousand hits.
import ctypes as C
import ctypes.wintypes as W
import json, math, pathlib, struct, sys, threading, time
from studio import paths

SCALE = 4096.0
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
MEM_COMMIT = 0x1000
PAGE_READABLE = (0x02, 0x04, 0x20, 0x40)  # RO, RW, EX_READ, EX_RW
ENCODINGS = [("float game", "<f", 4, 1.0), ("double game", "<d", 8, 1.0),
             ("float raw", "<f", 4, SCALE), ("double raw", "<d", 8, SCALE),
             ("int raw", "<i", 4, SCALE)]

k32 = C.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.restype = W.HANDLE
k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.VirtualQueryEx.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t]
k32.VirtualQueryEx.restype = C.c_size_t
k32.GetExitCodeProcess.argtypes = [W.HANDLE, C.POINTER(W.DWORD)]


class MEMORY_BASIC_INFORMATION(C.Structure):
    _fields_ = [("BaseAddress", C.c_void_p), ("AllocationBase", C.c_void_p),
                ("AllocationProtect", W.DWORD), ("RegionSize", C.c_size_t),
                ("State", W.DWORD), ("Protect", W.DWORD), ("Type", W.DWORD)]


def find_pid(name="IGI.exe"):
    TH32CS_SNAPPROCESS = 0x00000002

    class PROCESSENTRY32(C.Structure):
        _fields_ = [("dwSize", W.DWORD), ("cntUsage", W.DWORD), ("th32ProcessID", W.DWORD),
                    ("th32DefaultHeapID", C.POINTER(C.c_ulong)), ("th32ModuleID", W.DWORD),
                    ("cntThreads", W.DWORD), ("th32ParentProcessID", W.DWORD),
                    ("pcPriClassBase", C.c_long), ("dwFlags", W.DWORD),
                    ("szExeFile", C.c_char * 260)]

    k32.CreateToolhelp32Snapshot.restype = W.HANDLE
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == W.HANDLE(-1).value:
        return None
    e = PROCESSENTRY32()
    e.dwSize = C.sizeof(PROCESSENTRY32)
    found = None
    if k32.Process32First(snap, C.byref(e)):
        while True:
            if e.szExeFile.decode("latin1").lower() == name.lower():
                found = e.th32ProcessID
                break
            if not k32.Process32Next(snap, C.byref(e)):
                break
    k32.CloseHandle(snap)
    return found


def open_proc(pid):
    h = k32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not h:
        raise OSError("could not open process %d (error %d)" % (pid, C.get_last_error()))
    return h


def alive(h):
    code = W.DWORD()
    return bool(k32.GetExitCodeProcess(h, C.byref(code))) and code.value == 259   # STILL_ACTIVE


def regions(h, limit=0x7FFFFFFFFFFF):
    mbi = MEMORY_BASIC_INFORMATION()
    addr = 0
    while addr < limit:
        if not k32.VirtualQueryEx(h, C.c_void_p(addr), C.byref(mbi), C.sizeof(mbi)):
            break
        base = mbi.BaseAddress or 0
        size = mbi.RegionSize or 0x1000
        if mbi.State == MEM_COMMIT and mbi.Protect in PAGE_READABLE and size < 256 * 1024 * 1024:
            yield base, size
        addr = base + size


def read(h, addr, size):
    buf = C.create_string_buffer(size)
    got = C.c_size_t(0)
    if not k32.ReadProcessMemory(h, C.c_void_p(addr), buf, size, C.byref(got)):
        return None
    return buf.raw[:got.value]


def _top_bytes(fmt, width, lo, hi):
    """The distinct two most significant bytes of every value in [lo, hi]."""
    out = set()
    steps = 64
    for i in range(steps + 1):
        v = lo + (hi - lo) * i / steps
        out.add(struct.pack(fmt, int(v) if fmt[1] == "i" else v)[width - 2:])
    return out


def scan(h, target, tol=1.0, ztol=None, cap=2000):
    """[(address, encoding, (x, y, z))] where three consecutive values match target."""
    gx, gy, gz = target
    ztol = tol if ztol is None else ztol
    hits = []
    plans = []
    for label, fmt, w, mul in ENCODINGS:
        keys = _top_bytes(fmt, w, (gx - tol) * mul, (gx + tol) * mul)
        plans.append((label, fmt, w, mul, keys))
    for base, size in regions(h):
        data = read(h, base, size)
        if not data:
            continue
        for label, fmt, w, mul, keys in plans:
            trio = fmt[0] + fmt[1] * 3
            for key in keys:
                at = data.find(key)
                while at >= 0:
                    off = at - (w - 2)
                    if off >= 0 and off % 4 == 0 and off + 3 * w <= len(data):
                        x, y, z = (c / mul for c in struct.unpack_from(trio, data, off))
                        if abs(x - gx) <= tol and abs(y - gy) <= tol and abs(z - gz) <= ztol:
                            hits.append((base + off, label, (x, y, z)))
                            if len(hits) >= cap:
                                return hits
                    at = data.find(key, at + 1)
    return hits


def read_pos(h, addr, label):
    _, fmt, w, mul = next(e for e in ENCODINGS if e[0] == label)
    d = read(h, addr, w * 3)
    if not d or len(d) < w * 3:
        return None
    x, y, z = struct.unpack(fmt[0] + fmt[1] * 3, d)
    if not all(math.isfinite(v) for v in (x, y, z)):
        return None
    return (x / mul, y / mul, z / mul)


class LiveReader:
    """Attach to the game, find the player's position from the level start,
    and read it on demand. Safe to call from several threads."""

    def __init__(self, process="IGI.exe", pid=None):
        self.process, self.fixed_pid = process, pid
        self.h = None
        self.pid = None
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        self.status = "idle"          # idle | no-game | scanning | waiting | live | lost | failed
        self.message = ""
        self.candidates = []          # [(addr, label, first position)]
        self.chosen = None
        self.start = None
        self.box = None
        self.last = None
        self.heading = None
        self.moved_at = 0.0

    def _attach(self):
        if self.h and alive(self.h):
            return True
        if self.h:
            k32.CloseHandle(self.h)
            self.h = None
        pid = self.fixed_pid or find_pid(self.process)
        if not pid:
            return False
        self.h, self.pid = open_proc(pid), pid
        return True

    def calibrate(self, start, box=None, manual=False):
        """start: (x, y, z) where the player stands now - the level start, or the
        F11 numbers. box: (x0, x1, y0, y1) the level's extent, for plausibility."""
        with self.lock:
            self.reset()
            if not self._attach():
                self.status, self.message = "no-game", "IGI.exe is not running"
                return self.state()
            self.status = "scanning"
            self.start, self.box = tuple(start), box
        t0 = time.time()
        # at the start the player may have dropped or crouched a little; with F11
        # numbers z is the eye height, 1.65 above the feet
        hits = scan(self.h, start, tol=1.0 if manual else 1.5, ztol=2.5 if manual else 4.0)
        with self.lock:
            self.candidates = hits
            self.status = "waiting" if hits else "failed"
            self.message = ("%d place(s) hold your position (%.1fs) - walk a few steps" % (len(hits), time.time() - t0)
                            if hits else "your position was not found - stand at the mission start "
                                         "(restart the mission) or enter the F11 numbers")
            return self.state()

    def _plausible(self, p):
        if p is None:
            return False
        sx, sy, sz = self.start
        if self.box:
            x0, x1, y0, y1 = self.box
            if not (x0 - 300 <= p[0] <= x1 + 300 and y0 - 300 <= p[1] <= y1 + 300):
                return False
        elif math.hypot(p[0] - sx, p[1] - sy) > 3000:
            return False
        return abs(p[2] - sz) < 150

    def read(self):
        with self.lock:
            if self.status in ("idle", "no-game", "failed", "scanning"):
                if self.status == "no-game" and self._attach():
                    self.status, self.message = "idle", "IGI.exe is running - calibrate"
                return self.state()
            if not self.h or not alive(self.h):
                self.status, self.message = "lost", "the game was closed"
                return self.state()
            if self.status == "waiting":
                alive_c, moved = [], []
                for addr, label, first in self.candidates:
                    p = read_pos(self.h, addr, label)
                    if not self._plausible(p):
                        continue
                    alive_c.append((addr, label, first))
                    if math.hypot(p[0] - first[0], p[1] - first[1]) > 0.75:
                        moved.append((addr, label, p))
                self.candidates = alive_c
                if not alive_c:
                    self.status, self.message = "failed", "lost every candidate - calibrate again at the start"
                elif moved:
                    # copies that move together are the same position; take the first
                    self.chosen = (moved[0][0], moved[0][1])
                    self.backups = [(a, l) for a, l, _ in moved[1:]]
                    self.status, self.message = "live", "following 0x%08X (%s)" % self.chosen
                    self.last = moved[0][2]
                else:
                    self.last = self.start
                return self.state()
            # live
            p = read_pos(self.h, *self.chosen)
            if not self._plausible(p):
                for a, l in list(getattr(self, "backups", [])):
                    q = read_pos(self.h, a, l)
                    if self._plausible(q):
                        self.chosen, p = (a, l), q
                        break
                else:
                    self.status, self.message = "lost", "the position went away (new mission?) - calibrate again"
                    return self.state()
            if self.last and math.hypot(p[0] - self.last[0], p[1] - self.last[1]) > 0.05:
                h = math.atan2(p[1] - self.last[1], p[0] - self.last[0])
                self.heading = h if self.heading is None else _blend_angle(self.heading, h, 0.5)
                self.moved_at = time.time()
            self.last = p
            return self.state()

    def state(self):
        return {"status": self.status, "message": self.message, "pid": self.pid,
                "pos": list(self.last) if self.last else None,
                "heading": self.heading, "candidates": len(self.candidates),
                "address": "0x%08X" % self.chosen[0] if self.chosen else None,
                "encoding": self.chosen[1] if self.chosen else None}


def _blend_angle(a, b, t):
    d = math.atan2(math.sin(b - a), math.cos(b - a))
    return a + d * t


def _level_start(lv):
    data = paths.data()
    L = json.load((data / ("level%d.json" % lv)).open())
    p = next(o for o in L["objects"] if o["type"] == "player")
    meta = data / "terrain" / ("level%d.json" % lv)
    box = None
    if meta.exists():
        m = json.load(meta.open())
        box = (m["x0"], m["x0"] + m["w"] * m["cell"], m["y0"], m["y0"] + m["h"] * m["cell"])
    return (p["x"], p["y"], p["z"]), box


def main(argv):
    def arg(n, d=None):
        return argv[argv.index(n) + 1] if n in argv else d
    cmd = argv[0] if argv else ""
    if cmd == "scan":
        pid = find_pid()
        if not pid:
            sys.exit("IGI.exe is not running. Launch D:\\IGI1\\IGI-Debug.bat first.")
        h = open_proc(pid)
        target = tuple(float(v) for v in arg("--at", "").split(","))
        t0 = time.time()
        hits = scan(h, target, tol=0.75)
        print("%d candidate(s) in %.1fs" % (len(hits), time.time() - t0))
        for a, label, got in hits[:40]:
            print("   0x%08X  %-12s  %.2f, %.2f, %.2f" % (a, label, got[0], got[1], got[2]))
    elif cmd == "watch":
        r = LiveReader(pid=int(arg("--pid")) if arg("--pid") else None)
        if arg("--at"):
            start, box = tuple(float(v) for v in arg("--at").split(",")), None
            print(r.calibrate(start, manual=True)["message"])
        else:
            start, box = _level_start(int(arg("--level", "1")))
            print(r.calibrate(start, box)["message"])
        try:
            while True:
                s = r.read()
                p = s["pos"]
                print("   %-8s %s   %s" % (s["status"], "%.2f, %.2f, %.2f" % tuple(p) if p else "-", s["message"][:60]), end="\r")
                time.sleep(0.5)
        except KeyboardInterrupt:
            print()
    else:
        print(__doc__ or "", "commands: scan | watch")


if __name__ == "__main__":
    main(sys.argv[1:])
