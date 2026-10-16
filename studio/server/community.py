# The community: missions people share with each other, on Neon
# (cloud/migrations/001_community.sql holds every rule).
#
# The editor never talks to the cloud itself. It calls the routes here
# (/api/community/..., see handle()), and this module holds the account and
# makes the calls:
#
#   Neon's Data API   POST <DATA>/rpc/<fn>  {"p": {...}}   Authorization: Bearer <JWT>
#   Neon Auth         <AUTH>/sign-up/email, /sign-in/email, /email-otp/...,
#                     /sign-in/social, /get-session (the JWT comes in its
#                     set-auth-jwt header), /token/anonymous, /sign-out, /delete-user
#
# The session is Neon Auth's cookie (an opaque token), kept in the keystore,
# encrypted for this Windows account. The JWT made from it lasts 15 minutes
# and is fetched again when it runs out. A guest - anyone not signed in - reads
# with an anonymous JWT; writing needs an account.
#
# Staying signed in: "Keep me signed in" (on unless unticked) keeps the session
# 30 days past its last use, and signing out is the only other way it ends. Neon
# itself ends a session 7 days after its last use (Better Auth's default, not
# settable on Neon), and renews it - at most once a day - whenever it is used:
# the studio uses it each time it starts and opens the community. Unticked, it
# lasts only until the studio closes (ended on Neon at the next start).
#
# Neon's Data API now and then runs a call without the caller's account (seen:
# a few calls in a hundred, when several run at once) - the database then sees a
# guest. So "signed out" is believed only from Neon Auth (the session itself);
# the database saying so is asked again, and a write refused for want of an
# account is tried again before it is reported.
#
# Google from a desktop app: Google's page opens in the browser; Neon Auth then
# sends the browser to a small listener here - http://localhost on a fixed port,
# because Neon trusts localhost (any port) by itself while the studio's own port
# changes every run - with a one-time verifier this module exchanges for the
# session.
#
# Pictures and plans come base64 in JSON (get_media, get_plan) and are kept in
# cache/community/ by id: they never change, so each is fetched once.
#
# A plan pulled from the community is someone else's data: only the plan's own
# keys are kept (missions.save), strings lose control characters and are capped,
# and the whole thing is size-capped before it is read.
#
# Where the community is: COMMUNITY below (the real Neon project), or
# IGISTUDIO_COMMUNITY=http://127.0.0.1:8790 for the stand-in on this machine
# (cloud/dev/server.mjs).
#
# The routes (handle()); each answers {ok, ...} or {ok: false, error, code}:
#   GET  /api/community/status                  {configured, signed_in, profile, suggest, keep, until}
#   POST /api/community/rpc/<fn>   {p}          a database function the editor may call as it is (PASS)
#   GET  /api/community/media/<id>              a picture (kept)
#   GET  /api/community/avatar?u=<url>          a Google profile picture (kept)
#   GET  /api/community/plan/<id>?v=<version>   {mission: {name, description, base, plan, version}}
#   GET  /api/community/updates                 {updates: {mission id here: newer version there}}
#   GET  /api/community/precheck?mission=<id>   {unchanged, origin, lineage, published, picture}: before sharing
#                                               (a link to a mission deleted there is dropped first)
#   POST /api/community/unlink {id}             that mission deleted there: no mission here is shared as it
#   POST /api/community/auth/signup {email, password, name}, auth/verify {email, code},
#        auth/resend {email, kind}, auth/signin {email, password}, auth/reset {email, code, password},
#        auth/signout, account/delete; each sign-in takes keep (default true): kept for 30 days
#   POST /api/community/auth/keep {keep}        signed in: kept on this PC (30 days), or only until the studio closes
#   POST /api/community/auth/google {keep}      {url}; GET it: {state: waiting, done, failed; signed_in}
#   POST /api/community/auth/google-again       the same Google page opened again (not a new sign-in)
#   POST /api/community/auth/google-cancel      given up: none of its pages signs in any more
#   POST /api/community/auth/continue {keep}    back in as the account signed out of last ("Continue as"), no browser
#   POST /api/community/auth/forget             that account forgotten, and its session ended on Neon
#   POST /api/community/avatar {data}           a picture of you: {id}
#   POST /api/community/pull {id, version}      {mission}: a mission of yours now
#   POST /api/community/publish {mission, form} {id, version}: shared, or a new version (form.mode "update")
import base64, gzip, hashlib, html, json, os, pathlib, re, sys, threading, time, urllib.error, urllib.parse
import urllib.request, uuid, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from studio import keystore, paths
from studio.server import missions as MS

# The real project's two public addresses (Neon console: the Data API, and
# Neon Auth's URL). Nothing secret: what may be done is decided by the database.
COMMUNITY = {"data": "https://ep-withered-tooth-b47e9u86.apirest.c-6.us-east-2.aws.neon.tech/neondb/rest/v1",
             "auth": "https://ep-withered-tooth-b47e9u86.neonauth.c-6.us-east-2.aws.neon.tech/neondb/auth"}

# where Google sends the browser back to: the first of these that is free. Below
# 49152: Windows (Hyper-V, WSL, Docker) reserves blocks of ports above it, which
# move from one boot to the next
LISTEN_PORTS = (38461, 41923, 45127)
FORMAT_VERSION = 2                         # the export format a shared plan is in
# the keystore's name for the session: {cookies, keep, until, profile} - Neon Auth's
# cookies; kept past this run?; kept until (30 days past its last use); the account as last seen
KEY = "community-session"
KEEP_DAYS = 30
# the account signed out of last: its session kept (still valid on Neon) so it
# can come back with "Continue as" and no browser; {cookies, who}
REMEMBER = "community-remembered"
PLAN_MAX = 20 * 1024 * 1024                # a plan, unpacked
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
# what the editor may call as it is; the rest go through the routes below
PASS = {"me", "list_missions", "get_mission", "remixes", "list_comments", "get_profile", "handle_free", "community_stats",
        "name_free", "mission_versions", "set_vote", "add_comment", "edit_comment", "delete_comment",
        "report", "save_profile", "update_details", "set_status", "delete_mission", "mod_reports",
        "mod_act", "set_role"}
# Google's profile pictures, the only pictures fetched from elsewhere
AVATAR_HOST = re.compile(r"^https://lh[0-9]+\.googleusercontent\.com/[A-Za-z0-9_\-/=.]+$")


class CommunityError(Exception):
    def __init__(self, message, status=400, code=None):
        super().__init__(message)
        self.status, self.code = status, code


