# The AI designer's server side (docs/PLAN-ai.md): the API key, the model, and
# one streamed model turn at a time for the editor's agent loop.
#
# The key stays here. It comes from the studio's encrypted key store
# (studio/keystore.py, what you typed in Settings; formerly config.json "ai",
# ignored by git), else .env (OPENAI_API_KEY) next to the project, else the
# environment. The browser only learns whether there is one.
#
# One turn: the browser posts its history (user, assistant, call, result items),
# the tools and the instructions; this turns them into the provider's protocol,
# and streams the answer back as newline-separated JSON events:
#   {"t":"text","d":...}  {"t":"think","d":...}  {"t":"callstart","name":...}
#   {"t":"call","id":...,"name":...,"args":...}  {"t":"done","responseId":...,"usage":{...}}
#   {"t":"error","message":...}
# Protocols:
#   responses  POST {base}/responses - OpenAI. The only way to use tools with
#              reasoning on the newest models (chat completions refuses tools with
#              reasoning_effort on gpt-5.6-luna, 2026-09-18). Turns chain with
#              previous_response_id; if that id is refused, the whole history goes.
#   chat       POST {base}/chat/completions - any OpenAI-compatible server.
#   mock       no network: a scripted designer for the UI tests.
# Providers: each model is "openai" (an API key and a model; the address is
# OpenAI's) or "compatible", any server that speaks OpenAI's API (LM Studio,
# vLLM, Ollama, OpenRouter): a model, the server's address, an API key if it
# asks for one, and its context window. A compatible server's context is often
# small, so every request to one is fitted into its window (fit()): the oldest
# turns are left out whole, and then the longest tool results shortened.
# Two models (docs/PLAN-ai.md): the main one (config "ai": OpenAI by default)
# plans and builds; a light one (config "ai_light": LM Studio's qwen by default,
# on this machine) titles chats, looks things up for the main one (the scout)
# and reads pictures. A turn asks for one with {"role": "light"}.
# Pictures ride on a user item as {"images": [{"url": "data:image/..."}]}.
import json, os, pathlib, re, time, urllib.error, urllib.request
from studio import keystore, paths

ROOT = pathlib.Path(__file__).resolve().parents[2]
OPENAI = "https://api.openai.com/v1"
DEFAULTS = {"baseUrl": OPENAI, "model": "", "effort": "low", "pace": 350, "maxSteps": 60, "protocol": "auto"}
LIGHT = {"enabled": True, "baseUrl": "http://localhost:1234/v1", "model": "qwen/qwen3.5-9b", "effort": "none",
         "protocol": "chat", "vision": True, "maxTokens": 3000}
CONTEXT = 16384             # a compatible server's context window, until one is set
# not chat models, or not ones that take function tools
NOT_CHAT = re.compile(r"embedding|whisper|tts|dall-e|davinci|babbage|moderation|image|audio|realtime|transcribe|"
                      r"search|computer-use|sora|live|codex|deep-research|instruct|-pro\b|chatgpt", re.I)


def dotenv():
    """KEY=VALUE lines of the project's .env (quotes stripped); {} without one.

    Only a checkout reads it: it is a developer's convenience beside the code,
    and an installed copy keeps its key in the encrypted store instead."""
    out = {}
    if not paths.checkout():
        return out
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def migrate(cfg):
    """Move keys an older version saved in plain text into the encrypted store.

    Returns True when cfg changed and should be saved."""
    changed = False
    for section, name in (("ai", "openai"), ("ai_light", "light")):
        sec = cfg.get(section) or {}
        if sec.get("apiKey"):
            keystore.put(name, sec.pop("apiKey"))
            cfg[section] = sec
            changed = True
    return changed


