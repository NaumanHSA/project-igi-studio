"""The studio as an MCP server (studio/server/mcp.py and mcp_stdio.py): both eras
of the protocol, the road from an agent's call to the window and back, who may
connect, and the relay with the studio open and closed."""
import base64, json, os, pathlib, shutil, subprocess, sys, tempfile, threading, time, unittest, urllib.error, urllib.request

from unittest import mock

from studio.server import mcp as M

ROOT = pathlib.Path(__file__).resolve().parents[1]
ORIGINAL_RUNNING = M.claude_desktop_running
TOOLS = [{"name": "get_overview", "description": "the level", "parameters": {"type": "object", "properties": {}},
          "annotations": {"readOnlyHint": True}},
         {"name": "place_guards", "description": "guards", "parameters": {"type": "object", "properties": {"x": {"type": "number"}}}}]
PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNGfake").decode()
META = {M.K_VERSION: M.MODERN, M.K_CAPS: {}, M.K_CLIENT: {"name": "test-agent", "version": "1"}}


class Fake:
    """Stands in for the window's side."""
    def __init__(self):
        self.called = []
        self.seen = None

    def tools(self):
        return {"tools": TOOLS, "instructions": "How to work."}

    def saw(self, c):
        self.seen = c

    def call(self, name, args, client=None):
        self.called.append((name, args))
        return {"ok": True, "echo": args}


def rpc(method, params=None, mid=1):
    m = {"jsonrpc": "2.0", "id": mid, "method": method}
    if params is not None:
        m["params"] = params
    return m


class ProtocolTests(unittest.TestCase):
    def test_an_older_client_gets_the_handshake_of_its_revision(self):
        f = Fake()
        r = M.respond(rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                         "clientInfo": {"name": "Claude Desktop", "version": "9"}}), f)["result"]
        self.assertEqual(r["protocolVersion"], "2025-06-18")
        self.assertEqual(r["serverInfo"]["name"], "igi-studio")
        self.assertEqual(r["instructions"], "How to work.")
        self.assertNotIn("resultType", r)
        self.assertEqual(f.seen["name"], "Claude Desktop")
        # a revision we don't know: the newest handshake we do
        r = M.respond(rpc("initialize", {"protocolVersion": "2031-01-01"}), f)["result"]
        self.assertEqual(r["protocolVersion"], M.LEGACY[0])

    def test_a_modern_client_is_served_from_each_request(self):
        r = M.respond(rpc("server/discover", {"_meta": META}), Fake())["result"]
        self.assertEqual(r["resultType"], "complete")
        self.assertIn(M.MODERN, r["supportedVersions"])
        self.assertEqual(r["_meta"][M.K_SERVER]["name"], "igi-studio")
        r = M.respond(rpc("tools/list", {"_meta": META}), Fake())["result"]
        self.assertEqual(r["resultType"], "complete")
        self.assertEqual([t["name"] for t in r["tools"]], ["get_overview", "place_guards"])

    def test_an_unknown_version_is_refused_with_what_we_speak(self):
        e = M.respond(rpc("tools/list", {"_meta": {M.K_VERSION: "1900-01-01", M.K_CAPS: {}}}), Fake())["error"]
        self.assertEqual(e["code"], -32022)
        self.assertIn(M.MODERN, e["data"]["supported"])
        self.assertEqual(e["data"]["requested"], "1900-01-01")

    def test_a_modern_request_without_its_capabilities_is_malformed(self):
        e = M.respond(rpc("tools/list", {"_meta": {M.K_VERSION: M.MODERN}}), Fake())["error"]
        self.assertEqual(e["code"], -32602)

    def test_tools_list_as_mcp_wants_it(self):
        t = M.respond(rpc("tools/list"), Fake())["result"]["tools"][0]
        self.assertEqual(t["inputSchema"], TOOLS[0]["parameters"])
        self.assertEqual(t["annotations"], {"readOnlyHint": True})
        self.assertNotIn("parameters", t)

    def test_a_call_and_its_answer(self):
        f = Fake()
        r = M.respond(rpc("tools/call", {"name": "place_guards", "arguments": {"x": 1}}), f)["result"]
        self.assertEqual(f.called, [("place_guards", {"x": 1})])
        self.assertFalse(r["isError"])
        self.assertEqual(json.loads(r["content"][0]["text"]), {"ok": True, "echo": {"x": 1}})

    def test_an_unknown_tool_is_a_protocol_error_and_a_failed_one_is_not(self):
        e = M.respond(rpc("tools/call", {"name": "no_such"}), Fake())["error"]
        self.assertEqual(e["code"], -32602)

        class Bad(Fake):
            def call(self, name, args, client=None):
                return {"ok": False, "error": "There is no ground there."}
        r = M.respond(rpc("tools/call", {"name": "place_guards"}), Bad())["result"]
        self.assertTrue(r["isError"])
        self.assertIn("no ground", r["content"][0]["text"])

    def test_a_tool_s_picture_comes_as_image_content(self):
        c = M.result_content({"ok": True, "image": {"url": PNG, "bounds": {"x0": 1}}, "note": "seen"})
        self.assertEqual(c["content"][1], {"type": "image", "data": PNG.split(",")[1], "mimeType": "image/png"})
        said = json.loads(c["content"][0]["text"])
        self.assertEqual(said["pictures"], [{"bounds": {"x0": 1}}])    # what it said of the picture, not the picture
        self.assertNotIn("image", said)
        self.assertNotIn("base64", c["content"][0]["text"])

    def test_notifications_get_no_answer(self):
        self.assertIsNone(M.respond({"jsonrpc": "2.0", "method": "notifications/initialized"}, Fake()))

    def test_an_unknown_method(self):
        self.assertEqual(M.respond(rpc("nonsense"), Fake())["error"]["code"], -32601)

    def test_prompts(self):
        names = [p["name"] for p in M.respond(rpc("prompts/list"), Fake())["result"]["prompts"]]
        self.assertIn("design_mission", names)
        r = M.respond(rpc("prompts/get", {"name": "design_mission", "arguments": {"idea": "a rescue"}}), Fake())["result"]
        self.assertIn("a rescue", r["messages"][0]["content"]["text"])
        self.assertEqual(M.respond(rpc("prompts/get", {"name": "design_mission"}), Fake())["error"]["code"], -32602)