def endpoints():
    base = os.environ.get("IGISTUDIO_COMMUNITY", "").rstrip("/")
    if base:
        return base + "/neondb/rest/v1", base + "/neondb/auth"
    return COMMUNITY["data"].rstrip("/"), COMMUNITY["auth"].rstrip("/")


def configured():
    d, a = endpoints()
    return bool(d and a)


def _version():
    return __import__("studio").__version__


# ------------------------------------------------------------------ HTTP
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


_open = urllib.request.build_opener(_NoRedirect).open


def _http(method, url, body=None, headers=None, timeout=20):
    data = json.dumps(body).encode() if body is not None else None
    h = {"Accept": "application/json", "User-Agent": "IGI-Studio/" + _version()}
    if data is not None:
        h["Content-Type"] = "application/json"
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with _open(req, timeout=timeout) as r:
            raw = r.read()
            status, hdrs = r.status, r.headers
    except urllib.error.HTTPError as e:
        raw, status, hdrs = e.read(), e.code, e.headers
    except (urllib.error.URLError, TimeoutError, OSError):
        raise CommunityError("The community can't be reached - check your internet connection.", 503, "offline")
    try:
        j = json.loads(raw) if raw and raw.strip() else None
    except ValueError:
        j = None
    return status, hdrs, j


# ------------------------------------------------------------------ the session
_lock = threading.RLock()
_S = {"cookies": None, "jwt": None, "exp": 0, "anon": None, "anon_exp": 0, "keep": True, "until": 0, "profile": None}


def _load():
    """The session kept here, read once a run. One kept only for its own run, or not used for
    KEEP_DAYS, ends now - on Neon too."""
    try:
        raw = json.loads(keystore.get(KEY) or "{}")
    except Exception:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    if raw and "cookies" not in raw:
        # kept by a studio from before "Keep me signed in": the cookies alone, kept from now
        raw = {"cookies": raw, "keep": True, "until": time.time() + KEEP_DAYS * 86400}
    cookies = raw.get("cookies") if isinstance(raw.get("cookies"), dict) else {}
    keep = raw.get("keep") is not False
    try:
        until = float(raw.get("until") or 0)
    except (TypeError, ValueError):
        until = 0
    if cookies and (not keep or until < time.time()):
        _log("the session kept here ended: %s" % ("it was for one run of the studio" if not keep
                                                    else "not used for %d days" % KEEP_DAYS))
        _end_on_neon(cookies)
        keystore.drop(KEY)
        cookies = {}
    profile = raw.get("profile") if cookies and isinstance(raw.get("profile"), dict) else None
    _S.update(cookies=cookies, keep=keep if cookies else True, until=until if cookies else 0, profile=profile)


def _cookies():
    if _S["cookies"] is None:
        with _lock:
            if _S["cookies"] is None:
                _load()
    return _S["cookies"]


def _save():
    """The session into the keystore as it is now (out of it when there is none)."""
    jar = _S["cookies"] or {}
    if any(k.endswith("session_token") for k in jar):
        keystore.put(KEY, json.dumps({"cookies": jar, "keep": _S["keep"], "until": _S["until"], "profile": _S["profile"]}))
    else:
        keystore.drop(KEY)


def _touch(profile):
    """The session used, and working: kept another KEEP_DAYS from now, with the account as seen
    (written down when that changes, or at most once an hour)."""
    now = time.time()
    if profile != _S["profile"] or _S["until"] < now + KEEP_DAYS * 86400 - 3600:
        _S["profile"], _S["until"] = profile, now + KEEP_DAYS * 86400
        _save()


def _keep_cookies(hdrs):
    """Neon Auth's Set-Cookie headers into the kept session (a cleared one out)."""
    got = hdrs.get_all("Set-Cookie") if hdrs else None
    if not got:
        return
    jar = dict(_cookies())
    for line in got:
        part = line.split(";", 1)[0]
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        name, value = name.strip(), urllib.parse.unquote(value.strip())
        gone = not value or re.search(r"max-age=0\b", line, re.I) or re.search(r"expires=thu, 01 jan 1970", line, re.I)
        if gone:
            jar.pop(name, None)
        else:
            jar[name] = value
    _S["cookies"] = jar
    _S["jwt"], _S["exp"] = None, 0
    if any(k.endswith("session_token") for k in jar):
        _S["until"] = time.time() + KEEP_DAYS * 86400
    _save()


def _forget(why=None):
    """No session here any more. why: written to the log when there was one (a sign-out should
    always be explainable)."""
    if why and signed_in():
        _log("signed out: %s" % why)
    _S.update(cookies={}, jwt=None, exp=0, profile=None, until=0, keep=True)
    keystore.drop(KEY)


def _cookie_header():
    return "; ".join("%s=%s" % (k, urllib.parse.quote(v, safe="")) for k, v in _cookies().items())


def signed_in():
    return any(k.endswith("session_token") for k in _cookies())


def _origin():
    # localhost, not 127.0.0.1: Neon Auth trusts any localhost port without being told
    return "http://localhost:%d" % LISTEN_PORTS[0]


def _claims(tok):
    try:
        body = tok.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except Exception:
        return {}


def _auth(method, path, body=None, query=None):
    _, a = endpoints()
    if not a:
        raise CommunityError("The community is not open yet.", 503, "closed")
    url = a + path + ("?" + urllib.parse.urlencode(query) if query else "")
    h = {"Origin": _origin()}
    if _cookies():
        h["Cookie"] = _cookie_header()
    status, hdrs, j = _http(method, url, body, h)
    _keep_cookies(hdrs)
    return status, hdrs, j


AUTH_ERRORS = {
    "INVALID_EMAIL_OR_PASSWORD": "That email and password don't match.",
    "USER_ALREADY_EXISTS": "There's already an account with that email - sign in instead.",
    "USER_ALREADY_EXISTS_USE_ANOTHER_EMAIL": "There's already an account with that email - sign in instead.",
    "INVALID_OTP": "That code is wrong or has expired.",
    "OTP_EXPIRED": "That code has expired - send a new one.",
    "TOO_MANY_ATTEMPTS": "Too many tries - wait a minute.",
    "PASSWORD_TOO_SHORT": "The password needs at least 8 characters.",
    "PASSWORD_TOO_LONG": "That password is too long.",
    "INVALID_EMAIL": "That doesn't look like an email address.",
    "INVALID_ORIGIN": "The community does not trust this studio yet (its sign-in address is not listed).",
}