def settings(cfg):
    """The AI settings with the key resolved: (settings, key, where the key came from).

    The key comes from the studio's encrypted store (what you typed in
    Settings), then a checkout's .env, then the environment. It is never kept
    in the settings file."""
    s = dict(DEFAULTS)
    s.update({k: v for k, v in (cfg.get("ai") or {}).items() if v not in (None, "")})
    env = dotenv()
    legacy = s.pop("apiKey", "")
    key, src = keystore.get("openai"), "encrypted store"
    if not key and legacy:
        key, src = legacy, "settings"
    if not key and env.get("OPENAI_API_KEY"):
        key, src = env["OPENAI_API_KEY"], ".env"
    if not key and os.environ.get("OPENAI_API_KEY"):
        key, src = os.environ["OPENAI_API_KEY"], "environment"
    if not s.get("model"):
        s["model"] = env.get("MODEL_QUALITY") or "gpt-5-mini"
    _provider(s)
    return s, key, (src if key else None)


def light_settings(cfg):
    """The light model's settings and key (a local server needs none; on OpenAI
    without a key of its own, it uses the main model's)."""
    s = dict(LIGHT)
    s.update({k: v for k, v in (cfg.get("ai_light") or {}).items() if v not in (None, "")})
    legacy = s.pop("apiKey", "") or ""
    _provider(s)
    key = keystore.get("light") or legacy
    if not key and s["provider"] == "openai":
        key = settings(cfg)[1]
    return s, key


def _provider(s):
    """openai or compatible, from the settings or, for settings made before there
    was a choice, from the address. OpenAI's address is OpenAI's own."""
    p = (s.get("provider") or "").lower()
    if p not in ("openai", "compatible"):
        p = "openai" if (s.get("baseUrl") or OPENAI).rstrip("/") == OPENAI else "compatible"
    s["provider"] = p
    if p == "openai":
        s["baseUrl"] = OPENAI
    return s


def settings_for(cfg, role):
    """(settings, key) of the main model or the light one."""
    if role == "light":
        return light_settings(cfg)
    s, key, _ = settings(cfg)
    return s, key


def public(cfg):
    """What the browser may see: everything but the keys themselves."""
    s, key, src = settings(cfg)
    s["baseUrl"] = s.get("baseUrl") or OPENAI
    ls, lkey = light_settings(cfg)
    s.setdefault("contextWindow", None)
    ls.setdefault("contextWindow", None)
    # a compatible server needs no key; OpenAI does
    usable = bool(key) or s["provider"] == "compatible"
    return dict(s, hasKey=usable, keySaved=bool(key), keyFrom=src, keyHint=("…" + key[-4:]) if key else "",
                protocolInUse=protocol_of(s), defaultContext=CONTEXT,
                light=dict(ls, hasKey=bool(lkey), keySaved=bool(keystore.get("light")), protocolInUse=protocol_of(ls)))


def update(cfg, body):
    """Settings from the browser into cfg["ai"]. An apiKey of "" keeps the one
    there; {"clearKey": true} drops it."""
    ai = dict(cfg.get("ai") or {})
    for k in ("baseUrl", "model", "effort", "protocol", "provider"):
        if k in body:
            ai[k] = str(body[k] or "").strip()
    for k, lo, hi in (("pace", 0, 3000), ("maxSteps", 5, 200), ("contextWindow", 1024, 10000000)):
        if k in body and body[k] not in (None, ""):
            ai[k] = max(lo, min(hi, int(body[k] or 0)))
    # keys go to the encrypted store, not into cfg (which is a plain file)
    if body.get("apiKey"):
        keystore.put("openai", str(body["apiKey"]))
    if body.get("clearKey"):
        keystore.drop("openai")
    ai.pop("apiKey", None)
    cfg["ai"] = ai
    lb = body.get("light")
    if isinstance(lb, dict):
        li = dict(cfg.get("ai_light") or {})
        for k in ("baseUrl", "model", "effort", "protocol", "provider"):
            if k in lb:
                li[k] = str(lb[k] or "").strip()
        for k in ("enabled", "vision"):
            if k in lb:
                li[k] = bool(lb[k])
        if lb.get("contextWindow") not in (None, ""):
            li["contextWindow"] = max(1024, min(10000000, int(lb["contextWindow"])))
        if lb.get("apiKey"):
            keystore.put("light", str(lb["apiKey"]))
        if lb.get("clearKey"):
            keystore.drop("light")
        li.pop("apiKey", None)
        cfg["ai_light"] = li
    return cfg