class _Home(unittest.TestCase):
    """A home of its own, with a port of its own, so the real one is never touched."""
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="igi-mcp-")
        cls.was = os.environ.get("IGISTUDIO_HOME")
        os.environ["IGISTUDIO_HOME"] = cls.dir
        import socket
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        cls.port = s.getsockname()[1]
        s.close()
        M.save_connection({"port": cls.port, "token": "t" * 40, "on": False})

    @classmethod
    def tearDownClass(cls):
        if cls.was is None:
            os.environ.pop("IGISTUDIO_HOME", None)
        else:
            os.environ["IGISTUDIO_HOME"] = cls.was
        shutil.rmtree(cls.dir, ignore_errors=True)

    def post(self, msg, headers=None, token="t" * 40):
        h = {"Content-Type": "application/json"}
        if token:
            h["Authorization"] = "Bearer " + token
        h.update(headers or {})
        req = urllib.request.Request("http://127.0.0.1:%d/mcp" % self.port, data=json.dumps(msg).encode(), headers=h, method="POST")
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with op.open(req, timeout=5) as r:
                body = r.read()
                return r.status, json.loads(body) if body else None
        except urllib.error.HTTPError as e:
            body = e.read()
            return e.code, json.loads(body) if body else None

    def window(self, listener, stop):
        def go():
            b = listener.bridge
            while not stop.is_set():
                c = b.next("w", 0.2)
                if c:
                    b.result(c["id"], {"ok": True, "ran": c["name"], "args": c["args"]})
        threading.Thread(target=go, daemon=True).start()