def _auth_ok(status, j, what):
    if 200 <= status < 300:
        return j
    code = (j or {}).get("code") if isinstance(j, dict) else None
    if code == "EMAIL_NOT_VERIFIED":
        raise CommunityError("Enter the code we emailed you to finish signing up.", 403, "verify")
    if status == 429:
        raise CommunityError(AUTH_ERRORS["TOO_MANY_ATTEMPTS"], 429, "slow")
    msg = AUTH_ERRORS.get(code) or ((j or {}).get("message") if isinstance(j, dict) else None) or ("%s failed." % what)
    raise CommunityError(msg, status if status >= 400 else 400, code)


def _user_jwt():
    """The JWT for the account signed in here, or None (not signed in, or the session is over)."""
    with _lock:
        if not signed_in():
            return None
        if _S["jwt"] and _S["exp"] > time.time() + 30:
            return _S["jwt"]
        for again in (False, True):
            if again:
                time.sleep(0.6)
            status, hdrs, j = _auth("GET", "/get-session")
            if status == 200 and isinstance(j, dict) and j.get("session"):
                tok = hdrs.get("set-auth-jwt") if hdrs else None
                if not tok:
                    s2, _, j2 = _auth("GET", "/token")
                    tok = (j2 or {}).get("token") if s2 == 200 and isinstance(j2, dict) else None
                if tok:
                    _S["jwt"], _S["exp"] = tok, float(_claims(tok).get("exp") or time.time() + 600)
                    return tok
            if status not in (200, 401):
                raise CommunityError("The community's sign-in is not answering - try again in a moment.", 503, "offline")
        # said twice: the session ran out, was ended elsewhere, or gives no key
        _forget("Neon Auth no longer takes the session (%s)" % status)
        return None


def _anon_jwt():
    with _lock:
        if _S["anon"] and _S["anon_exp"] > time.time() + 30:
            return _S["anon"]
        status, _, j = _auth("GET", "/token/anonymous")
        if status != 200 or not isinstance(j, dict) or not j.get("token"):
            raise CommunityError("The community can't be browsed without an account right now.", 503, "anon")
        _S["anon"], _S["anon_exp"] = j["token"], float(j.get("expires_at") or time.time() + 600)
        return _S["anon"]


SIGN_IN_FIRST = "Sign in to the community first."      # community.member()'s own words


def rpc(fn, p=None, need_user=False):
    """public.<fn>(p) on the Data API, as the account signed in here or as a guest."""
    d, _ = endpoints()
    if not d:
        raise CommunityError("The community is not open yet.", 503, "closed")
    renewed, misses = False, 0
    while True:
        tok = _user_jwt()
        mine = bool(tok)
        if not tok:
            if need_user:
                raise CommunityError("Sign in to the community first.", 401, "signin")
            tok = _anon_jwt()
        status, _, j = _http("POST", "%s/rpc/%s" % (d, fn), {"p": p or {}}, {"Authorization": "Bearer " + tok})
        if status == 200:
            return j
        code = (j or {}).get("code") if isinstance(j, dict) else None
        msg = (j or {}).get("message") if isinstance(j, dict) else None
        if status == 401 and code in ("PGRST301", "PGRST302", "PGRST303") and not renewed:
            renewed = True
            with _lock:
                _S["jwt"] = _S["anon"] = None
                _S["exp"] = _S["anon_exp"] = 0
            continue
        # sent as the account, refused as a guest: the Data API lost who asked (see the top)
        if mine and misses < 2 and (code == "42501" or status in (401, 403) or (code == "P0001" and msg == SIGN_IN_FIRST)):
            misses += 1
            _log("%s: the database did not see the account; asking again" % fn)
            time.sleep(0.3 * misses)
            continue
        if code == "P0001" and msg:
            raise CommunityError(msg, 400, "rule")
        if code == "42501" or status in (401, 403):
            raise CommunityError("Sign in to the community first.", 401, "signin")
        if status == 404 or code in ("42883", "PGRST202"):
            raise CommunityError("This studio and the community don't match - update the studio.", 404, "version")
        if status == 413:
            raise CommunityError("That is too big to share.", 413, "big")
        raise CommunityError("The community had a problem - try again in a moment.", 502, code)


# ------------------------------------------------------------------ accounts
def _me():
    """The database's own view of the account signed in here, or None when it does not see one -
    asked again a few times first (see the top: now and then a call reaches it as a guest's)."""
    for wait in (0, 0.25, 0.6, 1.2):
        if wait:
            time.sleep(wait)
        me = rpc("me", need_user=True)
        if isinstance(me, dict) and me.get("signed_in"):
            return me
    return None


def status():
    out = {"configured": configured(), "signed_in": False, "profile": None}
    if not out["configured"]:
        return out
    if signed_in():
        try:
            # a session here that the community no longer takes is gone (_user_jwt forgets it):
            # signed in means a session that works, never "some cookies"
            if _user_jwt():
                me = _me()
                if me:
                    _touch(me.get("profile"))
                    out.update(signed_in=True, profile=me.get("profile"), suggest=me.get("suggest"))
                else:
                    # the session holds - Neon Auth says so - but the database kept missing it: still
                    # signed in, as the account last seen; the editor asks again in a moment
                    _log("status: the database did not see the account (asked 4 times); the session holds")
                    out.update(signed_in=True, profile=_S["profile"], unsure=True)
        except CommunityError as e:
            if e.code != "offline":
                raise
            out.update(signed_in=True, profile=_S["profile"], offline=True)
    if out["signed_in"]:
        out.update(keep=_S["keep"], until=int(_S["until"]) if _S["keep"] else None)
    else:
        r = remembered()
        if r:
            out["remembered"] = r
    return out


# ------------------------------------------------------------------ the account signed out of last
def _remembered_raw():
    try:
        r = json.loads(keystore.get(REMEMBER) or "null")
    except Exception:
        return None
    return r if isinstance(r, dict) and isinstance(r.get("cookies"), dict) and r.get("who") else None


def remembered():
    """Who signed out last here, to offer "Continue as" (handle, name, picture), or None."""
    r = _remembered_raw()
    return r["who"] if r else None


def _end_on_neon(cookies):
    """A session ended on Neon too, not only forgotten here."""
    _, a = endpoints()
    if not a or not cookies:
        return
    h = {"Origin": _origin(),
         "Cookie": "; ".join("%s=%s" % (k, urllib.parse.quote(v, safe="")) for k, v in cookies.items())}
    try:
        _http("POST", a + "/sign-out", {}, h)
    except CommunityError:
        pass


