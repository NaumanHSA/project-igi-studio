# The community

Missions people share with each other, from inside the studio: a Community
page to browse and search them, a page for each (its objectives, pictures,
author, votes, comments, versions and where it came from), a look at its map
and 3D view without taking it, pulling it into the studio to change it, and a
wizard to share missions of your own. Guests browse and look; pulling,
sharing, voting, commenting and reporting need an account (Google, or email
and password).

## The pieces

```
cloud/
├── migrations/001_community.sql   every rule: the tables, and the API (functions only)
├── migrate.mjs                    runs the migrations on Neon (DATABASE_URL from the environment)
├── dev/
│   ├── db.mjs                     the same SQL in PGlite, with what Neon has before it
│   ├── server.mjs                 a stand-in for the Neon project: Data API, Neon Auth, a pretend Google
│   └── test.mjs                   the rules, tested on the database itself
└── package.json                   npm install here: PGlite and pg
studio/server/community.py         the studio's client: the account, the calls, pictures, pull, share
editor/community.js                the Community page, the dialogs, the share wizard
editor/plotter.html                the editor's side (window.StudioCommunity), the preview, the menus
tests/test_community.py            the client against the stand-in: the whole story
```

## The database (Neon)

Neon's **Data API** (PostgREST) is in front of the database and **Neon Auth**
(managed Better Auth) holds the accounts. The studio never has a secret: what
anyone may do is decided in the database.

**The API is functions only.** The tables are in the schema `community`,
which the Data API does not expose and no API role is granted. Every call is
`public.<name>(p jsonb) returns jsonb`, `security definer`, and checks
everything itself - who is asking (`auth.user_id()`, null for a guest), what
they may do, sizes, and rate limits:

```
POST <data api>/rpc/<name>      {"p": {...}}      Authorization: Bearer <JWT>
```

Reading is granted to `anonymous` and `authenticated`; writing to
`authenticated` only. RLS is on with no policies, a second lock. An error is
a sentence for the person (errcode `P0001`), shown as it is.

| Reading (guests too) | Writing (an account) | Moderating |
|---|---|---|
| `me`, `handle_free`, `name_free`, `list_missions`, `get_mission`, `remixes`, `get_plan`, `get_media`, `mission_versions`, `list_comments`, `get_profile` | `save_profile`, `upload_media`, `publish_mission`, `publish_version`, `update_details`, `set_status`, `delete_mission`, `set_vote`, `record_pull`, `add_comment`, `edit_comment`, `delete_comment`, `report`, `delete_my_data` | `mod_reports`, `mod_act`, `set_role` (admin) |

The rules worth knowing:

- **Names** are unique however they are written (`name_key`: lower case,
  every run of what is not a letter or digit one space). A deleted mission's
  row is gone, so its name is free again at once.
- **A remix** (shared from a pulled mission) has `parent` and carries its
  whole `lineage` (oldest first). The line is a snapshot, so it survives when
  an earlier mission is deleted: the names stay, the links go. Sharing a plan
  identical to the version it came from is refused; so is sharing a changed
  copy when its author does not allow remixes.
- **Versions**: an update is a new plan with notes; votes and comments stay.
- **Media** (covers, thumbnails, screenshots, pictures, avatars, plans) are
  rows: `bytea`, size-capped by kind, their magic bytes checked. Neon's object
  storage would need secret keys the studio cannot hold. Uploads that never
  became part of anything are dropped after two hours.
- **Rate limits** per person per hour (publish 10, upload 120, vote 300,
  comment 60, report 20, ...). Banned people cannot write. Moderators hide
  missions, remove comments, ban; the admin makes moderators.
- **Search**: full text (`english`) over the name, the author, the summary,
  the tags, the description and the objectives, and the name as typed
  (`pg_trgm` word similarity: "radr" finds "Radar Dome Raid"). Pages of 24.

## The studio's side

`studio/server/community.py` holds the account and makes every call; the
editor only talks to the studio's own server (`/api/community/...`, listed at
the top of the module).