class BridgeTests(_Home):
    def window_runs_one(self, b, gen="w1", answer=None):
        """A window that runs one call."""
        def go():
            c = None
            for _ in range(40):
                c = b.next(gen, 0.25)
                if c:
                    break
            if c:
                b.result(c["id"], answer(c) if answer else {"ok": True, "ran": c["name"]})
        t = threading.Thread(target=go, daemon=True)
        t.start()
        return t

    def test_a_call_reaches_the_window_and_comes_back(self):
        b = M.Bridge()
        b.hello("w1", TOOLS, "x")
        self.window_runs_one(b)
        self.assertEqual(b.call("get_overview", {}), {"ok": True, "ran": "get_overview"})
        self.assertEqual(b.status()["last"], "get_overview")

    def test_no_window_is_said_at_once_and_not_left_hanging(self):
        b = M.Bridge()
        b.WAIT_WINDOW = 0.2
        t0 = time.time()
        r = b.call("get_overview", {})
        self.assertFalse(r["ok"])
        self.assertIn("not answering", r["error"])
        self.assertLess(time.time() - t0, 2)
        self.assertEqual(list(b.queue), [])              # and it does not run later, out of the blue

    def test_a_window_busy_on_a_long_call_is_not_taken_for_gone(self):
        b = M.Bridge()
        b.WAIT_WINDOW = 0.1
        b.hello("w1", TOOLS, "x")
        got = []
        threading.Thread(target=lambda: got.append(b.call("slow", {})), daemon=True).start()
        c = b.next("w1", 2)                              # the window takes it and works on it
        time.sleep(0.3)                                  # longer than a window may be silent
        out = []
        th = threading.Thread(target=lambda: out.append(b.call("next_one", {})), daemon=True)
        th.start()
        time.sleep(0.3)
        self.assertEqual(out, [])                        # waiting its turn, not told the window is gone
        b.result(c["id"], {"ok": True})
        c2 = b.next("w1", 2)
        self.assertEqual(c2["name"], "next_one")
        b.result(c2["id"], {"ok": True})
        th.join(2)
        self.assertEqual(out, [{"ok": True}])

    def test_calls_run_in_the_order_they_came(self):
        b = M.Bridge()
        b.hello("w1", TOOLS, "x")
        done = []

        def agent(n):
            b.call("t%d" % n, {})
        for n in range(3):
            threading.Thread(target=agent, args=(n,), daemon=True).start()
            time.sleep(0.05)
        for _ in range(3):
            c = b.next("w1", 2)
            done.append(c["name"])
            b.result(c["id"], {"ok": True})
        self.assertEqual(done, ["t0", "t1", "t2"])

    def test_a_reloaded_window_ends_what_the_old_one_was_running(self):
        b = M.Bridge()
        b.hello("old", TOOLS, "x")
        out = []
        th = threading.Thread(target=lambda: out.append(b.call("slow", {})), daemon=True)
        th.start()
        self.assertEqual(b.next("old", 2)["name"], "slow")
        b.hello("new", TOOLS, "x")
        th.join(2)
        self.assertFalse(out[0]["ok"])
        self.assertIn("reloaded", out[0]["error"])
        self.assertIsNone(b.next("old", 0.1))            # the old page's polls are turned away

    def test_a_call_the_window_never_got_goes_back_in_line(self):
        b = M.Bridge()
        b.hello("w1", TOOLS, "x")
        out = []
        th = threading.Thread(target=lambda: out.append(b.call("t", {})), daemon=True)
        th.start()
        c = b.next("w1", 2)
        b.give_back(c)
        c2 = b.next("w1", 2)
        self.assertEqual(c2["id"], c["id"])
        b.result(c2["id"], {"ok": True})
        th.join(2)
        self.assertEqual(out, [{"ok": True}])