def _drop_remembered(end=True):
    r = _remembered_raw()
    keystore.drop(REMEMBER)
    if r and end:
        _end_on_neon(r["cookies"])


def forget_remembered():
    _drop_remembered(end=True)
    return status()


def continue_remembered(keep=True):
    """Back in as the account signed out of last, with no browser - if its session still holds."""
    r = _remembered_raw()
    if not r:
        raise CommunityError("Sign in again.", 400, "signin")
    with _lock:
        _forget("back in as the account remembered")
        _S["cookies"] = dict(r["cookies"])
        tok = _user_jwt()                      # forgets it when it no longer holds
        if not tok:
            _forget()
            keystore.drop(REMEMBER)
            raise CommunityError("That sign-in has run out - sign in again.", 401, "expired")
        _S.update(keep=bool(keep), until=time.time() + KEEP_DAYS * 86400, profile=r.get("who"))
        _save()
        keystore.drop(REMEMBER)
    _log("signed in again as the account remembered")
    return status()


def set_keep(keep):
    """Signed in: kept on this PC for KEEP_DAYS past its last use, or only until the studio closes."""
    if not signed_in():
        raise CommunityError("Sign in to the community first.", 401, "signin")
    with _lock:
        _S.update(keep=bool(keep), until=time.time() + KEEP_DAYS * 86400)
        _save()
    return status()


def sign_up(email, password, name, keep=True):
    _S["keep"] = bool(keep)
    st, _, j = _auth("POST", "/sign-up/email", {"email": (email or "").strip(), "password": password or "",
                                                "name": (name or "").strip()[:60] or (email or "").split("@")[0]})
    _auth_ok(st, j, "Signing up")
    if signed_in():
        return status()
    return {"verify": True, "email": email}


def verify(email, code, keep=True):
    _S["keep"] = bool(keep)
    st, _, j = _auth("POST", "/email-otp/verify-email", {"email": (email or "").strip(), "otp": (code or "").strip()})
    _auth_ok(st, j, "Checking the code")
    if not signed_in():
        raise CommunityError("The code was right - now sign in with your password.", 400, "signin")
    _drop_remembered(end=True)
    return status()


def resend(email, kind="email-verification"):
    if kind not in ("email-verification", "forget-password"):
        kind = "email-verification"
    email = (email or "").strip()
    st, _, j = _auth("POST", "/email-otp/send-verification-otp", {"email": email, "type": kind})
    if st == 404 and kind == "email-verification":
        # without the code plugin's own call: Better Auth's, which sends what the project is set to (a code)
        st, _, j = _auth("POST", "/send-verification-email", {"email": email, "callbackURL": _origin()})
    _auth_ok(st, j, "Sending the code")
    return {"sent": True}


def sign_in(email, password, keep=True):
    _forget("signing in again")
    _S["keep"] = bool(keep)
    st, _, j = _auth("POST", "/sign-in/email", {"email": (email or "").strip(), "password": password or ""})
    _auth_ok(st, j, "Signing in")
    _drop_remembered(end=True)
    return status()


def reset_password(email, code, password, keep=True):
    st, _, j = _auth("POST", "/email-otp/reset-password", {"email": (email or "").strip(),
                                                           "otp": (code or "").strip(), "password": password or ""})
    _auth_ok(st, j, "Setting the password")
    return sign_in(email, password, keep)


def sign_out(forget=False):
    """Signed out here. The account is remembered (its session kept, encrypted) for "Continue as",
    unless forget: then it is ended on Neon too."""
    if signed_in():
        who = None
        # an account kept only for this run is not remembered past it either
        if not forget and _S["keep"]:
            try:
                p = (rpc("me", need_user=True) or {}).get("profile")
                if p:
                    who = {k: p.get(k) for k in ("handle", "name", "avatar", "avatar_url")}
            except CommunityError:
                pass
        if who:
            _drop_remembered(end=True)            # one remembered account: the last
            keystore.put(REMEMBER, json.dumps({"cookies": dict(_cookies()), "who": who}))
        else:
            _end_on_neon(dict(_cookies()))
    _forget("signed out in the studio")
    google_cancel()
    return status()


def delete_account():
    rpc("delete_my_data", {}, need_user=True)
    st, _, j = _auth("POST", "/delete-user", {})
    _forget("the account was deleted")
    if not 200 <= st < 300:
        raise CommunityError("Your missions, votes and comments are gone, but the account itself was not deleted: "
                             "sign in once more and try again.", 400, "partial")
    return status()


# ------------------------------------------------------------------ Google
# Any sign-in this studio started in the last ten minutes is taken when the
# browser comes back: a second click must not throw the first away, since its
# page may still be finishing in a browser tab behind the studio's window. The
# listener stays up until one has come back, or the ten minutes are over.
NONCE_LIFE = 600
_G = {"nonces": {}, "servers": [], "port": None, "url": None, "error": None, "done": 0, "started": 0, "keep": True}


def _log(msg):
    sys.stderr.write("   community: %s\n" % msg)