def protocol_of(s):
    p = (s.get("protocol") or "auto").lower()
    if (s.get("baseUrl") or "") == "mock":
        return "mock"
    if p in ("responses", "chat"):
        return p
    return "responses" if (s.get("baseUrl") or OPENAI).rstrip("/") == OPENAI else "chat"


def _req(s, key, path, payload=None, timeout=300):
    base = (s.get("baseUrl") or OPENAI).rstrip("/")
    h = {"Content-Type": "application/json"}
    if key:
        h["Authorization"] = "Bearer " + key
    data = json.dumps(payload).encode() if payload is not None else None
    return urllib.request.urlopen(urllib.request.Request(base + path, data=data, headers=h,
                                                         method="POST" if data else "GET"), timeout=timeout)


def _http_error(e):
    try:
        j = json.loads(e.read().decode("utf-8", "replace"))
        msg = (j.get("error") or {}).get("message") or json.dumps(j)[:400]
    except Exception:
        msg = str(e)
    return "%s (HTTP %d)" % (msg, e.code)


def models(cfg, role="main"):
    """The account's chat models, newest-looking first."""
    s, key = settings_for(cfg, role)
    if protocol_of(s) == "mock":
        return ["mock-designer"]
    try:
        ids = [m["id"] for m in json.load(_req(s, key, "/models", timeout=30)).get("data", [])]
    except urllib.error.HTTPError as e:
        raise ValueError(_http_error(e))
    except urllib.error.URLError as e:
        raise ValueError("can't reach %s: %s" % (s.get("baseUrl"), e.reason))
    keep = [i for i in ids if not NOT_CHAT.search(i) and not re.search(r"-\d{4}-\d{2}-\d{2}$", i)]
    if (s.get("baseUrl") or OPENAI).rstrip("/") == OPENAI:
        keep = [i for i in keep if re.match(r"(gpt-[4-9]|o[1-9])", i)]

    def rank(i):
        m = re.match(r"gpt-(\d+)(?:\.(\d+))?", i)
        return (-(int(m.group(1)) * 100 + int(m.group(2) or 0)) if m else 0, len(i), i)
    return sorted(set(keep), key=rank)


# ------------------------------------------------------------------ history
def _responses_input(items):
    out = []
    for it in items:
        k = it.get("k")
        if k == "user":
            ims = [im for im in it.get("images") or [] if isinstance(im, dict) and im.get("url")]
            if ims:
                out.append({"role": "user", "content": [{"type": "input_text", "text": it.get("text") or ""}] +
                            [{"type": "input_image", "image_url": im["url"]} for im in ims]})
            else:
                out.append({"role": "user", "content": it.get("text") or ""})
        elif k == "assistant" and (it.get("text") or "").strip():
            out.append({"role": "assistant", "content": it["text"]})
        elif k == "call":
            out.append({"type": "function_call", "call_id": it["id"], "name": it["name"], "arguments": it.get("args") or "{}"})
        elif k == "result":
            out.append({"type": "function_call_output", "call_id": it["id"], "output": it.get("output") or ""})
    return out


def _chat_messages(instructions, items):
    out = [{"role": "system", "content": instructions}] if instructions else []
    for it in items:
        k = it.get("k")
        if k == "user":
            ims = [im for im in it.get("images") or [] if isinstance(im, dict) and im.get("url")]
            if ims:
                out.append({"role": "user", "content": [{"type": "text", "text": it.get("text") or ""}] +
                            [{"type": "image_url", "image_url": {"url": im["url"]}} for im in ims]})
            else:
                out.append({"role": "user", "content": it.get("text") or ""})
        elif k == "assistant":
            out.append({"role": "assistant", "content": it.get("text") or ""})
        elif k == "call":
            last = out[-1] if out else None
            call = {"id": it["id"], "type": "function", "function": {"name": it["name"], "arguments": it.get("args") or "{}"}}
            if last and last["role"] == "assistant" and "tool_calls" in last:
                last["tool_calls"].append(call)
            elif last and last["role"] == "assistant":
                last["tool_calls"] = [call]
            else:
                out.append({"role": "assistant", "content": None, "tool_calls": [call]})
        elif k == "result":
            out.append({"role": "tool", "tool_call_id": it["id"], "content": it.get("output") or ""})
    return out


