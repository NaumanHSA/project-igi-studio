# The studio as an MCP server: any agent (Claude Desktop, Claude Code, Cursor...)
# works in the open studio, and the person watches every change as it happens.
#
#   the agent <- stdio -> studio mcp (mcp_stdio.py) <- HTTP -> Listener (here)
#                                 <- the page asks for the next call -> the window
#
# Nothing listens until the person presses Start in the studio, and it stops when
# they press Stop or close it. The tools are not here: they are the editor's, the
# same ones the built-in AI designer runs (StudioAI.tools and StudioAI.run), and
# the window publishes them when it connects. So a call from an agent takes the
# same road as a call from the designer, and a tool added for one is there for both.
#
# The protocol is written out here rather than taken from a package, as with the
# rest of the server: the standard library and nothing else. It speaks both eras
# of MCP on one endpoint. A client that sends initialize gets the handshake of its
# revision; one that puts its version in each request's _meta (2026-07-28 on) is
# served statelessly. No session is kept for either. respond() is the whole of it,
# and the relay uses it too, so a client that starts while the studio is closed
# still gets real answers.
import base64, collections, hmac, json, os, pathlib, re, secrets, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from studio import paths

MODERN = "2026-07-28"
LEGACY = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"]
VERSIONS = [MODERN] + LEGACY
K_VERSION = "io.modelcontextprotocol/protocolVersion"
K_CLIENT = "io.modelcontextprotocol/clientInfo"
K_CAPS = "io.modelcontextprotocol/clientCapabilities"
K_SERVER = "io.modelcontextprotocol/serverInfo"

PORT = 8760
CLOSED = ("The studio is not listening. Open Project IGI Studio and press Start in its MCP panel "
          "(the MCP button at the top), then try again.")

GUIDES = paths.ROOT / "editor" / "guide"


def server_info():
    try:
        from studio import __version__ as v
    except ImportError:
        v = "0"
    return {"name": "igi-studio", "title": "Project IGI Studio", "version": v}


# ------------------------------------------------------------------ what connects
def conn_file():
    return paths.home() / "mcp.json"


def tools_file():
    return paths.home() / "mcp-tools.json"


def connection():
    """The port, the token and whether it was left on. Made once and kept, so a
    client set up once stays set up. It lives in the user's own folder: the relay
    reads the token from here, so it never has to go in a client's settings."""
    f = conn_file()
    try:
        c = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        c = {}
    if not c.get("token") or not c.get("port"):
        c = {"port": int(c.get("port") or PORT), "token": secrets.token_urlsafe(32), "on": bool(c.get("on"))}
        save_connection(c)
    return c


def save_connection(c):
    f = conn_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    t = f.with_suffix(".tmp")
    t.write_text(json.dumps(c, indent=1), encoding="utf-8")
    paths.replace(t, f)