- **The session** is Neon Auth's cookie (an opaque token), kept in the
  keystore (DPAPI). The JWT for the Data API comes in the `set-auth-jwt`
  header of `GET <auth>/get-session`, lasts 15 minutes, and is fetched again
  when it runs out. A guest uses `GET <auth>/token/anonymous`.
- **Email**: sign-up, then a code by email (`/email-otp/verify-email`); a
  forgotten password is a code too (`/email-otp/reset-password`). Codes, not
  links: nothing has to come back to a desktop app.
- **Google** from a desktop app: `POST <auth>/sign-in/social` gives Google's
  page, opened in the browser; Neon Auth then sends the browser to
  `http://127.0.0.1:<port>/callback?...&neon_auth_session_verifier=...`, a
  small listener that runs only while a sign-in waits, and the studio
  exchanges the verifier for the session (`get-session?neon_auth_session_verifier=`).
  The port is fixed (38461, else 41923, else 45127) because Neon trusts listed
  origins only and the studio's own port changes every run; all three are
  below 49152, where Windows (Hyper-V, WSL, Docker) reserves blocks of ports
  that move from boot to boot.
- **Pictures and plans** come base64 in JSON and are kept in
  `cache/community/` by id: they never change. A Google profile picture is
  the only thing fetched from elsewhere (`lh*.googleusercontent.com` only).
- **Pulling** makes a mission of yours: the plan is someone else's data, so
  only the plan's own keys are kept (`missions.save`), strings lose control
  characters and are capped, and the whole is size-capped before it is read.
  `mission.json` gets `community`: `origin` (what it came from), `lineage`,
  `base_sha` (its plan right after pulling: "nothing changed" is comparing to
  it) and, once shared from here, `published`. A duplicate keeps where it came
  from but not `published`.
- **Sharing** (`publish`): the plan as the export file has it, gzipped; the
  cover and thumbnail (WebP, 1280x720 and 480x270, cut from the middle),
  screenshots, the mission's own picture; the objectives and facts the editor
  counted. A new mission (a remix when it was pulled), or a new version.

## The editor's side

- **Where**: the left wall's Community tab (apart from the mission's tabs; a
  globe), the Share menu, and the library's Community button.
- **The page** (`#community`, over the workspace like the library): search,
  sort (newest, top, this week, this month, most pulled, best match), filters
  (base level, difficulty, style, originals or remixes); a mission's page;
  profiles; the moderators' reports.
- **Looking without pulling** is the editor's read-only mode with a plan:
  `viewCommunity(doc, meta)` loads the plan (`loadPlanState`, shared with
  `openMission`) over its base level with `READONLY` and `PREVIEW` set. The
  banner offers Pull and Back to the community; nothing is saved or applied.
- **The share wizard**: Check (the mission saved and checked, at least one
  objective, not unchanged since it was pulled), About, Pictures, Credits,
  Review. What it was told is kept in this browser by mission until it is
  published.

## Running it

```
cd cloud && npm install
npm test                                     the rules, on the database itself
node dev/server.mjs                          the stand-in, kept in cloud/dev/.data (--memory: not kept)
IGISTUDIO_COMMUNITY=http://127.0.0.1:8790 python -m studio serve     the studio against it
python -m unittest tests.test_community      the client against it (starts its own)
```

### Setting up the Neon project

1. **Neon Auth** on: email and password with verification **by code**,
   Google (Neon's shared credentials to try it; our own Google OAuth client
   for the release), anonymous tokens on, and the trusted origins
   `http://127.0.0.1:38461`, `http://127.0.0.1:41923`, `http://127.0.0.1:45127`.
2. **Data API** on, with Neon Auth as its provider, exposing `public`.
3. `DATABASE_URL=<the owner's connection string> node migrate.mjs` (`--check`
   first shows what is there). The connection string stays out of the
   repository and the studio.
4. The Data API's and Neon Auth's URLs into `COMMUNITY` in
   `studio/server/community.py`: they are public.