# ------------------------------------------------------------------ the context window
IMAGE_TOKENS = 800          # what a picture costs, near enough


def _tokens(text):
    """A cautious guess: English and JSON run at three to four characters a token."""
    return len(text or "") // 3 + 4


def _cost(it):
    return (_tokens(it.get("text")) + _tokens(it.get("args")) + _tokens(it.get("output")) +
            IMAGE_TOKENS * len(it.get("images") or []))


def fit(s, instructions, items, tools):
    """(instructions, items) that fit a compatible server's context window.

    Room is kept for the answer (the model's maxTokens, else a quarter of the
    window, at most 4096). The oldest turns are left out first, whole (a turn
    starts at a user message, so a tool call is never parted from its result),
    never the newest; if that is still too much, the longest tool results are
    shortened, keeping their beginning and end. The model is told when either
    happened. OpenAI's own models are not fitted: their windows are large."""
    ctx = int(s.get("contextWindow") or 0)
    if s.get("provider") != "compatible" or ctx <= 0 or not items:
        return instructions, items
    budget = ctx - (int(s.get("maxTokens") or 0) or min(4096, ctx // 4))
    fixed = _tokens(instructions) + _tokens(json.dumps(tools)) + 60
    costs = [_cost(it) for it in items]
    if fixed + sum(costs) <= budget:
        return instructions, items
    starts = [i for i, it in enumerate(items) if it.get("k") == "user"] or [0]
    keep = starts[-1]
    for st in starts:
        if fixed + sum(costs[st:]) <= budget:
            keep = st
            break
    notes = []
    if keep > 0:
        notes.append("Earlier parts of this conversation were left out to fit the model's context window.")
    items = [dict(it) for it in items[keep:]]
    over = fixed + sum(_cost(it) for it in items) - budget
    if over > 0:
        for it in sorted((it for it in items if it.get("k") == "result"), key=lambda it: -len(it.get("output") or "")):
            out = it.get("output") or ""
            if over <= 0 or len(out) < 800:
                break
            keep_chars = max(600, len(out) - over * 3)
            head, tail = out[:keep_chars * 2 // 3], out[-(keep_chars // 3):]
            it["output"] = head + "\n... (shortened to fit the model's context window) ...\n" + tail
            over -= (len(out) - len(it["output"])) // 3
        notes.append("Some tool results were shortened to fit the model's context window.")
    return (instructions + ("\n\n" + " ".join(notes) if notes else "")), items


# ------------------------------------------------------------------ one turn
def chat(cfg, body, emit, alive=lambda: True):
    """Stream one model turn to emit(event). body: {instructions, tools:[{name,
    description, parameters}], history:[items], previousId, fresh (index where
    this turn's new items start), role ("main" or "light")}."""
    role = body.get("role") or "main"
    s, key = settings_for(cfg, role)
    proto = protocol_of(s)
    if proto == "mock" or body.get("mock"):          # the UI tests ask for the scripted designer
        return mock(body, emit)
    if role == "light" and not s.get("enabled", True):
        return emit({"t": "error", "message": "The light model is off (Settings, AI designer).", "code": "nolight"})
    if not key and (s.get("baseUrl") or OPENAI).rstrip("/") == OPENAI:
        return emit({"t": "error", "message": "No API key yet. Add one in Settings, AI designer.", "code": "nokey"})
    model = body.get("model") or s["model"]
    t0 = time.time()
    try:
        if proto == "responses":
            _responses(s, key, model, body, emit, alive)
        else:
            _chat(s, key, model, body, emit, alive)
    except urllib.error.URLError as e:
        emit({"t": "error", "message": "Can't reach %s: %s" % (s.get("baseUrl"), getattr(e, "reason", e))})
    except (BrokenPipeError, ConnectionError):
        pass                      # the browser stopped it
    return time.time() - t0


def _open_with_retries(s, key, path, payload, drops):
    """POST, and on a 400 that names a parameter this model does not take, once
    more without it (drops: [(pattern, remove(payload))])."""
    tried = set()
    while True:
        try:
            return _req(s, key, path, payload)
        except urllib.error.HTTPError as e:
            msg = _http_error(e)
            if e.code == 400:
                for pat, fix in drops:
                    if pat not in tried and re.search(pat, msg, re.I):
                        tried.add(pat)
                        fix(payload)
                        break
                else:
                    raise ValueError(msg)
                continue
            raise ValueError(msg)


def _responses(s, key, model, body, emit, alive):
    items = body.get("history") or []
    fresh = int(body.get("fresh") or 0)
    prev = body.get("previousId") or None
    payload = {"model": model, "stream": True, "instructions": body.get("instructions") or "",
               "input": _responses_input(items[fresh:] if prev else items),
               "tools": [dict(type="function", strict=False, **t) for t in body.get("tools") or []]}
    if not payload["tools"]:
        payload.pop("tools")
    eff = (s.get("effort") or "").lower()
    if eff and eff != "default":
        payload["reasoning"] = {"effort": eff, "summary": "auto"}
    if prev:
        payload["previous_response_id"] = prev

    def no_prev(p):
        p.pop("previous_response_id", None)
        p["input"] = _responses_input(items)
    drops = [(r"previous.response|not found", no_prev),
             (r"summary|organization.*verif", lambda p: p.get("reasoning", {}).pop("summary", None)),
             (r"reasoning", lambda p: p.pop("reasoning", None))]
    try:
        resp = _open_with_retries(s, key, "/responses", payload, drops)
    except ValueError as e:
        return emit({"t": "error", "message": str(e)})
    ev, streamed, done = None, set(), False
    for raw in resp:
        if not alive():
            resp.close()
            return
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if line.startswith("event:"):
            ev = line[6:].strip()
            continue
        if not line.startswith("data:"):
            continue
        try:
            d = json.loads(line[5:].strip())
        except ValueError:
            continue
        t = d.get("type") or ev
        if t == "response.output_text.delta":
            streamed.add(d.get("item_id"))
            emit({"t": "text", "d": d.get("delta") or ""})
        elif t in ("response.reasoning_summary_text.delta", "response.reasoning_text.delta"):
            emit({"t": "think", "d": d.get("delta") or ""})
        elif t == "response.output_item.added" and (d.get("item") or {}).get("type") == "function_call":
            emit({"t": "callstart", "name": d["item"].get("name") or ""})
        elif t == "response.output_item.done":
            it = d.get("item") or {}
            if it.get("type") == "function_call":
                emit({"t": "call", "id": it.get("call_id") or it.get("id"), "name": it.get("name"),
                      "args": it.get("arguments") or "{}"})
            elif it.get("type") == "message" and it.get("id") not in streamed:
                # an answer that came whole, with no deltas
                txt = "".join(c.get("text") or "" for c in it.get("content") or [] if c.get("type") == "output_text")
                if txt:
                    emit({"t": "text", "d": txt})
        elif t in ("response.completed", "response.incomplete"):
            r = d.get("response") or {}
            u = r.get("usage") or {}
            done = True
            emit({"t": "done", "responseId": r.get("id"), "status": r.get("status"), "model": r.get("model") or model,
                  "usage": {"in": u.get("input_tokens"), "out": u.get("output_tokens"),
                            "cached": (u.get("input_tokens_details") or {}).get("cached_tokens"),
                            "reasoning": (u.get("output_tokens_details") or {}).get("reasoning_tokens")},
                  "why": ((r.get("incomplete_details") or {}).get("reason"))})
        elif t in ("response.failed", "error"):
            err = (d.get("response") or {}).get("error") or d.get("error") or d
            done = True
            emit({"t": "error", "message": err.get("message") if isinstance(err, dict) else str(err)})
    if not done:
        emit({"t": "error", "message": "The answer stopped before it was complete."})


def _chat(s, key, model, body, emit, alive):
    instructions, history = fit(s, body.get("instructions") or "", body.get("history") or [], body.get("tools") or [])
    payload = {"model": model, "stream": True, "stream_options": {"include_usage": True},
               "messages": _chat_messages(instructions, history),
               "tools": [{"type": "function", "function": t} for t in body.get("tools") or []]}
    if not payload["tools"]:
        payload.pop("tools")
    eff = (s.get("effort") or "").lower()
    if eff and eff != "default":
        payload["reasoning_effort"] = eff
    if s.get("maxTokens"):                      # a small model can run on without end
        payload["max_tokens"] = int(s["maxTokens"])
    if eff == "none" and payload["messages"] and payload["messages"][0]["role"] == "system":
        payload["messages"][0]["content"] += "\n/no_think"      # Qwen's own switch for no reasoning
    drops = [(r"stream_options", lambda p: p.pop("stream_options", None)),
             (r"max_tokens", lambda p: p.pop("max_tokens", None)),
             (r"reasoning", lambda p: p.pop("reasoning_effort", None))]
    try:
        resp = _open_with_retries(s, key, "/chat/completions", payload, drops)
    except ValueError as e:
        return emit({"t": "error", "message": str(e)})
    calls, usage, finish, rid = {}, {}, None, None
    for raw in resp:
        if not alive():
            resp.close()
            return
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            c = json.loads(data)
        except ValueError:
            continue
        rid = c.get("id") or rid
        if c.get("usage"):
            usage = c["usage"]
        for ch in c.get("choices") or []:
            dl = ch.get("delta") or {}
            if dl.get("content"):
                emit({"t": "text", "d": dl["content"]})
            rc = dl.get("reasoning_content") or dl.get("reasoning")
            if isinstance(rc, str) and rc:
                emit({"t": "think", "d": rc})
            for tc in dl.get("tool_calls") or []:
                i = tc.get("index", 0)
                e = calls.setdefault(i, {"id": "", "name": "", "args": ""})
                e["id"] = tc.get("id") or e["id"]
                f = tc.get("function") or {}
                if f.get("name") and f["name"] != e["name"]:
                    if not e["name"]:
                        emit({"t": "callstart", "name": f["name"]})
                    e["name"] += f["name"]
                e["args"] += f.get("arguments") or ""
            finish = ch.get("finish_reason") or finish
    for i in sorted(calls):
        e = calls[i]
        emit({"t": "call", "id": e["id"] or "call_%d_%d" % (int(time.time()), i), "name": e["name"], "args": e["args"] or "{}"})
    emit({"t": "done", "responseId": None, "status": finish, "model": model,
          "usage": {"in": usage.get("prompt_tokens"), "out": usage.get("completion_tokens")}})


def test(cfg, role="main"):
    """A one-line request with the settings as they are: (ok, what came back)."""
    got = {"text": "", "err": None, "model": None}

    def emit(e):
        if e["t"] == "text":
            got["text"] += e["d"]
        elif e["t"] == "error":
            got["err"] = e["message"]
        elif e["t"] == "done":
            got["model"] = e.get("model")
    t = chat(cfg, {"instructions": "Answer in five words or fewer.", "role": role,
                   "history": [{"k": "user", "text": "Say that you are ready to design missions."}]}, emit) or 0
    if got["err"]:
        return False, got["err"]
    return True, "%s answered in %.1f s: %s" % (got["model"] or "The model", t, got["text"].strip()[:120])


# ------------------------------------------------------------------ the test provider
def mock(body, emit):
    """A scripted designer (base address "mock"): looks, builds a little, checks,
    and sums up, so the whole loop can be tested without a network. With no
    building tools (Ideas) it answers with two designs."""
    items = body.get("history") or []
    tools = {t["name"] for t in body.get("tools") or []}
    last_user = max((i for i, it in enumerate(items) if it.get("k") == "user"), default=-1)
    done_calls = [it for it in items[last_user + 1:] if it.get("k") == "call"]
    results = {it["id"]: it.get("output") for it in items[last_user + 1:] if it.get("k") == "result"}
    step = len({c["id"] for c in done_calls})
    n = sum(1 for it in items if it.get("k") == "call")

    def call(name, args):
        emit({"t": "callstart", "name": name})
        emit({"t": "call", "id": "mock_%d_%s" % (n, name), "name": name, "args": json.dumps(args)})

    def say(text):
        for w in re.findall(r"\S+\s*", text):
            emit({"t": "text", "d": w})
            time.sleep(0.004)
    place = "the centre"
    for c in done_calls:
        if c["name"] == "find_places":
            try:
                ps = json.loads(results.get(c["id"]) or "{}").get("places") or []
                if ps:
                    place = ps[0]["name"]
            except ValueError:
                pass
    last_text = (items[last_user].get("text") or "").lower() if last_user >= 0 else ""
    flows = [("stealth", "stealth_check", [("stealth_check", {})]),
             ("walkway", "add_walkways", [("find_places", {"query": "radar dome", "limit": 3}),
                                          ("add_walkways", {"place": "@place", "area_radius": 10})]),
             ("ground", "shape_ground", [("find_places", {"query": "radar dome", "limit": 3}),
                                         ("shape_ground", {"mode": "level", "place": "@place", "width": 16, "depth": 12})]),
             ("texts", "write_texts", [("write_texts", {"name": "Quiet Hands", "description": "Get in and out unseen",
                                                        "briefing": "Intel places the codes in the radar dome.\nGet in and out unseen.",
                                                        "objectives": [{"number": 1, "text": "Reach the radar dome."}]})]),
             ("scout", "scout", [("scout", {"question": "Where are the guards round the radar dome?"})])]
    for word, tool, steps in flows:
        if word in last_text and tool in tools:
            if step < len(steps):
                name, args = steps[step]
                args = {k: (place if v == "@place" else v) for k, v in args.items()}
                call(name, args)
            else:
                say("Done: %s." % ", ".join(n.replace("_", " ") for n, _ in steps))
            emit({"t": "done", "responseId": None, "model": "mock-designer", "usage": {"in": 0, "out": 0}})
            return
    if "character" in last_text and "design_character" in tools:
        if step == 0:
            call("design_character", {"name": "Counter-Strike Terrorist", "type": "AITYPE_MAFIA_GUARD_AK", "model": "014_01_1",
                                      "weapon": "WEAPON_ID_AK47", "sees_m": 55, "view_deg": 100})
        else:
            say("Here is the character. Add it to your inventory if you like it.")
        emit({"t": "done", "responseId": None, "model": "mock-designer", "usage": {"in": 0, "out": 0}})
        return
    if "design" in last_text and "design_structure" in tools:
        if step == 0:
            say("Looking for parts.\n")
            call("list_catalog", {"kind": "structures", "search": "crate", "limit": 4})
        elif step == 1:
            models = ["300_03_1"]
            for c in done_calls:
                if c["name"] == "list_catalog":
                    try:
                        models = [x["model"] for x in json.loads(results.get(c["id"]) or "{}").get("items") or []] or models
                    except ValueError:
                        pass
            call("design_structure", {"name": "Crate stack", "description": "A few crates to hide behind.",
                                      "parts": [{"model": models[0], "dx": 0, "dy": 0}, {"model": models[-1], "dx": 2.2, "dy": 0.4, "facing_deg": 20}],
                                      "guards": [{"type": "AITYPE_GUARD_AK", "dx": -2, "dy": 1.5, "facing_deg": 180}]})
        else:
            say("Here it is: a crate stack with a guard. Add it to your inventory if you like it.")
        emit({"t": "done", "responseId": None, "model": "mock-designer", "usage": {"in": 0, "out": 0}})
        return
    if "place_guards" not in tools:
        if step == 0:
            say("Looking at the level first.\n")
            call("get_overview", {})
        else:
            say("### Design 1: Quiet Hands\nSlip in at night, hack the terminal at %s and leave unseen. Two snipers "
                "cover the approach, cameras watch the gate.\n\n### Design 2: Hard Rain\nHeavy rain, a 12 minute limit, "
                "eliminate the officer and escape by the far side.\n" % place)
        emit({"t": "done", "responseId": None, "model": "mock-designer", "usage": {"in": 0, "out": 0}})
        return
    if step == 0:
        say("I'll look at the level, then put a sniper pair and a camera near the first named place.\n")
        call("get_overview", {})
    elif step == 1:
        call("find_places", {"query": "", "limit": 5})
    elif step == 2:
        say("Building at %s.\n" % place)
        call("place_guards", {"count": 2, "type": "AITYPE_SNIPER", "place": place})
        call("place_camera", {"place": place, "facing_deg": 0})
    elif step == 4:
        call("add_objective", {"kind": "reach", "place": place, "radius": 8, "text": "Reach " + place})
        call("set_settings", {"weather": "snow", "intensity": 0.2})
    elif step == 6:
        call("check_mission", {})
    else:
        say("Done: two snipers and a camera at %s, an objective to reach it, and snow. Apply when you are ready." % place)
    emit({"t": "done", "responseId": None, "model": "mock-designer", "usage": {"in": 0, "out": 0}})


# ------------------------------------------------------------------ chat threads
# A mission's conversations with the designer, one file each:
# missions/custom/<id>/ai/threads/<tid>.json {title, created, updated, items,
# view, responseId, synced, mode, model}. The single chat.json of before is
# taken in as the first thread.
def _threads_dir(store, mid):
    if not (store / mid).is_dir():
        raise FileNotFoundError(mid)
    d = store / mid / "ai" / "threads"
    d.mkdir(parents=True, exist_ok=True)
    old = store / mid / "ai" / "chat.json"
    if old.exists():
        try:
            data = json.loads(old.read_text(encoding="utf-8"))
            if data.get("items") or data.get("view"):
                first = next((it.get("text") for it in data.get("items") or [] if it.get("k") == "user"), "") or "Earlier chat"
                data.setdefault("title", " ".join(first.split()[:7]))
                data.setdefault("created", data.get("at") or int(time.time()))
                data.setdefault("updated", data.get("at") or int(time.time()))
                (d / ("t%d.json" % data["created"])).write_text(json.dumps(data), encoding="utf-8")
            old.unlink()
        except (OSError, ValueError):
            pass
    return d


def _tid(tid):
    if not re.fullmatch(r"[a-z0-9-]{1,40}", tid or ""):
        raise ValueError("bad thread id")
    return tid


def list_threads(store, mid):
    out = []
    for f in _threads_dir(store, mid).glob("*.json"):
        try:
            t = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({"id": f.stem, "title": t.get("title") or "Chat", "created": t.get("created"), "updated": t.get("updated"),
                    "count": sum(1 for it in t.get("view") or [] if it.get("k") == "user"), "mode": t.get("mode")})
    return sorted(out, key=lambda t: -(t.get("updated") or 0))


def load_thread(store, mid, tid):
    f = _threads_dir(store, mid) / (_tid(tid) + ".json")
    if not f.exists():
        raise FileNotFoundError(tid)
    return json.loads(f.read_text(encoding="utf-8"))


def save_thread(store, mid, tid, data):
    f = _threads_dir(store, mid) / (_tid(tid) + ".json")
    keep = {k: data.get(k) for k in ("title", "titled", "created", "items", "view", "responseId", "synced", "mode", "model")}
    keep["items"] = (keep["items"] or [])[-800:]
    keep["view"] = (keep["view"] or [])[-500:]
    keep["created"] = keep["created"] or int(time.time())
    keep["updated"] = int(time.time())
    f.write_text(json.dumps(keep), encoding="utf-8")
    return {"id": tid, "updated": keep["updated"]}


def delete_thread(store, mid, tid):
    f = _threads_dir(store, mid) / (_tid(tid) + ".json")
    if f.exists():
        f.unlink()
    return True


# ------------------------------------------------------------------ chat storage (before threads)
def chat_path(store, mid):
    return store / mid / "ai" / "chat.json"


def load_chat(store, mid):
    f = chat_path(store, mid)
    if not f.exists():
        return {"items": [], "view": [], "responseId": None}
    return json.loads(f.read_text(encoding="utf-8"))


def save_chat(store, mid, data):
    if not (store / mid).is_dir():
        raise FileNotFoundError(mid)
    f = chat_path(store, mid)
    f.parent.mkdir(exist_ok=True)
    keep = {"items": (data.get("items") or [])[-600:], "view": (data.get("view") or [])[-400:],
            "responseId": data.get("responseId"), "synced": data.get("synced"), "mode": data.get("mode"),
            "at": int(time.time())}
    f.write_text(json.dumps(keep), encoding="utf-8")
    return True
