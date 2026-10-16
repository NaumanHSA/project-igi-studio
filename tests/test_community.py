"""The studio's community client (studio/server/community.py) against the
community's stand-in on this machine (cloud/dev/server.mjs, the same SQL in
PGlite): accounts by email and by Google, sharing, browsing as a guest,
pulling, a changed copy shared back with its line, a new version, deleting.

Needs Node and `npm install` in cloud/; skipped without them."""
import base64, json, os, pathlib, re, shutil, subprocess, tempfile, threading, time, unittest, urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEV = ROOT / "cloud" / "dev"
WEBP = "data:image/webp;base64," + base64.b64encode(b"RIFF\x20\x00\x00\x00WEBPVP8 " + b"\x07" * 40).decode()


def _node_ready():
    return shutil.which("node") and (DEV.parent / "node_modules" / "@electric-sql" / "pglite").is_dir()


@unittest.skipUnless(_node_ready(), "the community stand-in needs Node and npm install in cloud/")
class CommunityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.mkdtemp(prefix="igi-community-")
        os.environ["IGISTUDIO_HOME"] = cls.home
        cls.proc = subprocess.Popen(["node", "server.mjs", "--memory", "--port", "0"], cwd=str(DEV),
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
        port = None
        for line in cls.proc.stdout:
            m = re.search(r"COMMUNITY_DEV_READY port=(\d+)", line)
            if m:
                port = int(m.group(1))
                break
        assert port, "the stand-in did not start"
        threading.Thread(target=lambda: [None for _ in cls.proc.stdout], daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % port
        os.environ["IGISTUDIO_COMMUNITY"] = cls.base
        from studio.server import community as CM, missions as MS
        cls.CM, cls.MS = CM, MS
        MS.STORE = pathlib.Path(cls.home) / "missions" / "custom"
        MS.TRASH = MS.STORE / ".trash"
        MS.STORE.mkdir(parents=True, exist_ok=True)
        CM.sign_out()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.CM.sign_out()
        finally:
            cls.proc.kill()
            os.environ.pop("IGISTUDIO_COMMUNITY", None)
            shutil.rmtree(cls.home, ignore_errors=True)

    # -------------------------------------------------------------- helpers
    def code_for(self, email):
        with urllib.request.urlopen(self.base + "/dev/mail?to=" + urllib.parse.quote(email)) as r:
            return json.loads(r.read())["code"]

    def email_account(self, email, handle):
        CM = self.CM
        r = CM.sign_up(email, "secret-pass-1", handle)
        self.assertTrue(r["verify"])
        with self.assertRaises(CM.CommunityError) as e:
            CM.sign_in(email, "secret-pass-1")
        self.assertEqual(e.exception.code, "verify")
        st = CM.verify(email, self.code_for(email))
        self.assertTrue(st["signed_in"])
        self.assertIsNone(st["profile"])
        CM.rpc("save_profile", {"handle": handle, "name": handle.title()})
        return CM.status()

    def google_account(self, email, handle):
        CM = self.CM
        url = CM.google_start(open_browser=False)["url"]
        state = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]
        # the browser: Google's page, then back to the studio's listener
        req = urllib.request.Request(self.base + "/dev/google", method="POST",
                                     data=urllib.parse.urlencode({"state": state, "email": email, "name": handle}).encode(),
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            urllib.request.build_opener(CM._NoRedirect).open(req)
            self.fail("no redirect back to the studio")
        except urllib.error.HTTPError as e:
            back = e.headers["Location"]
        self.assertTrue(back.startswith("http://localhost:"))
        with urllib.request.urlopen(back) as r:
            self.assertIn(b"signed in", r.read())
        self.assertEqual(CM.google_state()["state"], "done")
        self.assertTrue(CM.status()["signed_in"])
        CM.rpc("save_profile", {"handle": handle, "name": handle.title()})
        return CM.status()

    def local_mission(self, name, objectives):
        m = self.MS.create(name, 3, "copy", "In-game words")
        self.MS.save(m["id"], plan={"objectives": objectives, "placements": [{"type": "soldier", "x": 1, "y": 2}]})
        return m["id"]

    def form(self, name, **kw):
        f = {"name": name, "summary": "A raid", "description": "Long words", "difficulty": "normal",
             "tags": ["stealth"], "objectives": [{"kind": "reach", "text": "Reach the tower"}],
             "facts": {"guards": 1}, "cover": WEBP, "thumb": WEBP, "allow_remix": True}
        f.update(kw)
        return f

    # -------------------------------------------------------------- the story
    def test_the_whole_story(self):
        CM, MS = self.CM, self.MS
        # a guest: no account, an empty community, nothing to write
        st = CM.status()
        self.assertTrue(st["configured"])
        self.assertFalse(st["signed_in"])
        self.assertEqual(CM.rpc("list_missions", {})["items"], [])
        with self.assertRaises(CM.CommunityError) as e:
            CM.rpc("set_vote", {"id": "00000000-0000-0000-0000-000000000000", "value": 1}, need_user=True)
        self.assertEqual(e.exception.code, "signin")

        # Ann signs up by email and shares a mission
        ann = self.email_account("ann@example.com", "ann")
        self.assertEqual(ann["profile"]["handle"], "ann")
        mid = self.local_mission("Radar Dome Raid", [{"kind": "reach", "text": "Reach the tower"}])
        r = CM.publish(mid, self.form("Radar Dome Raid"))
        self.assertEqual(r["version"], 1)
        cid = r["id"]
        self.assertEqual(MS.load(mid)["community"]["published"]["id"], cid)
        with self.assertRaises(CM.CommunityError) as e:
            CM.publish(self.local_mission("Copy", []), self.form("radar dome raid"))
        self.assertIn("already a mission called", str(e.exception))

        # the session outlives the studio: it is in the keystore, kept 30 days past its last use
        CM._S.update(cookies=None, jwt=None, exp=0)
        st = CM.status()
        self.assertTrue(st["signed_in"])
        self.assertTrue(st["keep"])
        self.assertGreater(st["until"], time.time() + 29 * 86400)

        # the database now and then answers as if a guest asked (Neon's Data API): not a sign-out
        real = CM._http

        def blind(misses, fn, answer):
            def call(method, url, body=None, headers=None, timeout=20):
                if url.endswith("/rpc/" + fn) and call.n < misses:
                    call.n += 1
                    return answer
                return real(method, url, body, headers, timeout)
            call.n = 0
            return call
        CM._http = blind(2, "me", (200, None, {"signed_in": False, "profile": None}))
        try:
            st = CM.status()
        finally:
            CM._http = real
        self.assertTrue(st["signed_in"])
        self.assertEqual(st["profile"]["handle"], "ann")
        self.assertNotIn("unsure", st)
        CM._http = blind(99, "me", (200, None, {"signed_in": False, "profile": None}))
        try:
            st = CM.status()                    # never seen: signed in as last seen, and unsure
        finally:
            CM._http = real
        self.assertTrue(st["signed_in"] and st["unsure"])
        self.assertEqual(st["profile"]["handle"], "ann")
        CM._http = blind(1, "save_profile", (400, None, {"code": "P0001", "message": "Sign in to the community first."}))
        try:
            self.assertEqual(CM.rpc("save_profile", {"handle": "ann", "name": "Ann"})["profile"]["handle"], "ann")
        finally:
            CM._http = real

        # signed out, the account is remembered: back in as Ann with no browser
        CM.sign_out()
        st = CM.status()
        self.assertFalse(st["signed_in"])
        self.assertEqual(st["remembered"]["handle"], "ann")
        self.assertEqual(CM.continue_remembered()["profile"]["handle"], "ann")
        self.assertNotIn("remembered", CM.status())

        # not used for 30 days: signed out when the studio starts, and ended on Neon
        jar = dict(CM._S["cookies"])
        CM._S["until"] = time.time() - 1
        CM._save()
        CM._S.update(cookies=None, jwt=None, exp=0)
        st = CM.status()
        self.assertFalse(st["signed_in"])
        self.assertNotIn("remembered", st)
        CM._S["cookies"] = jar
        self.assertIsNone(CM._user_jwt())

        # "Keep me signed in" unticked: only until the studio closes, and not remembered after
        st = CM.sign_in("ann@example.com", "secret-pass-1", keep=False)
        self.assertTrue(st["signed_in"])
        self.assertFalse(st["keep"])
        jar = dict(CM._S["cookies"])
        CM._S.update(cookies=None, jwt=None, exp=0)         # the studio started again
        st = CM.status()
        self.assertFalse(st["signed_in"])
        self.assertNotIn("remembered", st)
        CM._S["cookies"] = jar
        self.assertIsNone(CM._user_jwt())
        # ticked again later, from the account menu: kept
        CM.sign_in("ann@example.com", "secret-pass-1", keep=False)
        self.assertTrue(CM.set_keep(True)["keep"])
        CM._S.update(cookies=None, jwt=None, exp=0)
        self.assertTrue(CM.status()["signed_in"])
        CM.sign_out()

        # a Google sign-in carries on only when its own page comes back: started and
        # given up, a page of it finished later signs no one in
        url = CM.google_start(open_browser=False)["url"]
        self.assertEqual(CM.google_state()["state"], "waiting")
        state = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]
        CM.google_cancel()
        req = urllib.request.Request(self.base + "/dev/google", method="POST",
                                     data=urllib.parse.urlencode({"state": state, "email": "late@gmail.com"}).encode())
        try:
            urllib.request.build_opener(CM._NoRedirect).open(req)
        except urllib.error.HTTPError as e:
            late = e.headers["Location"]
        with self.assertRaises(urllib.error.URLError):     # the listener is gone with the sign-in
            urllib.request.urlopen(late, timeout=5).read()
        self.assertFalse(CM.status()["signed_in"])
        self.assertEqual(CM.google_state()["state"], "waiting")

        # a guest browses and looks at it, pictures and plan, but cannot pull
        cards = CM.rpc("list_missions", {"q": "radar"})["items"]
        self.assertEqual([c["name"] for c in cards], ["Radar Dome Raid"])
        mime, data = CM.media(cards[0]["thumb"])
        self.assertEqual(mime, "image/webp")
        self.assertTrue(data.startswith(b"RIFF"))
        p = CM.plan(cid)
        self.assertEqual(p["base"], {"level": 3, "kind": "copy"})
        self.assertEqual(p["plan"]["objectives"][0]["text"], "Reach the tower")
        with self.assertRaises(CM.CommunityError):
            CM.pull(cid)

        # Bob signs in with Google, votes, pulls it
        bob = self.google_account("bob@gmail.com", "bob")
        self.assertEqual(bob["profile"]["handle"], "bob")
        self.assertEqual(CM.rpc("set_vote", {"id": cid, "value": 1})["up"], 1)
        mine = CM.pull(cid)
        self.assertEqual(mine["name"], "Radar Dome Raid")
        self.assertEqual(mine["community"]["origin"]["author"]["handle"], "ann")
        self.assertEqual(MS.summary(mine)["community"]["origin"]["author"], "ann")
        self.assertEqual(CM.rpc("get_mission", {"id": cid})["pulls"], 1)

        # unchanged, it cannot be shared back; changed, it is a remix carrying the line
        with self.assertRaises(CM.CommunityError) as e:
            CM.publish(mine["id"], self.form("Radar Dome Raid Redux"))
        self.assertEqual(e.exception.code, "unchanged")
        plan = MS.load(mine["id"])["plan"]
        plan["placements"].append({"type": "soldier", "x": 9, "y": 9})
        MS.save(mine["id"], plan=plan)
        r2 = CM.publish(mine["id"], self.form("Radar Dome Raid Redux"))
        remix = CM.rpc("get_mission", {"id": r2["id"]})
        self.assertEqual(remix["remix_of"]["name"], "Radar Dome Raid")
        self.assertEqual([x["author"]["handle"] for x in remix["lineage"]], ["ann"])
        # a duplicate keeps where it came from, but is not what was shared
        dup = MS.create("Dup", 3, copy_from=mine["id"])
        self.assertEqual(dup["community"]["origin"]["id"], cid)
        self.assertNotIn("published", dup["community"])

        # Ann puts out version 2: Bob's pulled copy sees it
        CM.sign_out()
        CM.sign_in("ann@example.com", "secret-pass-1")
        plan = MS.load(mid)["plan"]
        plan["objectives"].append({"kind": "destroy", "text": "Blow the generator"})
        MS.save(mid, plan=plan)
        r3 = CM.publish(mid, self.form("Radar Dome Raid", mode="update", notes="A second objective"))
        self.assertEqual(r3["version"], 2)
        ups = CM.updates()
        self.assertEqual(ups[mine["id"]]["version"], 2)
        self.assertEqual(CM.plan(cid, 1)["version"], 1)

        # the routes the editor calls
        code, out = CM.handle("POST", "/api/community/rpc/list_missions", {}, {"p": {"sort": "top"}})
        self.assertEqual(code, 200)
        self.assertEqual(out["result"]["items"][0]["name"], "Radar Dome Raid")
        code, out = CM.handle("POST", "/api/community/rpc/upload_media", {}, {"p": {}})
        self.assertEqual(code, 404)
        code, out = CM.handle("GET", "/api/community/media/" + cards[0]["thumb"], {}, {})
        self.assertEqual(out[0], "image/webp")

        # Bob deletes his account: his remix and his vote go
        CM.sign_out()
        url = CM.google_start(open_browser=False)["url"]
        state = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]
        req = urllib.request.Request(self.base + "/dev/google", method="POST",
                                     data=urllib.parse.urlencode({"state": state, "email": "bob@gmail.com"}).encode())
        try:
            urllib.request.build_opener(CM._NoRedirect).open(req)
        except urllib.error.HTTPError as e:
            urllib.request.urlopen(e.headers["Location"]).read()
        self.assertEqual(CM.google_state()["state"], "done")
        CM.delete_account()
        self.assertFalse(CM.status()["signed_in"])
        self.assertEqual(CM.rpc("get_mission", {"id": cid})["up"], 0)
        with self.assertRaises(CM.CommunityError):
            CM.rpc("get_mission", {"id": r2["id"]})


if __name__ == "__main__":
    unittest.main()
