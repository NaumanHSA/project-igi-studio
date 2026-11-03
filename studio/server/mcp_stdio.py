# The small program an agent's client starts: `studio mcp` (studio-server.exe mcp,
# or python -m studio mcp from a checkout). It carries MCP between the client's
# stdin and stdout and the listener in the open studio (mcp.py).
#
# The client usually starts this long before anyone opens the studio, and a server
# that fails its first handshake is often not tried again. So it answers whether the
# studio is there or not: from the tool list the studio last published, with any
# call told to open the studio and press Start. Once the studio is listening, the
# same process just works.
#
# Nothing but MCP may go to stdout.
import base64, json, os, sys, threading, urllib.error, urllib.request

from studio.server import mcp as MCP

_out = threading.Lock()
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))    # never through a proxy: it is this PC
_legacy = threading.Event()                 # it opened with initialize: it can take a change notice unasked
_who = []                                   # the client's name, once it has said


def write(msg):
    line = json.dumps(msg, ensure_ascii=True, separators=(",", ":")).encode("ascii") + b"\n"
    with _out:
        sys.stdout.buffer.write(line)
        sys.stdout.buffer.flush()


def log(text):
    try:
        sys.stderr.write("igi-studio: %s\n" % text)
        sys.stderr.flush()
    except OSError:
        pass


class Offline:
    """The studio is closed, or not listening: real answers, and no tools run."""
    live = False                              # any call gets "press Start", even one the old list doesn't name

    def tools(self):
        return MCP.cached_tools()

    def saw(self, client):
        pass

    def call(self, name, args, client=None):
        return {"ok": False, "error": MCP.CLOSED}


def _headers(msg, token):
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
         "Authorization": "Bearer " + token}
    if _who:
        h["X-Studio-Client"] = "=?base64?%s?=" % base64.b64encode(_who[0].encode("utf-8")).decode("ascii")
    params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
    meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
    if MCP.K_VERSION in meta:                 # what a modern request's body says, on its envelope
        h["MCP-Protocol-Version"] = str(meta[MCP.K_VERSION])
        h["Mcp-Method"] = str(msg.get("method"))
        name = params.get("uri") if msg.get("method") == "resources/read" else params.get("name")
        if name is not None:
            h["Mcp-Name"] = str(name)
    return h


def forward(msg):
    """The listener's answer to a message; None if it is not there."""
    c = MCP.connection()
    req = urllib.request.Request("http://127.0.0.1:%s/mcp" % c["port"], data=json.dumps(msg).encode("utf-8"),
                                 headers=_headers(msg, c["token"]), method="POST")
    try:
        with _opener.open(req, timeout=MCP.Bridge.WAIT_RESULT + 30) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        body = e.read()                       # a JSON-RPC error on a 4xx: the client wants that
    except (urllib.error.URLError, OSError):
        return None
    if not body:
        return {}                             # a notification, accepted
    try:
        return json.loads(body.decode("utf-8"))
    except ValueError:
        return None


def handle(msg):
    if isinstance(msg, dict) and msg.get("method") == "initialize":
        _legacy.set()
    if isinstance(msg, dict) and isinstance(msg.get("params"), dict):
        meta = msg["params"].get("_meta")
        info = msg["params"].get("clientInfo") or (meta.get(MCP.K_CLIENT) if isinstance(meta, dict) else None)
        if isinstance(info, dict) and (info.get("title") or info.get("name")):
            _who[:] = [str(info.get("title") or info.get("name"))]
    try:
        res = forward(msg)
        if res is None:
            res = MCP.respond(msg, Offline())
        if res:
            write(res)
    except Exception as e:                    # one bad call must not take the relay down
        log("%s: %s" % (type(e).__name__, e))
        if isinstance(msg, dict) and "id" in msg:
            write({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32603, "message": str(e)}})


def watch_tools():
    """The studio published a different list (a new version, or the first ever):
    tell the client, which then asks again."""
    f = MCP.tools_file()

    def stamp():
        try:
            return f.stat().st_mtime
        except OSError:
            return None
    was = stamp()
    ev = threading.Event()
    while not ev.wait(3.0):
        now = stamp()
        if now != was:
            was = now
            if _legacy.is_set():
                write({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})


def main():
    threading.Thread(target=watch_tools, daemon=True).start()
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            break                             # the client closed us: that is how it says goodbye
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            write({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Not valid JSON"}})
            continue
        # a call can take minutes: the next message (a ping, say) must not wait for it
        threading.Thread(target=handle, args=(msg,), daemon=True).start()
    try:
        sys.stdout.flush()
    finally:
        os._exit(0)


if __name__ == "__main__":
    main()