class ListenerTests(_Home):
    def setUp(self):
        self.l = M.Listener()
        self.assertTrue(self.l.start(), self.l.error)
        self.l.bridge.hello("w", TOOLS, "How to work.")
        self.stop = threading.Event()
        self.window(self.l, self.stop)

    def tearDown(self):
        self.stop.set()
        self.l.stop()

    def test_a_call_over_http(self):
        s, r = self.post(rpc("tools/call", {"name": "get_overview", "arguments": {"a": 1}}))
        self.assertEqual(s, 200)
        self.assertEqual(json.loads(r["result"]["content"][0]["text"]), {"ok": True, "ran": "get_overview", "args": {"a": 1}})

    def test_a_modern_call_over_http_with_its_headers(self):
        s, r = self.post(rpc("tools/call", {"name": "get_overview", "_meta": META}),
                         {"MCP-Protocol-Version": M.MODERN, "Mcp-Method": "tools/call", "Mcp-Name": "get_overview"})
        self.assertEqual(s, 200)
        self.assertEqual(r["result"]["resultType"], "complete")

    def test_headers_that_do_not_match_the_body_are_refused(self):
        s, r = self.post(rpc("tools/call", {"name": "get_overview", "_meta": META}),
                         {"MCP-Protocol-Version": M.MODERN, "Mcp-Method": "tools/call", "Mcp-Name": "place_guards"})
        self.assertEqual(s, 400)
        self.assertEqual(r["error"]["code"], -32020)
        s, r = self.post(rpc("tools/list", {"_meta": META}))                     # none at all
        self.assertEqual((s, r["error"]["code"]), (400, -32020))

    def test_status_codes_of_a_modern_client(self):
        s, r = self.post(rpc("nonsense", {"_meta": META}), {"MCP-Protocol-Version": M.MODERN, "Mcp-Method": "nonsense"})
        self.assertEqual((s, r["error"]["code"]), (404, -32601))
        v = dict(META, **{M.K_VERSION: "1900-01-01"})
        s, r = self.post(rpc("tools/list", {"_meta": v}), {"MCP-Protocol-Version": "1900-01-01", "Mcp-Method": "tools/list"})
        self.assertEqual((s, r["error"]["code"]), (400, -32022))

    def test_a_notification_is_accepted_with_no_body(self):
        self.assertEqual(self.post({"jsonrpc": "2.0", "method": "notifications/initialized"})[0], 202)

    def test_without_the_token_nothing_runs(self):
        for tok in (None, "wrong"):
            s, r = self.post(rpc("tools/call", {"name": "get_overview"}), token=tok)
            self.assertEqual(s, 401)
        self.assertIsNone(self.l.bridge.last)

    def test_a_web_page_is_refused_even_with_the_token(self):
        s, _ = self.post(rpc("tools/list"), {"Origin": "https://evil.example"})
        self.assertEqual(s, 403)
        s, _ = self.post(rpc("tools/list"), {"Host": "evil.example:%d" % self.port})   # DNS rebinding
        self.assertEqual(s, 403)
        self.assertEqual(self.post(rpc("tools/list"), {"Origin": "http://localhost:3000"})[0], 200)

    def test_no_stream_to_open_and_no_cors(self):
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for method in ("GET", "DELETE"):
            req = urllib.request.Request("http://127.0.0.1:%d/mcp" % self.port, headers={"Authorization": "Bearer " + "t" * 40}, method=method)
            with self.assertRaises(urllib.error.HTTPError) as c:
                op.open(req, timeout=5)
            self.assertEqual(c.exception.code, 405)
        req = urllib.request.Request("http://127.0.0.1:%d/mcp" % self.port, method="OPTIONS")
        with self.assertRaises(urllib.error.HTTPError) as c:
            op.open(req, timeout=5)
        self.assertEqual(c.exception.code, 405)
        self.assertIsNone(c.exception.headers.get("Access-Control-Allow-Origin"))

    def test_only_this_pc_can_reach_it(self):
        self.assertEqual(self.l.srv.server_address[0], "127.0.0.1")

    def test_the_status_says_who_is_connected(self):
        self.post(rpc("initialize", {"protocolVersion": "2025-06-18", "clientInfo": {"name": "Claude Desktop", "version": "9"}}))
        s = self.l.status()
        self.assertTrue(s["on"])
        self.assertEqual(s["client"]["name"], "Claude Desktop")