def cached_tools():
    """What the window last published: {tools, instructions}, or nothing yet."""
    try:
        d = json.loads(tools_file().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


# ------------------------------------------------------------------ the guides
def guide_title(text, name):
    m = re.match(r"#\s+(.+)", text)
    return m.group(1).strip() if m else name


def guides():
    """The studio's guides for agents: [{name, title, text}]. The ones measured from the
    person's own game come from their folder, never from the repository."""
    try:
        from studio.extract import anatomy
        anatomy.ensure()
    except (ImportError, OSError, ValueError):
        pass                              # without them, the written guides still stand
    out = []
    for d in (GUIDES, paths.home() / "guide"):
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.md")):
            try:
                text = f.read_text(encoding="utf-8")
            except OSError:
                continue
            out.append({"name": f.stem, "title": guide_title(text, f.stem), "text": text})
    return out


PROMPTS = {
    "design_mission": ("Design a whole new mission, from a plan to a tested build",
                       [{"name": "idea", "description": "what the mission is about", "required": True},
                        {"name": "level", "description": "which level's map to use (1 to 14), if you have one in mind"}],
                       "Design a new mission in Project IGI Studio: {idea}{level}\n\n"
                       "Start by calling studio_status and read_guide (topic: design). Work as the guide says: look at "
                       "the maps, write a plan and show it to me before building, build one area at a time, look at each "
                       "area on the map and in 3D, then test it in the game."),
    "review_mission": ("Look over the open mission and say what to fix",
                       [],
                       "Review the mission open in Project IGI Studio. Use check_mission and stealth_check, look at it "
                       "with screenshot_map and screenshot_3d, and test it in the game with test_load. Then tell me what "
                       "is wrong and what you would change, most important first. Change nothing yet."),
    "fix_problems": ("Fix what the check list finds in the open mission",
                     [],
                     "Open the check list of the mission in Project IGI Studio (check_mission) and fix what it finds. "
                     "Look at each fix on the map, then run check_mission again until it is clean."),
}


# ------------------------------------------------------------------ the protocol
class RpcError(Exception):
    def __init__(self, code, message, data=None, http=None):
        super().__init__(message)
        self.code, self.message, self.data, self.http = code, message, data, http


def _picture_part(p):
    url = p.get("url") or ""
    m = re.match(r"data:([\w/+.-]+);base64,", url)
    if not m:
        return None
    return {"type": "image", "data": url[m.end():], "mimeType": m.group(1)}


def result_content(res):
    """A tool's answer as MCP content: the answer as JSON, then any pictures. A
    tool gives pictures as image or images, each {url: a data: URL, ...}: the rest
    of what it says about a picture goes with the text."""
    res = dict(res) if isinstance(res, dict) else {"ok": False, "error": "No answer from the tool."}
    pics = [res.pop("image")] if res.get("image") else []
    pics += res.pop("images", None) or []
    parts, about = [], []
    for p in pics:
        part = _picture_part(p) if isinstance(p, dict) else None
        if part:
            parts.append(part)
            about.append({k: v for k, v in p.items() if k != "url"})
    if about:
        res["pictures"] = about
    text = {"type": "text", "text": json.dumps(res, ensure_ascii=False)}
    return {"content": [text] + parts, "isError": res.get("ok") is False}


def tool_defs(tools):
    """The registry's tools as MCP lists them."""
    out = []
    for t in tools or []:
        d = {"name": t["name"], "description": t.get("description") or "",
             "inputSchema": t.get("parameters") or {"type": "object", "properties": {}}}
        if t.get("title"):
            d["title"] = t["title"]
        if t.get("annotations"):
            d["annotations"] = t["annotations"]
        out.append(d)
    return out


def capabilities(modern):
    return {"tools": {} if modern else {"listChanged": True}, "resources": {}, "prompts": {}}


def respond(msg, studio):
    """The answer to one JSON-RPC message, or None for a notification. studio is
    what the tools come from: .tools() -> {tools, instructions}, .call(name, args,
    client) -> a tool's answer, .saw(client)."""
    if not isinstance(msg, dict) or "method" not in msg:
        return None                                # a response, or nothing we understand: nothing to say
    if "id" not in msg:
        return None
    mid = msg["id"]
    try:
        return {"jsonrpc": "2.0", "id": mid, "result": _dispatch(msg["method"], msg.get("params") or {}, studio)}
    except RpcError as e:
        err = {"code": e.code, "message": e.message}
        if e.data is not None:
            err["data"] = e.data
        return {"jsonrpc": "2.0", "id": mid, "error": err}


def _dispatch(method, params, studio):
    meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
    version = meta.get(K_VERSION)
    if version is not None and version not in VERSIONS:
        raise RpcError(-32022, "Unsupported protocol version", {"supported": VERSIONS, "requested": version}, 400)
    modern = version in (MODERN,) if version else False
    if modern and K_CAPS not in meta:
        raise RpcError(-32602, "Every request must carry %s in _meta" % K_CAPS, http=400)
    client = meta.get(K_CLIENT)
    if method == "initialize":
        client = params.get("clientInfo") or client
    if client:
        studio.saw(client)
    res = _method(method, params, studio, modern, client)
    if modern:
        res = dict(res)
        res.setdefault("resultType", "complete")
        res["_meta"] = dict(res.get("_meta") or {}, **{K_SERVER: server_info()})
    return res


def _method(method, params, studio, modern, client):
    if method == "initialize":
        asked = params.get("protocolVersion")
        return {"protocolVersion": asked if asked in LEGACY else LEGACY[0], "capabilities": capabilities(False),
                "serverInfo": server_info(), "instructions": studio.tools().get("instructions") or ""}
    if method == "server/discover":
        return {"supportedVersions": VERSIONS, "capabilities": capabilities(True),
                "instructions": studio.tools().get("instructions") or ""}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": tool_defs(studio.tools().get("tools"))}
    if method == "tools/call":
        name = params.get("name")
        if not isinstance(name, str) or not name:
            raise RpcError(-32602, "tools/call needs a tool name", http=400)
        known = studio.tools().get("tools")
        if getattr(studio, "live", True) and known and not any(t.get("name") == name for t in known):
            raise RpcError(-32602, "Unknown tool: %s" % name, http=400)
        return result_content(studio.call(name, params.get("arguments") or {}, client))
    if method == "resources/list":
        return {"resources": [{"uri": "igi://guide/%s" % g["name"], "name": g["name"], "title": g["title"],
                               "mimeType": "text/markdown"} for g in guides()]}
    if method == "resources/read":
        uri = params.get("uri") or ""
        for g in guides():
            if uri == "igi://guide/%s" % g["name"]:
                return {"contents": [{"uri": uri, "mimeType": "text/markdown", "text": g["text"]}]}
        raise RpcError(-32602, "No resource %s" % uri, {"uri": uri}, 400)
    if method == "prompts/list":
        return {"prompts": [{"name": k, "description": v[0], "arguments": v[1]} for k, v in PROMPTS.items()]}
    if method == "prompts/get":
        p = PROMPTS.get(params.get("name"))
        if not p:
            raise RpcError(-32602, "No prompt %s" % params.get("name"), http=400)
        a = params.get("arguments") or {}
        missing = [x["name"] for x in p[1] if x.get("required") and not a.get(x["name"])]
        if missing:
            raise RpcError(-32602, "The prompt needs: %s" % ", ".join(missing), http=400)
        text = p[2].format(idea=a.get("idea") or "", level=(" (on the map of level %s)" % a["level"]) if a.get("level") else "")
        return {"description": p[0], "messages": [{"role": "user", "content": {"type": "text", "text": text}}]}
    raise RpcError(-32601, "Method not found: %s" % method, http=404)


# ------------------------------------------------------------------ the window
class Bridge:
    """Between the agents' calls and the open window. An agent's call waits here
    until the window has asked for it, run it and posted the answer."""
    NO_WINDOW = "The studio's window is not answering. Check that the studio is open."
    WAIT_WINDOW = 6.0        # how long a call waits for a window to come and ask
    WAIT_RESULT = 180.0      # the tools that take longer (a build, a test) give back a job instead

    def __init__(self):
        self.cv = threading.Condition()
        self.queue = collections.deque()
        self.open = {}                   # call id -> {event, result}
        self.gen = None                  # the window now connected; an older one's polls are turned away
        self.polling = 0
        self.seen = 0.0                  # when a window last asked
        self.published = {}              # {tools, instructions}
        self.client = None               # the agent last heard from
        self.client_seen = 0.0
        self.calls = 0
        self.last = None                 # the last tool called
        self.next_id = 0

    # the agent's side
    def tools(self):
        return self.published or cached_tools()

    def saw(self, client):
        with self.cv:
            self.client = {"name": str(client.get("title") or client.get("name") or "An agent"),
                           "version": str(client.get("version") or "")}
            self.client_seen = time.time()

    def call(self, name, args, client=None):
        with self.cv:
            self.client_seen = time.time()
            self.calls += 1
            self.last = name
            self.next_id += 1
            cid = self.next_id
            ev = threading.Event()
            self.open[cid] = {"event": ev, "result": None}
            self.queue.append({"id": cid, "name": name, "args": args, "client": (self.client or {}).get("name")})
            self.cv.notify_all()
            t0 = time.time()
            # nobody to run it: say so rather than leave the agent hanging
            while not self._alive() and time.time() - t0 < self.WAIT_WINDOW and not ev.is_set():
                self.cv.wait(0.25)
            if not self._alive() and not ev.is_set():
                self._forget(cid)
                return {"ok": False, "error": self.NO_WINDOW}
        if not ev.wait(self.WAIT_RESULT):
            with self.cv:
                self._forget(cid)
            return {"ok": False, "error": "The studio took too long over %s (%d s)." % (name, self.WAIT_RESULT)}
        with self.cv:
            res = self.open.pop(cid, {}).get("result")
        return res

    def _alive(self):
        """A window is asking, asked a moment ago, or is busy running a call."""
        return bool(self.polling or time.time() - self.seen < self.WAIT_WINDOW
                    or any(c.get("taken") and not c["event"].is_set() for c in self.open.values()))

    def _forget(self, cid):
        self.open.pop(cid, None)
        self.queue = collections.deque(c for c in self.queue if c["id"] != cid)

    # the window's side
    def hello(self, gen, tools=None, instructions=None):
        """A window has connected (or come back after a reload): what the last one
        was running will never finish, so those calls are told now."""
        with self.cv:
            if gen != self.gen:
                self.gen = gen
                self._fail_running("The studio's window was reloaded while this ran. Try it again.")
                self.cv.notify_all()
            self.seen = time.time()
            if tools is not None:
                self.published = {"tools": tools, "instructions": instructions or ""}
        if tools is not None:
            try:
                t = tools_file().with_suffix(".tmp")
                t.write_text(json.dumps(self.published), encoding="utf-8")
                paths.replace(t, tools_file())
            except OSError:
                pass                      # only the relay's copy for when the studio is closed

    def next(self, gen, wait=20.0):
        """The next call for this window, or None when there is none yet."""
        end = time.time() + wait
        with self.cv:
            if gen != self.gen:
                return None
            self.polling += 1
            self.cv.notify_all()
            try:
                while True:
                    self.seen = time.time()
                    if gen != self.gen:
                        return None
                    if self.queue:
                        c = self.queue.popleft()
                        self.open.setdefault(c["id"], {"event": threading.Event(), "result": None})["taken"] = True
                        return c
                    left = end - time.time()
                    if left <= 0:
                        return None
                    self.cv.wait(min(left, 1.0))
            finally:
                self.polling -= 1

    def give_back(self, call):
        """A call the window never got: its connection had gone."""
        with self.cv:
            if call["id"] in self.open:
                self.open[call["id"]].pop("taken", None)
                self.queue.appendleft(call)
                self.cv.notify_all()

    def result(self, cid, res):
        with self.cv:
            c = self.open.get(cid)
            if c:
                c["result"] = res
                c["event"].set()

    def _fail_running(self, why):
        for cid, c in list(self.open.items()):
            if c.get("taken") and not c["event"].is_set():
                c["result"] = {"ok": False, "error": why}
                c["event"].set()

    def fail_all(self, why):
        with self.cv:
            self.queue.clear()
            for c in self.open.values():
                if not c["event"].is_set():
                    c["result"] = {"ok": False, "error": why}
                    c["event"].set()
            self.cv.notify_all()

    def status(self):
        with self.cv:
            return {"window": bool(self.polling or time.time() - self.seen < 30),
                    "client": self.client, "clientSeen": int(self.client_seen * 1000) if self.client_seen else 0,
                    "calls": self.calls, "last": self.last}


# ------------------------------------------------------------------ the listener
LOCAL_HOSTS = ("127.0.0.1", "localhost", "[::1]")


def _origin_ok(origin):
    if not origin:
        return True                      # not a browser
    m = re.match(r"^https?://([^/:]+|\[[^\]]+\])(:\d+)?$", origin)
    return bool(m) and m.group(1).lower() in LOCAL_HOSTS


def _host_ok(host):
    h = (host or "").strip().lower()
    return re.sub(r":\d+$", "", h) in LOCAL_HOSTS


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "IGIStudioMCP"
    sys_version = ""
    timeout = 300

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body=None, ctype="application/json", extra=None):
        data = b"" if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        if body is not None:
            self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if data:
            self.wfile.write(data)

    def _refuse(self):
        """A web page, or DNS rebinding, or anything without the token."""
        if not _origin_ok(self.headers.get("Origin")) or not _host_ok(self.headers.get("Host")):
            self._send(403, {"jsonrpc": "2.0", "error": {"code": -32600, "message": "Only local programs may connect."}})
            return True
        have = self.headers.get("Authorization") or ""
        want = "Bearer " + self.server.token
        if not hmac.compare_digest(have.encode("utf-8", "replace"), want.encode("utf-8")):
            self._send(401, {"jsonrpc": "2.0", "error": {"code": -32600, "message": "The studio's MCP token is missing or wrong."}})
            return True
        return False

    def _not_here(self):
        self._send(405, extra={"Allow": "POST"})

    def do_GET(self):
        if not self._refuse():
            self._not_here()

    def do_DELETE(self):
        if not self._refuse():
            self._not_here()

    def do_OPTIONS(self):
        self._send(405, extra={"Allow": "POST"})   # no CORS: a browser's preflight ends here

    def do_POST(self):
        if self.path.split("?", 1)[0].rstrip("/") != "/mcp":
            self._send(404, {"jsonrpc": "2.0", "error": {"code": -32601, "message": "The MCP endpoint is /mcp"}})
            return
        if self._refuse():
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            msg = json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._send(400, {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Not valid JSON"}})
            return
        if not isinstance(msg, dict):
            self._send(400, {"jsonrpc": "2.0", "error": {"code": -32600, "message": "One JSON-RPC message per request"}})
            return
        bad = _bad_headers(msg, self.headers)
        if bad:
            self._send(bad[0], bad[1])
            return
        # the relay says who it carries for: that client may have shaken hands with
        # the relay alone, while the studio was closed
        who = self.headers.get("X-Studio-Client")
        if who:
            self.server.bridge.saw({"name": _decoded(who) or "An agent"})
        res = respond(msg, self.server.bridge)
        if res is None:
            self._send(202)
            return
        code = 200
        err = res.get("error")
        if err and _is_modern(msg):
            code = 404 if err.get("code") == -32601 else 400 if err.get("code") in (-32602, -32022) else 200
        elif err and err.get("code") == -32022:
            code = 400
        self._send(code, res)


def _is_modern(msg):
    params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
    meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
    return K_VERSION in meta


def _decoded(v):
    m = re.fullmatch(r"=\?base64\?(.+)\?=", v or "")
    if not m:
        return v
    try:
        return base64.b64decode(m.group(1)).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None


def _bad_headers(msg, headers):
    """The headers a modern request must carry, and that they say what its body
    says. Only a request with _meta is held to this: an older client sends none."""
    header = headers.get("MCP-Protocol-Version")
    if not _is_modern(msg):
        if header and header not in VERSIONS:
            return 400, {"jsonrpc": "2.0", "id": msg.get("id"), "error": {
                "code": -32022, "message": "Unsupported protocol version", "data": {"supported": VERSIONS, "requested": header}}}
        return None
    if "id" not in msg:
        return None

    def mismatch(text):
        return 400, {"jsonrpc": "2.0", "id": msg.get("id"), "error": {"code": -32020, "message": "Header mismatch: " + text}}
    params = msg.get("params") or {}
    version = params["_meta"][K_VERSION]
    if header != version:
        return mismatch("MCP-Protocol-Version says %s, the body %s" % (header, version))
    if headers.get("Mcp-Method") != msg.get("method"):
        return mismatch("Mcp-Method says %s, the body %s" % (headers.get("Mcp-Method"), msg.get("method")))
    if msg.get("method") in ("tools/call", "prompts/get", "resources/read"):
        want = params.get("uri") if msg["method"] == "resources/read" else params.get("name")
        if _decoded(headers.get("Mcp-Name")) != want:
            return mismatch("Mcp-Name says %s, the body %s" % (headers.get("Mcp-Name"), want))
    return None


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False          # on Windows it would let a second studio take the same port


class Listener:
    """The switch in the studio's window."""

    def __init__(self):
        self.bridge = Bridge()
        self.srv = None
        self.thread = None
        self.error = None
        self.lock = threading.Lock()

    def running(self):
        return self.srv is not None

    def start(self):
        with self.lock:
            if self.srv:
                return True
            c = connection()
            try:
                srv = _Server(("127.0.0.1", int(c["port"])), _Handler)
            except OSError as e:
                self.error = ("Port %s is taken: another studio may be running, or another program is using it. (%s)"
                              % (c["port"], e.strerror or e))
                return False
            srv.bridge, srv.token = self.bridge, c["token"]
            self.thread = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
            self.thread.start()
            self.srv, self.error = srv, None
            c["on"] = True
            save_connection(c)
            return True

    def stop(self, remember=True):
        with self.lock:
            srv, self.srv = self.srv, None
            if srv:
                self.bridge.fail_all("The person stopped the MCP server in the studio.")
                srv.shutdown()
                srv.server_close()
            if remember:
                c = connection()
                c["on"] = False
                save_connection(c)

    def status(self):
        c = connection()
        s = self.bridge.status()
        s.update({"on": self.running(), "port": c["port"], "error": self.error})
        return s


# ------------------------------------------------------------------ connecting an agent
def relay_command():
    """How an agent's program starts the relay, from this studio as it is."""
    import sys
    if getattr(sys, "frozen", False):
        return {"command": sys.executable, "args": ["mcp"]}
    return {"command": sys.executable, "args": ["-m", "studio", "mcp"], "env": {"PYTHONPATH": str(paths.ROOT)}}


def claude_desktop_config():
    base = os.environ.get("APPDATA")
    return pathlib.Path(base) / "Claude" / "claude_desktop_config.json" if base else None


def connect_info():
    """What the window shows so that a person can connect an agent."""
    cmd = relay_command()
    entry = json.dumps({"mcpServers": {"igi-studio": cmd}}, indent=2)
    parts = ['"%s"' % cmd["command"] if " " in cmd["command"] else cmd["command"]] + cmd["args"]
    env = "".join(' --env %s=%s' % (k, ('"%s"' % v) if " " in v else v) for k, v in (cmd.get("env") or {}).items())
    c = connection()
    f = claude_desktop_config()
    return {"json": entry, "claudeCode": "claude mcp add igi-studio --scope user%s -- %s" % (env, " ".join(parts)),
            "url": "http://127.0.0.1:%s/mcp" % c["port"], "token": c["token"],
            "claudeDesktop": {"found": bool(f and f.parent.is_dir()), "path": str(f) if f else "", "added": _desktop_has(f)}}


def _desktop_has(f):
    try:
        return "igi-studio" in (json.loads(f.read_text(encoding="utf-8")).get("mcpServers") or {})
    except (OSError, ValueError, AttributeError):
        return False


def add_to_claude_desktop():
    """At the person's click: the studio in Claude Desktop's list of MCP servers.
    What else is in the file stays as it is, and the file as it was is kept."""
    f = claude_desktop_config()
    if not f or not f.parent.is_dir():
        return {"ok": False, "error": "Claude Desktop's folder is not on this PC."}
    cfg = {}
    if f.exists():
        raw = f.read_text(encoding="utf-8")
        try:
            cfg = json.loads(raw)
        except ValueError:
            return {"ok": False, "error": "Claude Desktop's settings file could not be read, so it was left alone: %s" % f}
        f.with_name(f.name + ".before-igi-studio").write_text(raw, encoding="utf-8")
    cfg.setdefault("mcpServers", {})["igi-studio"] = relay_command()
    t = f.with_name(f.name + ".tmp")
    t.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    paths.replace(t, f)
    return {"ok": True, "path": str(f)}