class _Callback(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path != "/callback":
            return self._page(404, "old", "Nothing here", "This address only answers the studio's sign-in.")
        nonce = (q.get("s") or [""])[0]
        t = _G["nonces"].get(nonce)
        if not t or time.time() - t > NONCE_LIFE:
            _log("google: a sign-in came back that this studio did not start, or too late")
            return self._page(410, "old", "This sign-in has expired",
                              "It was cancelled in the studio, or started too long ago. Go back to IGI Studio and sign in again.")
        v = (q.get("neon_auth_session_verifier") or [""])[0]
        err = (q.get("error") or [""])[0]
        try:
            if err or not v:
                raise CommunityError("Google sign-in did not finish%s." % (" (%s)" % err if err else ""))
            with _lock:
                _S["keep"] = _G["keep"]
                st, _, j = _auth("GET", "/get-session", query={"neon_auth_session_verifier": v})
                if st != 200 or not (isinstance(j, dict) and j.get("session")) or not signed_in():
                    raise CommunityError("Google sign-in did not finish.")
            user = j.get("user") if isinstance(j.get("user"), dict) else {}
            done = time.time()
            # no other page of these can sign in later
            _G.update(done=done, error=None, nonces={})
            _drop_remembered(end=True)
            _log("google: signed in")
            self._page(200, "ok", "You\u2019re signed in", "Google confirmed it\u2019s you.", user)
            # the listener goes, unless another sign-in has started since
            _later(2.0, lambda: _G["started"] <= done and _stop_listener())
        except CommunityError as e:
            _G["error"] = str(e)
            _log("google: %s" % e)
            self._page(400, "bad", "Sign-in didn\u2019t finish", str(e) + " Go back to IGI Studio and try again.")

    def _page(self, code, kind, title, text, user=None):
        body = _browser_page(kind, title, text, user).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


# The page the browser shows when it comes back to the studio: the studio's
# look, a mark (a check, a cross, a clock), who signed in, and what next. Only
# what it holds itself: the logo inline, Windows' own condensed face.
_LOGO = None


def _logo():
    global _LOGO
    if _LOGO is None:
        f = pathlib.Path(__file__).resolve().parents[2] / "editor" / "icon.png"
        try:
            _LOGO = "data:image/png;base64," + base64.b64encode(f.read_bytes()).decode()
        except OSError:
            _LOGO = ""
    return _LOGO


_MARKS = {
    "ok": ('#8dff9a', '<path class="draw" d="M30 50l13 13 27-28"/>'),
    "bad": ('#ff6b5a', '<path class="draw" d="M35 35l30 30M65 35L35 65"/>'),
    "old": ('#ffd24a', '<path class="draw" d="M50 30v21l13 8"/>'),
}


def _browser_page(kind, title, text, user=None):
    color, inner = _MARKS.get(kind, _MARKS["old"])
    who = ""
    if kind == "ok" and user:
        img = user.get("image") or ""
        pic = ('<img src="%s" alt="" referrerpolicy="no-referrer">' % html.escape(img)) if AVATAR_HOST.match(img) else \
              '<span class="ini">%s</span>' % html.escape((user.get("name") or user.get("email") or "?")[:1].upper())
        who = ('<div class="who">%s<div><b>%s</b><span>%s</span></div></div>' %
               (pic, html.escape(user.get("name") or ""), html.escape(user.get("email") or "")))
    nxt = ('Go back to <b>IGI Studio</b>: it has carried on by itself. You can close this tab.' if kind == "ok"
           else 'Go back to <b>IGI Studio</b>. You can close this tab.')
    logo = _logo()
    return """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>%(title)s \u00b7 IGI Studio</title>
<style>
:root{--g:#8dff9a;--gold:#ffd24a;--ink:#eaffec;--muted:#9fe0a7;--faint:#5fa868;--line:#2a6b33;--mark:%(color)s}
*{box-sizing:border-box}
html,body{height:100%%}
body{margin:0;display:grid;place-items:center;padding:24px;color:var(--ink);font:15px/1.55 "Segoe UI",system-ui,sans-serif;
  background:radial-gradient(900px 520px at 50%% -12%%,rgba(80,255,110,.17),transparent 70%%),
    linear-gradient(rgba(141,255,154,.045) 1px,transparent 1px) 0 0/32px 32px,
    linear-gradient(90deg,rgba(141,255,154,.045) 1px,transparent 1px) 0 0/32px 32px,#06150a}
.card{position:relative;width:min(500px,100%%);padding:38px 38px 30px;text-align:center;border:1px solid var(--line);border-radius:14px;
  background:linear-gradient(180deg,rgba(16,48,22,.96),rgba(7,25,10,.96));box-shadow:0 30px 80px rgba(0,0,0,.6),0 0 46px rgba(141,255,154,.08);
  animation:rise .5s cubic-bezier(.2,.9,.3,1) both}
.card::before,.card::after{content:"";position:absolute;width:26px;height:26px;border:2px solid var(--g);filter:drop-shadow(0 0 6px rgba(141,255,154,.5))}
.card::before{left:-7px;top:-7px;border-right:0;border-bottom:0}
.card::after{right:-7px;bottom:-7px;border-left:0;border-top:0}
@keyframes rise{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
.brand{display:flex;align-items:center;justify-content:center;gap:10px;margin:0 0 28px;font:600 15px Bahnschrift,"Arial Narrow",sans-serif;
  letter-spacing:.22em;text-transform:uppercase}
.brand img{width:30px;height:30px;filter:drop-shadow(0 0 8px rgba(141,255,154,.55))}
.brand i{font-style:normal;color:var(--g)}
.mark{display:block;width:104px;height:104px;margin:0 auto 18px;filter:drop-shadow(0 0 18px var(--mark))}
.mark circle{fill:none;stroke:var(--mark);stroke-width:3;opacity:.35}
.mark .ring{opacity:1;stroke-dasharray:283;stroke-dashoffset:283;animation:draw .7s .1s ease-out forwards;transform:rotate(-90deg);transform-origin:50%% 50%%}
.mark .draw{fill:none;stroke:var(--mark);stroke-width:6;stroke-linecap:round;stroke-linejoin:round;stroke-dasharray:80;stroke-dashoffset:80;
  animation:draw .45s .7s ease-out forwards}
@keyframes draw{to{stroke-dashoffset:0}}
h1{margin:0 0 6px;font:600 36px/1.1 Bahnschrift,"Arial Narrow",sans-serif;letter-spacing:.01em}
p{margin:0;color:var(--muted)}
.who{display:inline-flex;align-items:center;gap:12px;margin:20px auto 2px;padding:9px 18px 9px 9px;border:1px solid var(--line);border-radius:40px;
  background:rgba(3,11,4,.55);text-align:left;max-width:100%%}
.who img,.who .ini{width:42px;height:42px;border-radius:50%%;flex:none;border:2px solid var(--g)}
.who .ini{display:grid;place-items:center;font:700 19px Bahnschrift,sans-serif;color:#06140a;background:linear-gradient(135deg,#b3ffbc,#4fd062)}
.who b{display:block;font-size:15px;color:var(--ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.who span{display:block;font-size:12.5px;color:var(--faint);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.next{margin-top:24px;padding-top:18px;border-top:1px solid var(--line);font-size:14px;color:var(--muted)}
.next b{color:var(--gold);font-weight:600}
@media (prefers-reduced-motion:reduce){.card,.mark .ring,.mark .draw{animation:none;stroke-dashoffset:0}}
</style>
<main class="card">
  <div class="brand">%(logo)sIGI Studio <i>Community</i></div>
  <svg class="mark" viewBox="0 0 100 100" aria-hidden="true"><circle cx="50" cy="50" r="45"/><circle class="ring" cx="50" cy="50" r="45"/>%(inner)s</svg>
  <h1>%(title)s</h1>
  <p>%(text)s</p>
  %(who)s
  <div class="next">%(next)s</div>
</main></html>""" % {"title": html.escape(title), "text": html.escape(text), "color": color, "inner": inner, "who": who,
                     "next": nxt, "logo": ('<img src="%s" alt="">' % logo) if logo else ""}


def _later(seconds, fn):
    """fn in a while, on a thread that never keeps the studio from closing"""
    t = threading.Timer(seconds, fn)
    t.daemon = True
    t.start()


def _stop_listener():
    servers, _G["servers"] = _G.get("servers") or [], []
    for srv in servers:
        try:
            srv.shutdown()
            srv.server_close()
        except Exception:
            pass


class _Server4(ThreadingHTTPServer):
    # the port is ours alone: HTTPServer asks for SO_REUSEADDR, which on Windows lets a second
    # program listen on the same port - and the browser's return could reach the wrong one
    allow_reuse_address = False

    def server_bind(self):
        so = getattr(__import__("socket"), "SO_EXCLUSIVEADDRUSE", None)
        if so is not None:
            self.socket.setsockopt(__import__("socket").SOL_SOCKET, so, 1)
        ThreadingHTTPServer.server_bind(self)


class _Server6(_Server4):
    address_family = __import__("socket").AF_INET6


def _listen(port):
    """The listener on localhost's two addresses (a browser may try either), or None when the port is taken."""
    try:
        four = _Server4(("127.0.0.1", port), _Callback)
    except OSError:
        return None
    out = [four]
    try:
        out.append(_Server6(("::1", port), _Callback))
    except OSError:
        pass                                    # no IPv6 here: the browser falls back to 127.0.0.1
    return out


def google_cancel():
    """The sign-in given up: none of its pages can sign in any more."""
    _G.update(nonces={}, error=None, done=0, url=None)
    _stop_listener()
    return {"cancelled": True}


def google_start(open_browser=True, keep=True):
    """Starts a Google sign-in: the listener (kept if it is up), and Google's page (opened in the browser).
    Nothing of an earlier account stays in the way: only this sign-in coming back signs in."""
    with _lock:
        if signed_in():
            _forget("signing in with Google again")
    _G["keep"] = bool(keep)
    now = time.time()
    _G["nonces"] = {k: t for k, t in _G["nonces"].items() if now - t < NONCE_LIFE}
    if not _G["servers"]:
        servers = None
        for port in LISTEN_PORTS:
            servers = _listen(port)
            if servers:
                break
        if not servers:
            raise CommunityError("Google sign-in needs one of the ports %s free on this computer." %
                                 ", ".join(map(str, LISTEN_PORTS)), 503, "port")
        _G.update(servers=servers, port=servers[0].server_address[1])
        for srv in servers:
            threading.Thread(target=srv.serve_forever, daemon=True).start()
    nonce = uuid.uuid4().hex
    _G["nonces"][nonce] = now
    _G.update(error=None, done=0, started=now)
    _later(NONCE_LIFE + 5, lambda: time.time() - _G["started"] >= NONCE_LIFE and _stop_listener())
    back = "http://localhost:%d/callback?s=%s" % (_G["port"], nonce)
    st, _, j = _auth("POST", "/sign-in/social", {"provider": "google", "callbackURL": back,
                                                 "errorCallbackURL": back, "disableRedirect": True})
    j = _auth_ok(st, j, "Google sign-in")
    url = (j or {}).get("url") if isinstance(j, dict) else None
    if not url:
        raise CommunityError("Google sign-in is not available right now.", 503, "google")
    _G["url"] = url
    _log("google: sign-in started (listening on localhost:%d)" % _G["port"])
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    return {"url": url, "state": "waiting"}


def google_reopen():
    """Google's page again, for the sign-in already started (not a new one)."""
    if not _G["url"] or time.time() - _G["started"] > NONCE_LIFE:
        raise CommunityError("Start the sign-in again.", 400, "google")
    try:
        webbrowser.open(_G["url"])
    except Exception:
        pass
    return {"url": _G["url"]}


def google_state():
    """waiting; done (a page of this sign-in came back, and the studio is signed in); or failed (why)"""
    state = "done" if _G["done"] and signed_in() else "failed" if _G["error"] else "waiting"
    return {"state": state, "error": _G["error"]}


# ------------------------------------------------------------------ pictures and plans
def _cache():
    d = paths.cache() / "community"
    (d / "media").mkdir(parents=True, exist_ok=True)
    (d / "plans").mkdir(parents=True, exist_ok=True)
    return d


EXT = {"image/webp": ".webp", "image/png": ".png", "image/jpeg": ".jpg", "application/gzip": ".gz"}
MIME = {v: k for k, v in EXT.items()}


def media(mid):
    """(mime, bytes) of a community picture, from the cache or the community."""
    if not UUID.match(mid or ""):
        raise CommunityError("Not a picture.", 404)
    d = _cache() / "media"
    for f in d.glob(mid + ".*"):
        return MIME.get(f.suffix, "application/octet-stream"), f.read_bytes()
    j = rpc("get_media", {"id": mid})
    mime = j.get("mime")
    if mime not in EXT or mime == "application/gzip":
        raise CommunityError("Not a picture.", 404)
    b = base64.b64decode(j.get("data") or "")
    tmp = d / (mid + ".tmp")
    tmp.write_bytes(b)
    tmp.replace(d / (mid + EXT[mime]))
    return mime, b


def avatar(url):
    """A Google profile picture (the only kind fetched from elsewhere), kept like the rest."""
    if not AVATAR_HOST.match(url or ""):
        raise CommunityError("Not a picture.", 404)
    d = _cache() / "media"
    f = d / ("g-" + hashlib.sha256(url.encode()).hexdigest()[:32] + ".img")
    if f.exists():
        b = f.read_bytes()
    else:
        req = urllib.request.Request(url, headers={"User-Agent": "IGI-Studio/" + _version()})
        try:
            with _open(req, timeout=15) as r:
                b = r.read(300000)
        except Exception:
            raise CommunityError("Not a picture.", 404)
        f.write_bytes(b)
    mime = "image/png" if b[:8] == b"\x89PNG\r\n\x1a\n" else "image/webp" if b[8:12] == b"WEBP" else "image/jpeg"
    return mime, b


def _no_constants(name):
    raise ValueError("not a number: %s" % name)


def _clean(v, depth=0):
    """Someone else's JSON, made safe to keep: depth, string length, control characters."""
    if depth > 24:
        raise ValueError("too deep")
    if isinstance(v, dict):
        return {str(k)[:200]: _clean(x, depth + 1) for k, x in list(v.items())[:100000]}
    if isinstance(v, list):
        return [_clean(x, depth + 1) for x in v[:200000]]
    if isinstance(v, str):
        return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", v)[:20000]
    if isinstance(v, (bool, int, float)) or v is None:
        return v
    return None


def plan(cid, version=None):
    """A community mission's plan, as a mission file has it: {name, description, base, plan}."""
    if not UUID.match(cid or ""):
        raise CommunityError("Not a mission.", 404)
    d = _cache() / "plans"
    if version:
        f = d / ("%s@%d.json.gz" % (cid, int(version)))
        if f.exists():
            return _read_plan(f.read_bytes(), json.loads(f.with_suffix(".meta").read_text("utf-8")))
    j = rpc("get_plan", {"id": cid, "version": int(version) if version else None})
    raw = base64.b64decode(j.get("data") or "")
    meta = {"id": cid, "version": j.get("version"), "sha256": j.get("sha256"), "name": j.get("name"),
            "format_version": j.get("format_version")}
    out = _read_plan(raw, meta)
    f = d / ("%s@%d.json.gz" % (cid, int(meta["version"])))
    f.write_bytes(raw)
    f.with_suffix(".meta").write_text(json.dumps(meta), "utf-8")
    return out


def _read_plan(raw, meta):
    if (meta.get("format_version") or 0) > FORMAT_VERSION:
        raise CommunityError("This mission was made with a newer studio - update the studio to open it.", 400, "newer")
    try:
        with gzip.GzipFile(fileobj=__import__("io").BytesIO(raw)) as g:
            body = g.read(PLAN_MAX + 1)
        if len(body) > PLAN_MAX:
            raise ValueError("too big")
        d = _clean(json.loads(body.decode("utf-8"), parse_constant=_no_constants))
    except (OSError, ValueError, UnicodeDecodeError):
        raise CommunityError("That mission's plan could not be read.", 400, "bad")
    if not isinstance(d, dict) or not isinstance(d.get("plan"), dict) or not isinstance(d.get("base"), dict):
        raise CommunityError("That mission's plan could not be read.", 400, "bad")
    b = d["base"]
    lvl = b.get("level")
    if not isinstance(lvl, int) or not 1 <= lvl <= 14 or b.get("kind") not in ("copy", "empty"):
        raise CommunityError("That mission's plan could not be read.", 400, "bad")
    return {"name": str(d.get("name") or meta.get("name") or "Community mission")[:60],
            "description": str(d.get("description") or "")[:200],
            "base": {"level": lvl, "kind": b["kind"]}, "plan": d["plan"],
            "version": meta.get("version"), "sha256": meta.get("sha256"), "id": meta.get("id")}


def plan_sha(p):
    """The fingerprint of a plan: its JSON with sorted keys."""
    return hashlib.sha256(json.dumps(p, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                          .encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ pulling
def pull(cid, version=None):
    """A community mission made a mission of yours: its plan, picture, and where it came from."""
    info = rpc("get_mission", {"id": cid})
    p = plan(cid, version or info.get("version"))
    rpc("record_pull", {"id": cid, "version": p["version"]}, need_user=True)
    m = MS.create(p["name"], p["base"]["level"], p["base"]["kind"], p["description"])
    MS.save(m["id"], plan=p["plan"])
    m = MS.load(m["id"])                     # as the studio keeps it from now on
    if info.get("picture"):
        try:
            mime, b = media(info["picture"])
            if mime == "image/png":
                MS.set_picture(m["id"], b)
        except CommunityError:
            pass
    author = info.get("author") or {}
    origin = {"id": cid, "version": p["version"], "name": info.get("name"),
              "author": {"id": author.get("id"), "handle": author.get("handle"), "name": author.get("name")}}
    m = MS.set_community(m["id"], {
        "origin": origin,
        "lineage": (info.get("lineage") or [])[-49:] + [origin],
        # the plan as it is here right after pulling: "nothing changed" is this
        "base_sha": plan_sha(m["plan"]),
    })
    return m


def updates():
    """For each mission here pulled from the community: a newer version there, if any."""
    mine = MS.list_community()
    ids = sorted({c["origin"]["id"] for c in mine.values() if (c.get("origin") or {}).get("id")} |
                 {c["published"]["id"] for c in mine.values() if (c.get("published") or {}).get("id")})
    if not ids:
        return {}
    now = {x["id"]: x for x in rpc("mission_versions", {"ids": ids}).get("items") or []}
    # shared from here and deleted there since: the link goes (signed in, as its author would know)
    if signed_in():
        for pub in {c["published"]["id"] for c in mine.values() if (c.get("published") or {}).get("id")} - set(now):
            if _gone(pub):
                unlink(pub)
    out = {}
    for mid, c in mine.items():
        o = (c.get("origin") or {})
        if o.get("id") in now and (now[o["id"]]["version"] or 0) > (o.get("version") or 0):
            out[mid] = {"id": o["id"], "version": now[o["id"]]["version"], "name": now[o["id"]]["name"]}
    return out


# ------------------------------------------------------------------ sharing
def _data_url(s, kinds=("image/webp", "image/png", "image/jpeg")):
    m = re.match(r"^data:([a-z/]+);base64,(.+)$", s or "", re.S)
    if not m or m.group(1) not in kinds:
        raise CommunityError("A picture is missing - choose the cover again.", 400, "picture")
    return m.group(1), m.group(2)


def _upload(kind, mime, data_b64):
    return rpc("upload_media", {"kind": kind, "mime": mime, "data": data_b64}, need_user=True)["id"]


def publish(mid, form):
    """Shares a mission of yours (form: what the wizard asked), or a new version of one shared before."""
    m = MS.load(mid)
    c = m.get("community") or {}
    cur = plan_sha(m["plan"])
    origin = c.get("origin") or {}
    update = form.get("mode") == "update"
    if update and not (c.get("published") or {}).get("id"):
        raise CommunityError("This mission was not shared from here yet.", 400)
    if not update and origin.get("id") and c.get("base_sha") == cur:
        raise CommunityError("Nothing has changed since you pulled \"%s\" - change something before sharing it."
                             % (origin.get("name") or "it"), 400, "unchanged")
    doc = {"format": "igi-mission-studio", "version": FORMAT_VERSION, "name": form.get("name") or m["name"],
           "description": m.get("description", ""), "base": m["base"], "plan": m["plan"]}
    packed = gzip.compress(json.dumps(doc, separators=(",", ":")).encode("utf-8"), 9)
    ids = {"plan": _upload("plan", "application/gzip", base64.b64encode(packed).decode())}
    ids["cover"] = _upload("cover", *_data_url(form.get("cover")))
    ids["thumb"] = _upload("thumb", *_data_url(form.get("thumb")))
    ids["shots"] = [_upload("shot", *_data_url(s)) for s in (form.get("shots") or [])[:4]]
    ids["picture"] = None
    pic = MS.STORE / mid / MS.PICTURE
    if form.get("with_picture", True) and pic.exists() and pic.stat().st_size <= 300000:
        ids["picture"] = _upload("picture", "image/png", base64.b64encode(pic.read_bytes()).decode())
    p = {k: form.get(k) for k in ("name", "summary", "description", "difficulty", "tags", "play_minutes",
                                  "video_url", "allow_remix", "coauthors", "objectives", "facts", "notes")}
    p.update(ids, level=m["base"]["level"], kind=m["base"]["kind"], plan_sha256=cur,
             format_version=FORMAT_VERSION, studio_version=_version())
    if update:
        p["id"] = c["published"]["id"]
        r = rpc("publish_version", p, need_user=True)
    else:
        if origin.get("id"):
            p["parent"] = {"id": origin["id"], "version": origin.get("version")}
            p["lineage"] = c.get("lineage") or []
        r = rpc("publish_mission", p, need_user=True)
    MS.set_community(mid, dict(c, published={"id": r["id"], "version": r["version"], "sha": cur}))
    return r


def unlink(cid):
    """A mission of the community gone (deleted there): no mission here says it is shared as it any more."""
    n = 0
    for mid, c in MS.list_community().items():
        if (c.get("published") or {}).get("id") == cid:
            c = dict(c)
            c.pop("published", None)
            MS.set_community(mid, c)
            n += 1
    return {"unlinked": n}


def _gone(cid):
    """Is that mission no longer in the community at all? (Asked as its author: a hidden one is still there.
    Asked twice: a call the database takes for a guest's would not see a hidden one.)"""
    for wait in (0, 0.8):
        time.sleep(wait)
        try:
            rpc("get_mission", {"id": cid}, need_user=True)
            return False
        except CommunityError as e:
            if not (e.code == "rule" and "not in the community" in str(e)):
                return False
    return True


def precheck(mid):
    """What the share wizard needs to know about a mission here before it starts."""
    m = MS.load(mid)
    c = m.get("community") or {}
    pub = (c.get("published") or {}).get("id")
    if pub and _gone(pub):
        # deleted from the community since: it can only be shared anew
        unlink(pub)
        m = MS.load(mid)
        c = m.get("community") or {}
    o = c.get("origin") or {}
    return {"name": m["name"], "base": m["base"],
            "unchanged": bool(o.get("id")) and c.get("base_sha") == plan_sha(m["plan"]),
            "origin": o or None, "lineage": c.get("lineage") or [],
            "published": c.get("published") or None,
            "picture": (MS.STORE / mid / MS.PICTURE).exists()}


def upload_avatar(data_url):
    return {"id": _upload("avatar", *_data_url(data_url))}


# ------------------------------------------------------------------ the routes
def handle(method, path, query, body):
    """(status, JSON or (mime, bytes)) for /api/community/<route>."""
    route = path[len("/api/community/"):].split("?", 1)[0].strip("/")
    try:
        if method == "GET" and route == "status":
            return 200, dict(status(), ok=True)
        if not configured():
            raise CommunityError("The community is not open yet.", 503, "closed")
        m = re.match(r"^rpc/([a-z_]+)$", route)
        if m and method == "POST":
            if m.group(1) not in PASS:
                raise CommunityError("Not a community call.", 404)
            return 200, {"ok": True, "result": rpc(m.group(1), body.get("p") or {})}
        m = re.match(r"^media/([0-9a-f-]{36})$", route)
        if m and method == "GET":
            return 200, media(m.group(1))
        if route == "avatar" and method == "GET":
            return 200, avatar((query.get("u") or [""])[0])
        m = re.match(r"^plan/([0-9a-f-]{36})$", route)
        if m and method == "GET":
            v = (query.get("v") or [None])[0]
            return 200, {"ok": True, "mission": plan(m.group(1), int(v) if v and v.isdigit() else None)}
        if method == "GET" and route == "auth/google":
            return 200, dict(google_state(), ok=True)
        if method == "GET" and route == "updates":
            return 200, {"ok": True, "updates": updates()}
        if method == "POST" and route == "unlink":
            return 200, dict(unlink((body or {}).get("id")), ok=True)
        if method == "GET" and route == "precheck":
            return 200, dict(precheck((query.get("mission") or [""])[0]), ok=True)
        if method != "POST":
            raise CommunityError("Not a community call.", 404)
        b = body or {}
        keep = b.get("keep", True) is not False
        r = {
            "auth/signup": lambda: sign_up(b.get("email"), b.get("password"), b.get("name"), keep),
            "auth/verify": lambda: verify(b.get("email"), b.get("code"), keep),
            "auth/resend": lambda: resend(b.get("email"), b.get("kind")),
            "auth/signin": lambda: sign_in(b.get("email"), b.get("password"), keep),
            "auth/reset": lambda: reset_password(b.get("email"), b.get("code"), b.get("password"), keep),
            "auth/keep": lambda: set_keep(keep),
            "auth/google": lambda: google_start(b.get("open", True) is not False, keep),
            "auth/google-again": google_reopen,
            "auth/google-cancel": google_cancel,
            "auth/signout": lambda: sign_out(bool(b.get("forget"))),
            "auth/continue": lambda: continue_remembered(keep),
            "auth/forget": forget_remembered,
            "account/delete": delete_account,
            "avatar": lambda: upload_avatar(b.get("data")),
            "pull": lambda: {"mission": MS.summary(pull(b.get("id"), b.get("version")))},
            "publish": lambda: publish(b.get("mission"), b.get("form") or {}),
        }.get(route)
        if not r:
            raise CommunityError("Not a community call.", 404)
        out = r()
        return 200, dict(out if isinstance(out, dict) else {"result": out}, ok=True)
    except CommunityError as e:
        return e.status, {"ok": False, "error": str(e), "code": e.code}