class SwitchTests(_Home):
    def test_stop_ends_waiting_calls_and_closes_the_port(self):
        l = M.Listener()
        self.assertTrue(l.start())
        l.bridge.hello("w", TOOLS, "x")
        out = []
        th = threading.Thread(target=lambda: out.append(l.bridge.call("slow", {})), daemon=True)
        th.start()
        self.assertEqual(l.bridge.next("w", 2)["name"], "slow")
        l.stop()
        th.join(2)
        self.assertFalse(out[0]["ok"])
        self.assertIn("stopped", out[0]["error"])
        self.assertFalse(l.running())
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with self.assertRaises(urllib.error.URLError):
            op.open("http://127.0.0.1:%d/mcp" % self.port, timeout=2)

    def test_it_remembers_how_it_was_left_and_can_start_again(self):
        l = M.Listener()
        self.assertTrue(l.start())
        self.assertTrue(M.connection()["on"])
        l.stop()
        self.assertFalse(M.connection()["on"])
        self.assertTrue(l.start())
        l.stop()

    def test_a_taken_port_is_said_and_not_shared(self):
        a, b = M.Listener(), M.Listener()
        self.assertTrue(a.start())
        try:
            self.assertFalse(b.start())
            self.assertIn("taken", b.status()["error"])
            self.assertFalse(b.running())
        finally:
            a.stop()

    def test_the_token_is_kept_between_runs(self):
        self.assertEqual(M.connection()["token"], "t" * 40)


class ClaudeDesktopTests(_Home):
    def setUp(self):
        self.app = tempfile.mkdtemp(prefix="igi-appdata-")
        self.was_app = os.environ.get("APPDATA")
        os.environ["APPDATA"] = self.app
        (pathlib.Path(self.app) / "Claude").mkdir()
        self.f = pathlib.Path(self.app) / "Claude" / "claude_desktop_config.json"
        p = mock.patch.object(M, "claude_desktop_running", return_value=False)
        self.running = p.start()
        self.addCleanup(p.stop)

    def test_it_waits_for_claude_desktop_to_close_or_its_own_copy_would_undo_this(self):
        self.running.return_value = True
        was = {"mcpServers": {"other": {"command": "x"}}}
        self.f.write_text(json.dumps(was))
        r = M.add_to_claude_desktop()
        self.assertFalse(r["ok"])
        self.assertTrue(r["running"])
        self.assertEqual(json.loads(self.f.read_text()), was)
        self.running.return_value = False
        self.assertTrue(M.add_to_claude_desktop()["ok"])
        self.assertIn("igi-studio", json.loads(self.f.read_text())["mcpServers"])

    def test_claude_code_is_not_claude_desktop(self):
        from studio.server import gamewin as G
        cases = [([r"C:\Users\Me\.vscode\extensions\anthropic.claude-code-2\native-binary\claude.exe",
                   r"C:\Users\Me\.local\bin\claude.exe"], False),
                 ([r"C:\Program Files\WindowsApps\Claude_3.6_x64__abc\app\Claude.exe"], True),
                 ([r"C:\Users\Me\AppData\Local\AnthropicClaude\app-1.0\claude.exe"], True),
                 ([], False)]
        for images, want in cases:
            with mock.patch.object(G, "images_of", return_value=images):
                self.assertEqual(ORIGINAL_RUNNING(), want, images)

    def tearDown(self):
        os.environ["APPDATA"] = self.was_app or ""
        shutil.rmtree(self.app, ignore_errors=True)

    def test_added_and_nothing_else_touched(self):
        was = {"mcpServers": {"other": {"command": "x"}}, "preferences": {"a": 1}}
        self.f.write_text(json.dumps(was))
        self.assertFalse(M.connect_info()["claudeDesktop"]["added"])
        self.assertTrue(M.add_to_claude_desktop()["ok"])
        now = json.loads(self.f.read_text())
        self.assertEqual(now["preferences"], {"a": 1})
        self.assertEqual(now["mcpServers"]["other"], {"command": "x"})
        self.assertIn("igi-studio", now["mcpServers"])
        self.assertEqual(now["mcpServers"]["igi-studio"]["args"], ["-m", "studio", "mcp"])
        self.assertTrue(M.connect_info()["claudeDesktop"]["added"])
        self.assertEqual(json.loads(self.f.with_name(self.f.name + ".before-igi-studio").read_text()), was)   # as it was

    def test_a_file_it_cannot_read_is_left_alone(self):
        self.f.write_text("{not json")
        self.assertFalse(M.add_to_claude_desktop()["ok"])
        self.assertEqual(self.f.read_text(), "{not json")


class RelayTests(_Home):
    """The real program, started as a client starts it."""
    def relay(self):
        env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONIOENCODING="utf-8")
        p = subprocess.Popen([sys.executable, "-m", "studio", "mcp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, env=env, cwd=tempfile.gettempdir())
        self.addCleanup(self._close, p)
        return p

    def _close(self, p):
        for s in (p.stdin, p.stdout):
            try:
                s.close()
            except OSError:
                pass
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()

    def ask(self, p, msg):
        p.stdin.write(json.dumps(msg).encode() + b"\n")
        p.stdin.flush()
        return json.loads(p.stdout.readline())

    def test_with_the_studio_closed_it_still_answers(self):
        M.tools_file().write_text(json.dumps({"tools": TOOLS, "instructions": "Cached."}))
        p = self.relay()
        r = self.ask(p, rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "c"}}))
        self.assertEqual(r["result"]["serverInfo"]["name"], "igi-studio")
        r = self.ask(p, rpc("tools/list", mid=2))
        self.assertEqual(len(r["result"]["tools"]), 2)
        r = self.ask(p, rpc("tools/call", {"name": "get_overview"}, mid=3))
        self.assertTrue(r["result"]["isError"])
        self.assertIn("press Start", r["result"]["content"][0]["text"])

    def test_with_the_studio_listening_it_carries_the_call_both_eras(self):
        l = M.Listener()
        self.assertTrue(l.start())
        self.addCleanup(l.stop)
        l.bridge.hello("w", TOOLS, "Live.")
        stop = threading.Event()
        self.addCleanup(stop.set)
        self.window(l, stop)
        p = self.relay()
        r = self.ask(p, rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "Claude Desktop"}}))
        self.assertEqual(r["result"]["instructions"], "Live.")
        self.assertEqual(l.status()["client"]["name"], "Claude Desktop")
        r = self.ask(p, rpc("tools/call", {"name": "place_guards", "arguments": {"x": 5}}, mid=2))
        self.assertEqual(json.loads(r["result"]["content"][0]["text"])["args"], {"x": 5})
        # a modern request: the relay puts the headers on
        r = self.ask(p, rpc("tools/call", {"name": "get_overview", "_meta": META}, mid=3))
        self.assertEqual(r["result"]["resultType"], "complete")

    def test_the_client_s_name_reaches_the_studio_though_it_shook_hands_while_closed(self):
        p = self.relay()
        self.ask(p, rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "Claude Desktop"}}))
        l = M.Listener()                                  # only now does the person press Start
        self.assertTrue(l.start())
        self.addCleanup(l.stop)
        l.bridge.hello("w", TOOLS, "Live.")
        stop = threading.Event()
        self.addCleanup(stop.set)
        self.window(l, stop)
        self.ask(p, rpc("tools/call", {"name": "get_overview"}, mid=2))
        self.assertEqual(l.status()["client"]["name"], "Claude Desktop")

    def test_while_closed_any_call_is_told_to_press_start_even_a_tool_the_old_list_lacks(self):
        M.tools_file().write_text(json.dumps({"tools": TOOLS, "instructions": ""}))
        p = self.relay()
        r = self.ask(p, rpc("tools/call", {"name": "a_tool_from_a_newer_version"}))
        self.assertIn("press Start", r["result"]["content"][0]["text"])

    def test_nothing_but_mcp_on_stdout_and_it_leaves_when_closed(self):
        p = self.relay()
        r = self.ask(p, rpc("ping"))
        self.assertEqual(r, {"jsonrpc": "2.0", "id": 1, "result": {}})
        p.stdin.close()
        self.assertEqual(p.wait(timeout=5), 0)
        self.assertEqual(p.stdout.read(), b"")


if __name__ == "__main__":
    unittest.main()
