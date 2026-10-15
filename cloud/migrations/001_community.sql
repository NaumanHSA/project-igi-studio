-- The community's database: the missions people share, their versions, votes,
-- comments, pulls, reports, and the people. For Neon: its Data API in front,
-- Neon Auth for the accounts.
--
-- The API is the functions at the end of this file, and only they. The tables
-- live in the schema "community", which the Data API does not expose and no
-- API role is granted. Each function is public.<name>(p jsonb) returns jsonb,
-- security definer, and checks everything itself: who is asking
-- (auth.user_id(), null for a guest), what they may do, sizes and rates.
-- Called as
--
--   POST <data api>/rpc/<name>        {"p": {...}}
--
-- Reads are granted to "anonymous" (guests, with Neon Auth's anonymous token)
-- and "authenticated"; everything that writes to "authenticated" only.
--
-- An error is a sentence for the person (errcode P0001), shown as it is.
--
-- Pictures and plans are rows (community.media), not files: Neon's object
-- storage needs secret keys the studio cannot hold. They are small and capped,
-- and the studio keeps each one it has fetched (they never change).
--
-- cloud/dev/server.mjs runs this same file in PGlite for the tests; it makes
-- the roles and auth.user_id() first, which Neon already has.

create extension if not exists pg_trgm;
create schema if not exists community;
revoke all on schema community from public;

-- ------------------------------------------------------------------ tables

create table community.media (
  id uuid primary key default gen_random_uuid(),
  owner text not null,
  kind text not null check (kind in ('cover', 'thumb', 'shot', 'picture', 'avatar', 'plan')),
  mime text not null check (mime in ('image/webp', 'image/png', 'image/jpeg', 'application/gzip')),
  bytes bytea not null,
  sha256 text not null,
  created_at timestamptz not null default now()
);
create index media_owner on community.media (owner, created_at);

create table community.profiles (
  id text primary key,                          -- the account (auth.user_id())
  handle text not null,
  handle_key text not null unique,              -- the handle in lower case: unique however it is written
  display_name text not null,
  bio text not null default '',
  links jsonb not null default '[]'::jsonb,
  avatar uuid references community.media (id) on delete set null,
  avatar_url text,                              -- the Google picture, when there is none of ours
  role text not null default 'user' check (role in ('user', 'mod', 'admin')),
  banned boolean not null default false,
  created_at timestamptz not null default now()
);

create table community.missions (
  id uuid primary key default gen_random_uuid(),
  author text not null references community.profiles (id) on delete cascade,
  name text not null,
  name_key text not null,                       -- the name folded (case, spaces, punctuation): unique
  summary text not null,
  description text not null default '',
  base_level int not null check (base_level between 1 and 14),
  base_kind text not null check (base_kind in ('copy', 'empty')),
  difficulty text not null default 'normal' check (difficulty in ('easy', 'normal', 'hard')),
  tags text[] not null default '{}',
  play_minutes int check (play_minutes between 1 and 600),
  objectives jsonb not null,                    -- [{kind, text}], as the mission has them
  facts jsonb not null default '{}'::jsonb,     -- counted by the studio: guards, cameras, time limit...
  cover uuid not null references community.media (id),
  thumb uuid not null references community.media (id),
  picture uuid references community.media (id) on delete set null,
  shots uuid[] not null default '{}',
  video_url text,
  version int not null default 1,
  allow_remix boolean not null default true,
  status text not null default 'published' check (status in ('published', 'unlisted', 'hidden')),
  parent uuid references community.missions (id) on delete set null,
  parent_version int,
  lineage jsonb not null default '[]'::jsonb,   -- every mission before it, oldest first: kept when one goes
  coauthors text[] not null default '{}',
  up int not null default 0,
  down int not null default 0,
  comments int not null default 0,
  pulls int not null default 0,
  search tsvector,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
-- a deleted mission's row is gone, so its name is free again at once
create unique index missions_name_key on community.missions (name_key);
create index missions_author on community.missions (author);
create index missions_parent on community.missions (parent);
create index missions_new on community.missions (created_at desc);
create index missions_top on community.missions ((up - down) desc);
create index missions_search on community.missions using gin (search);
create index missions_name_trgm on community.missions using gin (name_key gin_trgm_ops);

create table community.versions (
  mission uuid not null references community.missions (id) on delete cascade,
  version int not null,
  plan uuid not null references community.media (id),
  plan_sha256 text not null,                    -- of the plan as JSON with sorted keys: "nothing changed"
  size int not null,
  format_version int not null,
  studio_version text not null default '',
  notes text not null default '',
  created_at timestamptz not null default now(),
  primary key (mission, version)
);
create index versions_plan on community.versions (plan);

create table community.votes (
  mission uuid not null references community.missions (id) on delete cascade,
  voter text not null references community.profiles (id) on delete cascade,
  value smallint not null check (value in (-1, 1)),
  created_at timestamptz not null default now(),
  primary key (mission, voter)
);
create index votes_recent on community.votes (mission, created_at);
create index votes_voter on community.votes (voter);

create table community.pulls (
  mission uuid not null references community.missions (id) on delete cascade,
  puller text not null references community.profiles (id) on delete cascade,
  version int not null,
  created_at timestamptz not null default now(),
  primary key (mission, puller)
);
create index pulls_puller on community.pulls (puller);

create table community.comments (
  id uuid primary key default gen_random_uuid(),
  mission uuid not null references community.missions (id) on delete cascade,
  author text not null references community.profiles (id) on delete cascade,
  parent uuid references community.comments (id) on delete cascade,
  body text not null,
  removed boolean not null default false,
  created_at timestamptz not null default now(),
  edited_at timestamptz
);
create index comments_mission on community.comments (mission, created_at);
create index comments_parent on community.comments (parent);
create index comments_author on community.comments (author);

create table community.reports (
  id uuid primary key default gen_random_uuid(),
  target_type text not null check (target_type in ('mission', 'comment', 'profile')),
  target_id text not null,
  reporter text not null references community.profiles (id) on delete cascade,
  reason text not null check (reason in ('spam', 'offensive', 'stolen', 'broken', 'other')),
  note text not null default '',
  status text not null default 'open' check (status in ('open', 'done', 'dismissed')),
  handled_by text,
  created_at timestamptz not null default now()
);
create index reports_open on community.reports (status, created_at);

-- what each person did in the last day, for the rate limits
create table community.actions (
  who text not null,
  kind text not null,
  at timestamptz not null default now()
);
create index actions_who on community.actions (who, kind, at);

-- a second lock: nothing in here is read or written except by the functions
alter table community.media enable row level security;
alter table community.profiles enable row level security;
alter table community.missions enable row level security;
alter table community.versions enable row level security;
alter table community.votes enable row level security;
alter table community.pulls enable row level security;
alter table community.comments enable row level security;
alter table community.reports enable row level security;
alter table community.actions enable row level security;

-- ------------------------------------------------------------------ helpers

create function community.fail(msg text) returns void language plpgsql as $$
begin
  raise exception using message = msg, errcode = 'P0001';
end $$;

create function community.me() returns text language sql stable as $$
  select nullif(auth.user_id(), '')
$$;

create function community.as_uuid(s text) returns uuid language plpgsql immutable as $$
begin
  return s::uuid;
exception when others then
  return null;
end $$;

create function community.as_int(s text) returns int language plpgsql immutable as $$
begin
  return s::int;
exception when others then
  return null;
end $$;

-- one line, or (multiline) lines: control characters out, trimmed, capped
create function community.clean(s text, maxlen int, multiline boolean default false) returns text
language sql immutable as $$
  select left(btrim(case when multiline
                         then regexp_replace(replace(coalesce(s, ''), E'\r\n', E'\n'), E'[\\x01-\\x08\\x0B\\x0C\\x0E-\\x1F\\x7F]', '', 'g')
                         else regexp_replace(coalesce(s, ''), E'[\\x01-\\x1F\\x7F]+', ' ', 'g') end), maxlen)
$$;

-- a name folded: lower case, every run of what is not a letter or a digit one space
create function community.name_key(s text) returns text language sql immutable as $$
  select btrim(regexp_replace(lower(coalesce(s, '')), '[^[:alnum:]]+', ' ', 'g'))
$$;

create function community.tag_list() returns text[] language sql immutable as $$
  select array['stealth', 'assault', 'sniper', 'rescue', 'sabotage', 'escape', 'defence', 'story',
               'timed', 'hardcore', 'beginner', 'short']
$$;

-- the person asking, with a profile and allowed to post; or why not
create function community.member() returns community.profiles language plpgsql as $$
declare
  r community.profiles;
begin
  if community.me() is null then
    perform community.fail('Sign in to the community first.');
  end if;
  select * into r from community.profiles where id = community.me();
  if not found then
    perform community.fail('Choose your name for the community first.');
  end if;
  if r.banned then
    perform community.fail('Your account can no longer post to the community.');
  end if;
  return r;
end $$;

create function community.is_mod(who text) returns boolean language sql stable as $$
  select exists (select 1 from community.profiles where id = who and role in ('mod', 'admin') and not banned)
$$;

create function community.rate(what text, per_hour int) returns void language plpgsql as $$
declare
  n int;
begin
  select count(*) into n from community.actions a
   where a.who = community.me() and a.kind = what and a.at > now() - interval '1 hour';
  if n >= per_hour then
    perform community.fail('That is a lot in a short time - try again in a while.');
  end if;
  insert into community.actions (who, kind) values (community.me(), what);
  delete from community.actions a where a.who = community.me() and a.at < now() - interval '1 day';
end $$;

-- a person as others see them
create function community.who(pid text) returns jsonb language sql stable as $$
  select jsonb_build_object('id', r.id, 'handle', r.handle, 'name', r.display_name,
                            'avatar', r.avatar, 'avatar_url', r.avatar_url,
                            'role', case when r.role = 'user' then null else r.role end)
    from community.profiles r where r.id = pid
$$;

create function community.who_short(pid text) returns jsonb language sql stable as $$
  select jsonb_build_object('id', r.id, 'handle', r.handle, 'name', r.display_name)
    from community.profiles r where r.id = pid
$$;

-- is a picture or a plan still part of something
create function community.referenced(mid uuid) returns boolean language sql stable as $$
  select exists (select 1 from community.missions m
                  where m.cover = mid or m.thumb = mid or m.picture = mid or mid = any (m.shots))
      or exists (select 1 from community.versions v where v.plan = mid)
      or exists (select 1 from community.profiles r where r.avatar = mid)
$$;

create function community.drop_media(ids uuid[]) returns void language sql as $$
  delete from community.media d where d.id = any (ids) and not community.referenced(d.id)
$$;

-- a picture or plan of yours, of that kind, not yet part of something else
create function community.own_media(mid uuid, want text, for_mission uuid default null) returns uuid
language plpgsql as $$
declare
  k text;
begin
  select kind into k from community.media where id = mid and owner = community.me();
  if k is null or k <> want then
    perform community.fail('A ' || want || ' was not uploaded - try again.');
  end if;
  if exists (select 1 from community.missions m
              where m.id is distinct from for_mission
                and (m.cover = mid or m.thumb = mid or m.picture = mid or mid = any (m.shots)))
     or exists (select 1 from community.versions v where v.plan = mid and v.mission is distinct from for_mission) then
    perform community.fail('That ' || want || ' belongs to another mission.');
  end if;
  return mid;
end $$;

-- what a card shows
create function community.card(m community.missions) returns jsonb language sql stable as $$
  select jsonb_build_object(
    'id', m.id, 'name', m.name, 'summary', m.summary, 'author', community.who(m.author),
    'level', m.base_level, 'kind', m.base_kind, 'difficulty', m.difficulty, 'tags', to_jsonb(m.tags),
    'play_minutes', m.play_minutes, 'objectives', jsonb_array_length(m.objectives),
    'up', m.up, 'down', m.down, 'score', m.up - m.down, 'comments', m.comments, 'pulls', m.pulls,
    'thumb', m.thumb, 'cover', m.cover, 'version', m.version, 'status', m.status,
    'facts', m.facts,
    'remix_of', case
      when m.parent is not null then
        (select jsonb_build_object('id', q.id, 'name', q.name, 'author', community.who_short(q.author))
           from community.missions q where q.id = m.parent)
      when jsonb_array_length(m.lineage) > 0 then m.lineage -> -1 end,
    'created_at', m.created_at, 'updated_at', m.updated_at)
$$;

create function community.searchable(m community.missions) returns tsvector language sql stable as $$
  select setweight(to_tsvector('english', coalesce(m.name, '')), 'A')
      || setweight(to_tsvector('english', coalesce((select handle || ' ' || display_name from community.profiles
                                                      where id = m.author), '')), 'B')
      || setweight(to_tsvector('english', coalesce(m.summary, '')), 'B')
      || setweight(to_tsvector('english', array_to_string(m.tags, ' ')), 'B')
      || setweight(to_tsvector('english', coalesce(m.description, '')), 'C')
      || setweight(to_tsvector('english', coalesce((select string_agg(o ->> 'text', ' ')
                                                      from jsonb_array_elements(m.objectives) o), '')), 'C')
$$;

create function community.missions_search() returns trigger language plpgsql as $$
begin
  new.search := community.searchable(new);
  return new;
end $$;
create trigger missions_search before insert or update of name, summary, description, tags, objectives
  on community.missions for each row execute function community.missions_search();

create function community.clean_facts(j jsonb) returns jsonb language plpgsql immutable as $$
declare
  out jsonb := '{}'::jsonb;
  k text;
  n int;
begin
  if jsonb_typeof(j) <> 'object' then
    return out;
  end if;
  foreach k in array array['guards', 'cameras', 'alarms', 'cutscenes', 'vehicles', 'pickups', 'placements',
                           'events', 'time_limit'] loop
    n := community.as_int(j ->> k);
    if n is not null and n between 0 and 100000 then
      out := out || jsonb_build_object(k, n);
    end if;
  end loop;
  foreach k in array array['weather', 'music', 'level_name', 'fail_on_alarm'] loop
    if j ? k and jsonb_typeof(j -> k) in ('string', 'boolean') then
      out := out || jsonb_build_object(k, case when jsonb_typeof(j -> k) = 'boolean' then j -> k
                                               else to_jsonb(community.clean(j ->> k, 60)) end);
    end if;
  end loop;
  return out;
end $$;

-- a line of missions a mission carries when the one it came from is gone
create function community.clean_lineage(j jsonb) returns jsonb language plpgsql immutable as $$
declare
  out jsonb := '[]'::jsonb;
  e jsonb;
begin
  if jsonb_typeof(j) <> 'array' then
    return out;
  end if;
  for e in select x from jsonb_array_elements(j) x limit 50 loop
    if jsonb_typeof(e) = 'object' then
      out := out || jsonb_build_array(jsonb_build_object(
        'id', community.as_uuid(e ->> 'id'),
        'version', community.as_int(e ->> 'version'),
        'name', community.clean(e ->> 'name', 60),
        'author', jsonb_build_object('handle', community.clean(e -> 'author' ->> 'handle', 24),
                                     'name', community.clean(e -> 'author' ->> 'name', 40))));
    end if;
  end loop;
  return out;
end $$;

-- a mission's details from what the studio sent: everything (whole), or only
-- what is there; checked, cleaned, the media yours
create function community.apply_details(m community.missions, j jsonb, whole boolean) returns community.missions
language plpgsql as $$
declare
  v text;
  n int;
  a jsonb;
  e jsonb;
  t text[];
  ids uuid[];
  h text;
  pid text;
begin
  if whole or j ? 'name' then
    v := community.clean(j ->> 'name', 200);
    if char_length(v) < 3 or char_length(v) > 60 then
      perform community.fail('The name must be 3 to 60 characters.');
    end if;
    if community.name_key(v) = '' then
      perform community.fail('The name needs a letter or a number.');
    end if;
    if exists (select 1 from community.missions q
                where q.name_key = community.name_key(v) and q.id is distinct from m.id) then
      perform community.fail('There is already a mission called "' || v || '" in the community. Choose another name.');
    end if;
    m.name := v;
    m.name_key := community.name_key(v);
  end if;
  if whole or j ? 'summary' then
    v := community.clean(j ->> 'summary', 400);
    if char_length(v) < 1 or char_length(v) > 140 then
      perform community.fail('The summary must be 1 to 140 characters.');
    end if;
    m.summary := v;
  end if;
  if whole or j ? 'description' then
    v := community.clean(j ->> 'description', 12000, true);
    if char_length(v) > 6000 then
      perform community.fail('The description must be at most 6000 characters.');
    end if;
    m.description := v;
  end if;
  if whole then
    n := community.as_int(j ->> 'level');
    v := j ->> 'kind';
    if n is null or n not between 1 and 14 or v is null or v not in ('copy', 'empty') then
      perform community.fail('The mission needs its base level (1 to 14) and kind (copy or empty).');
    end if;
    if m.base_level is not null and (m.base_level <> n or m.base_kind <> v) then
      perform community.fail('An update keeps the base level it was shared with.');
    end if;
    m.base_level := n;
    m.base_kind := v;
    a := j -> 'objectives';
    if jsonb_typeof(a) <> 'array' or jsonb_array_length(a) < 1 then
      perform community.fail('A mission needs at least one objective.');
    end if;
    if jsonb_array_length(a) > 30 then
      perform community.fail('At most 30 objectives.');
    end if;
    m.objectives := '[]'::jsonb;
    for e in select x from jsonb_array_elements(a) x loop
      v := community.clean(e ->> 'text', 600);
      if v = '' or char_length(v) > 300 then
        perform community.fail('Each objective needs a text of at most 300 characters.');
      end if;
      m.objectives := m.objectives || jsonb_build_array(jsonb_build_object(
        'kind', community.clean(e ->> 'kind', 20), 'text', v));
    end loop;
    m.facts := community.clean_facts(j -> 'facts');
  end if;
  if whole or j ? 'difficulty' then
    v := coalesce(nullif(j ->> 'difficulty', ''), 'normal');
    if v not in ('easy', 'normal', 'hard') then
      perform community.fail('The difficulty is easy, normal or hard.');
    end if;
    m.difficulty := v;
  end if;
  if whole or j ? 'tags' then
    t := '{}';
    if jsonb_typeof(j -> 'tags') = 'array' then
      select coalesce(array_agg(distinct x), '{}') into t from jsonb_array_elements_text(j -> 'tags') x;
    end if;
    if not t <@ community.tag_list() then
      perform community.fail('Unknown tag.');
    end if;
    if cardinality(t) > 6 then
      perform community.fail('At most 6 tags.');
    end if;
    m.tags := t;
  end if;
  if whole or j ? 'play_minutes' then
    n := community.as_int(j ->> 'play_minutes');
    if n is not null and n not between 1 and 600 then
      perform community.fail('The play time is 1 to 600 minutes.');
    end if;
    m.play_minutes := n;
  end if;
  if whole or j ? 'video_url' then
    v := nullif(community.clean(j ->> 'video_url', 400), '');
    if v is not null and (char_length(v) > 300 or v !~ '^https://[^[:space:]]+$') then
      perform community.fail('The video link must be an https:// address.');
    end if;
    m.video_url := v;
  end if;
  if whole or j ? 'allow_remix' then
    m.allow_remix := coalesce((j ->> 'allow_remix')::boolean, true);
  end if;
  if whole or j ? 'cover' then
    m.cover := community.own_media(community.as_uuid(j ->> 'cover'), 'cover', m.id);
    m.thumb := community.own_media(community.as_uuid(j ->> 'thumb'), 'thumb', m.id);
  end if;
  if whole or j ? 'picture' then
    m.picture := case when nullif(j ->> 'picture', '') is null then null
                      else community.own_media(community.as_uuid(j ->> 'picture'), 'picture', m.id) end;
  end if;
  if whole or j ? 'shots' then
    ids := '{}';
    if jsonb_typeof(j -> 'shots') = 'array' then
      if jsonb_array_length(j -> 'shots') > 4 then
        perform community.fail('At most 4 screenshots.');
      end if;
      for v in select x from jsonb_array_elements_text(j -> 'shots') x loop
        ids := ids || community.own_media(community.as_uuid(v), 'shot', m.id);
      end loop;
    end if;
    m.shots := ids;
  end if;
  if whole or j ? 'coauthors' then
    t := '{}';
    if jsonb_typeof(j -> 'coauthors') = 'array' then
      if jsonb_array_length(j -> 'coauthors') > 5 then
        perform community.fail('At most 5 co-authors.');
      end if;
      for h in select x from jsonb_array_elements_text(j -> 'coauthors') x loop
        select id into pid from community.profiles where handle_key = lower(btrim(h, '@ '));
        if pid is null then
          perform community.fail('No one in the community is called @' || h || '.');
        end if;
        if pid <> m.author and not pid = any (t) then
          t := t || pid;
        end if;
      end loop;
    end if;
    m.coauthors := t;
  end if;
  return m;
end $$;

-- the media a mission holds, to let go of when it goes or changes
create function community.mission_media(m community.missions) returns uuid[] language sql stable as $$
  select array[m.cover, m.thumb, m.picture] || m.shots
      || coalesce((select array_agg(v.plan) from community.versions v where v.mission = m.id), '{}')
$$;

-- a mission others may see (a hidden one: its author and the mods)
create function community.visible(mid uuid) returns community.missions language plpgsql stable as $$
declare
  m community.missions;
begin
  select * into m from community.missions where id = mid;
  if not found or (m.status = 'hidden' and m.author is distinct from community.me()
                   and not community.is_mod(community.me())) then
    perform community.fail('That mission is not in the community any more.');
  end if;
  return m;
end $$;

create function community.comment_json(c community.comments, owner text) returns jsonb language sql stable as $$
  select jsonb_build_object(
    'id', c.id, 'parent', c.parent, 'author', community.who(c.author),
    'body', case when c.removed then '' else c.body end, 'removed', c.removed,
    'created_at', c.created_at, 'edited_at', c.edited_at,
    'mine', coalesce(c.author = community.me(), false),
    'can_remove', community.me() is not null and not c.removed
                  and (c.author = community.me() or owner = community.me() or community.is_mod(community.me())))
$$;

-- ------------------------------------------------------------------ the API: reading (guests too)

-- who you are here: your profile, or what to suggest for one
create function public.me(p jsonb default '{}'::jsonb) returns jsonb
language plpgsql stable security definer set search_path = community, public, pg_temp as $$
declare
  r community.profiles;
  sname text;
  simg text;
begin
  if community.me() is null then
    return jsonb_build_object('signed_in', false, 'profile', null);
  end if;
  select * into r from community.profiles where id = community.me();
  if not found then
    -- the account's own name and picture (Neon Auth's user table), to start from
    if to_regclass('neon_auth."user"') is not null then
      execute 'select name, image from neon_auth."user" where id::text = $1' into sname, simg using community.me();
    end if;
    return jsonb_build_object('signed_in', true, 'profile', null,
                              'suggest', jsonb_build_object('name', sname, 'image', simg));
  end if;
  return jsonb_build_object('signed_in', true, 'profile',
    community.who(r.id) || jsonb_build_object('bio', r.bio, 'links', r.links, 'banned', r.banned,
                                              'role', r.role, 'created_at', r.created_at));
end $$;

create function public.handle_free(p jsonb) returns jsonb
language plpgsql stable security definer set search_path = community, public, pg_temp as $$
declare
  h text := btrim(coalesce(p ->> 'handle', ''), '@ ');
begin
  if h !~ '^[A-Za-z0-9][A-Za-z0-9_.-]{2,23}$' then
    return jsonb_build_object('free', false,
      'message', '3 to 24 letters, digits, _ . or -, starting with a letter or a digit.');
  end if;
  if lower(h) in ('admin', 'administrator', 'mod', 'moderator', 'igi', 'igistudio', 'studio', 'support',
                  'community', 'system', 'anonymous', 'guest', 'me', 'null') then
    return jsonb_build_object('free', false, 'message', 'That name is kept for the studio.');
  end if;
  if exists (select 1 from community.profiles where handle_key = lower(h)
                                               and id is distinct from community.me()) then
    return jsonb_build_object('free', false, 'message', '@' || h || ' is taken.');
  end if;
  return jsonb_build_object('free', true);
end $$;

create function public.name_free(p jsonb) returns jsonb
language plpgsql stable security definer set search_path = community, public, pg_temp as $$
declare
  k text := community.name_key(community.clean(p ->> 'name', 200));
begin
  if k = '' then
    return jsonb_build_object('free', false);
  end if;
  return jsonb_build_object('free', not exists (
    select 1 from community.missions where name_key = k and id is distinct from community.as_uuid(p ->> 'except')));
end $$;

-- a page of cards: q (search), sort (new, top, week, month, pulled, relevance),
-- level, difficulty, tag, author (a handle), remixes (only, none), cursor, limit
create function public.list_missions(p jsonb default '{}'::jsonb) returns jsonb
language plpgsql stable security definer set search_path = community, public, pg_temp as $$
declare
  q text := community.clean(p ->> 'q', 100);
  qk text := community.name_key(community.clean(p ->> 'q', 100));
  srt text := coalesce(nullif(p ->> 'sort', ''), case when community.clean(p ->> 'q', 100) <> '' then 'relevance' else 'new' end);
  lim int := least(greatest(coalesce(community.as_int(p ->> 'limit'), 24), 1), 48);
  off int := greatest(coalesce(community.as_int(p ->> 'cursor'), 0), 0);
  lvl int := community.as_int(p ->> 'level');
  dif text := nullif(p ->> 'difficulty', '');
  tg text := nullif(p ->> 'tag', '');
  rmx text := nullif(p ->> 'remixes', '');
  aid text;
  tsq tsquery;
  items jsonb;
  cnt int;
begin
  if srt not in ('new', 'top', 'week', 'month', 'pulled', 'relevance') then
    srt := 'new';
  end if;
  if srt = 'relevance' and q = '' then
    srt := 'new';
  end if;
  if nullif(p ->> 'author', '') is not null then
    select id into aid from community.profiles where handle_key = lower(btrim(p ->> 'author', '@ '));
    if aid is null then
      return jsonb_build_object('items', '[]'::jsonb, 'next', null);
    end if;
  end if;
  if q <> '' then
    tsq := websearch_to_tsquery('english', q);
  end if;
  select coalesce(jsonb_agg(x.card order by x.rn), '[]'::jsonb), count(*) into items, cnt from (
    select community.card(m) as card,
           row_number() over (order by
             case when srt = 'relevance' then ts_rank(m.search, tsq) + word_similarity(qk, m.name_key) end desc nulls last,
             case when srt in ('week', 'month') then
               (select coalesce(sum(v.value), 0) from community.votes v
                 where v.mission = m.id
                   and v.created_at > now() - case when srt = 'week' then interval '7 days' else interval '30 days' end)
             end desc nulls last,
             case when srt in ('top', 'week', 'month') then m.up - m.down end desc nulls last,
             case when srt = 'pulled' then m.pulls end desc nulls last,
             m.created_at desc, m.id) as rn
      from community.missions m
     where (m.status = 'published' or (m.status = 'unlisted' and aid is not null and aid = community.me()))
       and (lvl is null or m.base_level = lvl)
       and (dif is null or m.difficulty = dif)
       and (tg is null or tg = any (m.tags))
       and (aid is null or m.author = aid)
       and (rmx is null or (rmx = 'only' and jsonb_array_length(m.lineage) > 0)
                        or (rmx = 'none' and jsonb_array_length(m.lineage) = 0))
       -- the words, or the name as typed (a letter missing or swapped: "radr" finds "Radar Dome Raid")
       and (q = '' or m.search @@ tsq or word_similarity(qk, m.name_key) >= 0.5
            or (qk <> '' and m.name_key like '%' || qk || '%'))
     order by rn
     limit lim + 1 offset off
  ) x;
  if cnt > lim then
    items := items - lim;
    return jsonb_build_object('items', items, 'next', (off + lim)::text);
  end if;
  return jsonb_build_object('items', items, 'next', null);
end $$;

-- a mission's page
create function public.get_mission(p jsonb) returns jsonb
language plpgsql stable security definer set search_path = community, public, pg_temp as $$
declare
  m community.missions := community.visible(community.as_uuid(p ->> 'id'));
begin
  return community.card(m) || jsonb_build_object(
    'description', m.description, 'objectives', m.objectives, 'picture', m.picture,
    'shots', to_jsonb(m.shots), 'video_url', m.video_url, 'allow_remix', m.allow_remix,
    'lineage', m.lineage, 'parent', m.parent, 'parent_version', m.parent_version,
    'coauthors', (select coalesce(jsonb_agg(community.who(x)), '[]'::jsonb) from unnest(m.coauthors) x),
    'versions', (select coalesce(jsonb_agg(jsonb_build_object(
                   'version', v.version, 'notes', v.notes, 'size', v.size, 'format_version', v.format_version,
                   'studio_version', v.studio_version, 'created_at', v.created_at) order by v.version desc), '[]'::jsonb)
                   from community.versions v where v.mission = m.id),
    'remixes', (select count(*) from community.missions q where q.parent = m.id and q.status <> 'hidden'),
    'my_vote', (select value from community.votes where mission = m.id and voter = community.me()),
    'my_pull', (select version from community.pulls where mission = m.id and puller = community.me()),
    'mine', coalesce(m.author = community.me(), false),
    'can_moderate', community.is_mod(community.me()));
end $$;

-- the missions made from this one, and from those, down the line
create function public.remixes(p jsonb) returns jsonb
language plpgsql stable security definer set search_path = community, public, pg_temp as $$
declare
  root community.missions := community.visible(community.as_uuid(p ->> 'id'));
  out jsonb;
begin
  with recursive t as (
    select q.id, 1 as depth from community.missions q where q.parent = root.id and q.status <> 'hidden'
    union all
    select q.id, t.depth + 1 from community.missions q join t on q.parent = t.id
     where t.depth < 8 and q.status <> 'hidden'
  )
  select coalesce(jsonb_agg(jsonb_build_object(
           'id', m.id, 'name', m.name, 'author', community.who_short(m.author), 'parent', m.parent,
           'depth', t.depth, 'version', m.version, 'score', m.up - m.down, 'status', m.status)
           order by t.depth, m.created_at), '[]'::jsonb)
    into out
    from (select * from t limit 200) t join community.missions m on m.id = t.id;
  return jsonb_build_object('items', out);
end $$;

-- the plan itself, gzipped, in base64: to look at it, or to pull it
create function public.get_plan(p jsonb) returns jsonb
language plpgsql stable security definer set search_path = community, public, pg_temp as $$
declare
  m community.missions := community.visible(community.as_uuid(p ->> 'id'));
  vn int := coalesce(community.as_int(p ->> 'version'), m.version);
  v community.versions;
  b bytea;
begin
  select * into v from community.versions where mission = m.id and version = vn;
  if not found then
    perform community.fail('That version is not there.');
  end if;
  select bytes into b from community.media where id = v.plan;
  return jsonb_build_object('id', m.id, 'version', v.version, 'sha256', v.plan_sha256,
                            'format_version', v.format_version, 'name', m.name,
                            'data', translate(encode(b, 'base64'), E'\n', ''));
end $$;

create function public.get_media(p jsonb) returns jsonb
language plpgsql stable security definer set search_path = community, public, pg_temp as $$
declare
  d community.media;
begin
  select * into d from community.media where id = community.as_uuid(p ->> 'id');
  if not found then
    perform community.fail('That picture is not there any more.');
  end if;
  return jsonb_build_object('id', d.id, 'mime', d.mime, 'data', translate(encode(d.bytes, 'base64'), E'\n', ''));
end $$;

-- the newest version of each of these (the library's "Update available")
create function public.mission_versions(p jsonb) returns jsonb
language plpgsql stable security definer set search_path = community, public, pg_temp as $$
declare
  out jsonb;
begin
  select coalesce(jsonb_agg(jsonb_build_object('id', m.id, 'version', m.version, 'name', m.name,
                                               'status', m.status)), '[]'::jsonb)
    into out
    from community.missions m
   where m.id in (select community.as_uuid(x) from jsonb_array_elements_text(
                    case when jsonb_typeof(p -> 'ids') = 'array' then p -> 'ids' else '[]'::jsonb end) x limit 200)
     and m.status <> 'hidden';
  return jsonb_build_object('items', out);
end $$;

-- comments: the top ones newest first, 30 a page, each with its replies oldest first
create function public.list_comments(p jsonb) returns jsonb
language plpgsql stable security definer set search_path = community, public, pg_temp as $$
declare
  m community.missions := community.visible(community.as_uuid(p ->> 'id'));
  off int := greatest(coalesce(community.as_int(p ->> 'cursor'), 0), 0);
  tops community.comments[];
  out jsonb := '[]'::jsonb;
  c community.comments;
  rp jsonb;
begin
  tops := array(
    select c0 from community.comments c0
     where c0.mission = m.id and c0.parent is null
       and (not c0.removed or exists (select 1 from community.comments r where r.parent = c0.id and not r.removed))
     order by c0.created_at desc, c0.id
     limit 31 offset off);
  foreach c in array tops[1:30] loop
    select coalesce(jsonb_agg(community.comment_json(r, m.author) order by r.created_at, r.id), '[]'::jsonb)
      into rp from community.comments r where r.parent = c.id and not r.removed;
    out := out || jsonb_build_array(community.comment_json(c, m.author) || jsonb_build_object('replies', rp));
  end loop;
  return jsonb_build_object('items', out,
                            'next', case when cardinality(tops) > 30 then (off + 30)::text end);
end $$;

-- a person's page: who they are, what they shared
create function public.get_profile(p jsonb) returns jsonb
language plpgsql stable security definer set search_path = community, public, pg_temp as $$
declare
  r community.profiles;
begin
  select * into r from community.profiles where handle_key = lower(btrim(coalesce(p ->> 'handle', ''), '@ '));
  if not found then
    perform community.fail('There is no one called @' || coalesce(p ->> 'handle', '') || ' in the community.');
  end if;
  return jsonb_build_object(
    'profile', community.who(r.id) || jsonb_build_object('bio', r.bio, 'links', r.links,
                                                         'created_at', r.created_at, 'banned', r.banned),
    'stats', (select jsonb_build_object('missions', count(*), 'score', coalesce(sum(m.up - m.down), 0),
                                        'pulls', coalesce(sum(m.pulls), 0))
                from community.missions m where m.author = r.id and m.status = 'published'),
    'mine', coalesce(r.id = community.me(), false),
    'missions', public.list_missions(jsonb_build_object('author', r.handle, 'sort', 'new',
                                                        'cursor', p ->> 'cursor')));
end $$;

-- ------------------------------------------------------------------ the API: writing (signed in)

-- your profile: made the first time, changed after
create function public.save_profile(p jsonb) returns jsonb
language plpgsql security definer set search_path = community, public, pg_temp as $$
declare
  r community.profiles;
  h text := btrim(coalesce(p ->> 'handle', ''), '@ ');
  chk jsonb;
  nm text := community.clean(p ->> 'name', 100);
  v_bio text := community.clean(p ->> 'bio', 1000, true);
  v_links jsonb := '[]'::jsonb;
  l text;
  av uuid;
  avu text;
begin
  if community.me() is null then
    perform community.fail('Sign in to the community first.');
  end if;
  select * into r from community.profiles where id = community.me();
  if found and r.banned then
    perform community.fail('Your account can no longer post to the community.');
  end if;
  perform community.rate('profile', 30);
  chk := public.handle_free(jsonb_build_object('handle', h));
  if not (chk ->> 'free')::boolean then
    perform community.fail(chk ->> 'message');
  end if;
  if char_length(nm) < 1 or char_length(nm) > 40 then
    perform community.fail('Your name must be 1 to 40 characters.');
  end if;
  if char_length(v_bio) > 500 then
    perform community.fail('A few words about you: at most 500 characters.');
  end if;
  if jsonb_typeof(p -> 'links') = 'array' then
    if jsonb_array_length(p -> 'links') > 4 then
      perform community.fail('At most 4 links.');
    end if;
    for l in select community.clean(x, 400) from jsonb_array_elements_text(p -> 'links') x loop
      if l <> '' then
        if char_length(l) > 200 or l !~ '^https://[^[:space:]]+$' then
          perform community.fail('Links must be https:// addresses.');
        end if;
        v_links := v_links || to_jsonb(l);
      end if;
    end loop;
  end if;
  if nullif(p ->> 'avatar', '') is not null then
    av := community.as_uuid(p ->> 'avatar');
    if not exists (select 1 from community.media where id = av and owner = community.me() and kind = 'avatar') then
      perform community.fail('The picture was not uploaded - try again.');
    end if;
  end if;
  avu := nullif(community.clean(p ->> 'avatar_url', 600), '');
  -- a Google profile picture: the studio fetches no other address a stranger gives it
  if avu is not null and (char_length(avu) > 500 or avu !~ '^https://lh[0-9]+[.]googleusercontent[.]com/[^[:space:]]+$') then
    avu := null;
  end if;
  if r.id is null then
    insert into community.profiles (id, handle, handle_key, display_name, bio, links, avatar, avatar_url)
    values (community.me(), h, lower(h), nm, v_bio, v_links, av, avu);
  else
    update community.profiles
       set handle = h, handle_key = lower(h), display_name = nm, bio = v_bio,
           links = v_links, avatar = av, avatar_url = avu
     where id = community.me();
    if r.avatar is not null and r.avatar is distinct from av then
      perform community.drop_media(array[r.avatar]);
    end if;
    -- the handle is in the search of their missions
    update community.missions set name = name where author = community.me() and r.handle <> h;
  end if;
  return public.me('{}'::jsonb);
end $$;

-- a picture or a plan, uploaded before the mission that holds it
create function public.upload_media(p jsonb) returns jsonb
language plpgsql security definer set search_path = community, public, pg_temp as $$
declare
  r community.profiles := community.member();
  k text := p ->> 'kind';
  mt text := p ->> 'mime';
  b bytea;
  cap int;
  mid uuid;
begin
  perform community.rate('upload', 120);
  cap := case k when 'cover' then 450000 when 'thumb' then 90000 when 'shot' then 450000
                when 'picture' then 300000 when 'avatar' then 120000 when 'plan' then 1500000 end;
  if cap is null then
    perform community.fail('Unknown kind of upload.');
  end if;
  if (k = 'plan') <> (mt = 'application/gzip') or mt not in ('image/webp', 'image/png', 'image/jpeg', 'application/gzip') then
    perform community.fail('That kind of file does not go there.');
  end if;
  begin
    b := decode(coalesce(p ->> 'data', ''), 'base64');
  exception when others then
    perform community.fail('That file could not be read.');
  end;
  if octet_length(b) = 0 or octet_length(b) > cap then
    perform community.fail('That file is too big (at most ' || (cap / 1000) || ' KB).');
  end if;
  if not (case mt
      when 'image/webp' then substring(b from 1 for 4) = '\x52494646'::bytea and substring(b from 9 for 4) = '\x57454250'::bytea
      when 'image/png' then substring(b from 1 for 8) = '\x89504e470d0a1a0a'::bytea
      when 'image/jpeg' then substring(b from 1 for 3) = '\xffd8ff'::bytea
      when 'application/gzip' then substring(b from 1 for 2) = '\x1f8b'::bytea
      else false end) then
    perform community.fail('That file is not what it says it is.');
  end if;
  -- uploads of yours that never became part of anything
  delete from community.media d
   where d.owner = r.id and d.created_at < now() - interval '2 hours' and not community.referenced(d.id);
  insert into community.media (owner, kind, mime, bytes, sha256)
  values (r.id, k, mt, b, encode(sha256(b), 'hex'))
  returning id into mid;
  return jsonb_build_object('id', mid, 'size', octet_length(b));
end $$;

-- share a mission: its details, pictures and plan (uploaded first), and when
-- it came from another, that one ({id, version}) or the line it carries
create function public.publish_mission(p jsonb) returns jsonb
language plpgsql security definer set search_path = community, public, pg_temp as $$
declare
  r community.profiles := community.member();
  m community.missions;
  par community.missions;
  plan_id uuid;
  sha text := lower(coalesce(p ->> 'plan_sha256', ''));
  fv int := coalesce(community.as_int(p ->> 'format_version'), 0);
  pv int;
  lin jsonb;
begin
  perform community.rate('publish', 10);
  m.id := gen_random_uuid();
  m.author := r.id;
  m.version := 1;
  m.status := 'published';
  m.up := 0; m.down := 0; m.comments := 0; m.pulls := 0;
  m.lineage := '[]'::jsonb;
  m.created_at := now();
  m.updated_at := now();
  m := community.apply_details(m, p, true);
  plan_id := community.own_media(community.as_uuid(p ->> 'plan'), 'plan', m.id);
  if sha !~ '^[0-9a-f]{64}$' or fv not between 1 and 99 then
    perform community.fail('The plan came without its fingerprint or format - try again.');
  end if;
  if jsonb_typeof(p -> 'parent') = 'object' then
    select * into par from community.missions where id = community.as_uuid(p -> 'parent' ->> 'id');
    if found then
      if not par.allow_remix and par.author <> r.id then
        perform community.fail('The author of "' || par.name || '" does not allow changed versions of it to be shared.');
      end if;
      pv := coalesce(community.as_int(p -> 'parent' ->> 'version'), par.version);
      if exists (select 1 from community.versions v
                  where v.mission = par.id and v.version = pv and v.plan_sha256 = sha) then
        perform community.fail('Nothing has changed from "' || par.name || '" - change something before sharing it.');
      end if;
      m.parent := par.id;
      m.parent_version := pv;
      lin := par.lineage || jsonb_build_array(jsonb_build_object(
        'id', par.id, 'version', pv, 'name', par.name, 'author', community.who_short(par.author)));
      if jsonb_array_length(lin) > 50 then
        lin := jsonb_build_array(lin -> 0) || (select jsonb_agg(x) from (
          select x from jsonb_array_elements(lin) with ordinality e(x, i) where i > jsonb_array_length(lin) - 49) s);
      end if;
      m.lineage := lin;
    end if;
  end if;
  if m.parent is null and jsonb_typeof(p -> 'lineage') = 'array' then
    -- the one it came from is gone: the line the mission carries
    m.lineage := community.clean_lineage(p -> 'lineage');
  end if;
  insert into community.missions select (m).*;
  insert into community.versions (mission, version, plan, plan_sha256, size, format_version, studio_version, notes)
  values (m.id, 1, plan_id, sha, (select octet_length(bytes) from community.media where id = plan_id), fv,
          community.clean(p ->> 'studio_version', 20), community.clean(p ->> 'notes', 2000, true));
  return jsonb_build_object('id', m.id, 'version', 1, 'name', m.name);
end $$;

-- a new version of a mission of yours: a new plan, notes, and its details again
create function public.publish_version(p jsonb) returns jsonb
language plpgsql security definer set search_path = community, public, pg_temp as $$
declare
  r community.profiles := community.member();
  m community.missions;
  old uuid[];
  plan_id uuid;
  sha text := lower(coalesce(p ->> 'plan_sha256', ''));
  fv int := coalesce(community.as_int(p ->> 'format_version'), 0);
  v_notes text := community.clean(p ->> 'notes', 2000, true);
begin
  select * into m from community.missions where id = community.as_uuid(p ->> 'id') for update;
  if not found or m.author <> r.id then
    perform community.fail('That mission is not yours to update.');
  end if;
  if m.status = 'hidden' then
    perform community.fail('A moderator has hidden that mission.');
  end if;
  perform community.rate('publish', 10);
  if char_length(v_notes) < 1 or char_length(v_notes) > 1000 then
    perform community.fail('Say what is new in this version (at most 1000 characters).');
  end if;
  old := community.mission_media(m);
  m := community.apply_details(m, p, true);
  plan_id := community.own_media(community.as_uuid(p ->> 'plan'), 'plan', m.id);
  if sha !~ '^[0-9a-f]{64}$' or fv not between 1 and 99 then
    perform community.fail('The plan came without its fingerprint or format - try again.');
  end if;
  if exists (select 1 from community.versions v where v.mission = m.id and v.version = m.version and v.plan_sha256 = sha) then
    perform community.fail('The mission has not changed since version ' || m.version || '.');
  end if;
  m.version := m.version + 1;
  m.updated_at := now();
  update community.missions t
     set name = m.name, name_key = m.name_key, summary = m.summary, description = m.description,
         difficulty = m.difficulty, tags = m.tags, play_minutes = m.play_minutes, objectives = m.objectives,
         facts = m.facts, cover = m.cover, thumb = m.thumb, picture = m.picture, shots = m.shots,
         video_url = m.video_url, allow_remix = m.allow_remix, coauthors = m.coauthors,
         version = m.version, updated_at = m.updated_at
   where t.id = m.id;
  insert into community.versions (mission, version, plan, plan_sha256, size, format_version, studio_version, notes)
  values (m.id, m.version, plan_id, sha, (select octet_length(bytes) from community.media where id = plan_id), fv,
          community.clean(p ->> 'studio_version', 20), v_notes);
  perform community.drop_media(old);
  return jsonb_build_object('id', m.id, 'version', m.version, 'name', m.name);
end $$;

-- the details of a mission of yours, without a new version
create function public.update_details(p jsonb) returns jsonb
language plpgsql security definer set search_path = community, public, pg_temp as $$
declare
  r community.profiles := community.member();
  m community.missions;
  old uuid[];
begin
  select * into m from community.missions where id = community.as_uuid(p ->> 'id') for update;
  if not found or m.author <> r.id then
    perform community.fail('That mission is not yours to change.');
  end if;
  perform community.rate('details', 60);
  old := community.mission_media(m);
  m := community.apply_details(m, p - 'id' - 'level' - 'kind' - 'objectives' - 'facts', false);
  update community.missions t
     set name = m.name, name_key = m.name_key, summary = m.summary, description = m.description,
         difficulty = m.difficulty, tags = m.tags, play_minutes = m.play_minutes,
         cover = m.cover, thumb = m.thumb, picture = m.picture, shots = m.shots,
         video_url = m.video_url, allow_remix = m.allow_remix, coauthors = m.coauthors, updated_at = now()
   where t.id = m.id;
  perform community.drop_media(old);
  return public.get_mission(jsonb_build_object('id', m.id));
end $$;

-- listed (published) or not (unlisted: only with its link); a moderator also hides
create function public.set_status(p jsonb) returns jsonb
language plpgsql security definer set search_path = community, public, pg_temp as $$
declare
  r community.profiles := community.member();
  m community.missions;
  st text := p ->> 'status';
  modr boolean := community.is_mod(r.id);
begin
  select * into m from community.missions where id = community.as_uuid(p ->> 'id') for update;
  if not found or (m.author <> r.id and not modr) then
    perform community.fail('That mission is not yours to change.');
  end if;
  if st not in ('published', 'unlisted', 'hidden') or (st = 'hidden' and not modr) then
    perform community.fail('Unknown status.');
  end if;
  if m.status = 'hidden' and not modr then
    perform community.fail('A moderator has hidden that mission.');
  end if;
  update community.missions set status = st where id = m.id;
  return jsonb_build_object('id', m.id, 'status', st);
end $$;

-- gone for good: its versions, votes, comments and pictures; its name free again
create function public.delete_mission(p jsonb) returns jsonb
language plpgsql security definer set search_path = community, public, pg_temp as $$
declare
  r community.profiles := community.member();
  m community.missions;
  v_media uuid[];
begin
  select * into m from community.missions where id = community.as_uuid(p ->> 'id') for update;
  if not found or (m.author <> r.id and not community.is_mod(r.id)) then
    perform community.fail('That mission is not yours to delete.');
  end if;
  v_media := community.mission_media(m);
  delete from community.missions where id = m.id;
  perform community.drop_media(v_media);
  update community.reports set status = 'done', handled_by = r.id
   where target_type = 'mission' and target_id = m.id::text and status = 'open';
  return jsonb_build_object('deleted', m.id);
end $$;

-- up (1), down (-1), or neither (0)
create function public.set_vote(p jsonb) returns jsonb
language plpgsql security definer set search_path = community, public, pg_temp as $$
declare
  r community.profiles := community.member();
  m community.missions := community.visible(community.as_uuid(p ->> 'id'));
  val int := community.as_int(p ->> 'value');
  was int;
  u int;
  d int;
begin
  if m.author = r.id then
    perform community.fail('You cannot vote for your own mission.');
  end if;
  if val is null or val not in (-1, 0, 1) then
    perform community.fail('A vote is up or down.');
  end if;
  perform community.rate('vote', 300);
  select value into was from community.votes where mission = m.id and voter = r.id;
  was := coalesce(was, 0);
  if val = 0 then
    delete from community.votes where mission = m.id and voter = r.id;
  else
    insert into community.votes (mission, voter, value) values (m.id, r.id, val)
    on conflict (mission, voter) do update set value = excluded.value, created_at = now();
  end if;
  update community.missions
     set up = up + (val = 1)::int - (was = 1)::int, down = down + (val = -1)::int - (was = -1)::int
   where id = m.id
  returning up, down into u, d;
  return jsonb_build_object('id', m.id, 'up', u, 'down', d, 'score', u - d, 'my_vote', nullif(val, 0));
end $$;

-- you pulled it into your studio (counted once a person)
create function public.record_pull(p jsonb) returns jsonb
language plpgsql security definer set search_path = community, public, pg_temp as $$
declare
  r community.profiles := community.member();
  m community.missions := community.visible(community.as_uuid(p ->> 'id'));
  vn int := coalesce(community.as_int(p ->> 'version'), m.version);
  n int;
begin
  perform community.rate('pull', 120);
  if not exists (select 1 from community.pulls where mission = m.id and puller = r.id) then
    update community.missions set pulls = pulls + 1 where id = m.id;
  end if;
  insert into community.pulls (mission, puller, version) values (m.id, r.id, vn)
  on conflict (mission, puller) do update set version = excluded.version, created_at = now();
  select pulls into n from community.missions where id = m.id;
  return jsonb_build_object('id', m.id, 'pulls', n);
end $$;

create function public.add_comment(p jsonb) returns jsonb
language plpgsql security definer set search_path = community, public, pg_temp as $$
declare
  r community.profiles := community.member();
  m community.missions := community.visible(community.as_uuid(p ->> 'id'));
  v_body text := community.clean(p ->> 'body', 4000, true);
  par uuid;
  c community.comments;
begin
  if m.status = 'hidden' then
    perform community.fail('A moderator has hidden that mission.');
  end if;
  if char_length(v_body) < 1 or char_length(v_body) > 2000 then
    perform community.fail('A comment is 1 to 2000 characters.');
  end if;
  perform community.rate('comment', 60);
  if nullif(p ->> 'parent', '') is not null then
    select id into par from community.comments
     where id = community.as_uuid(p ->> 'parent') and mission = m.id and parent is null;
    if par is null then
      perform community.fail('That comment is not there any more.');
    end if;
  end if;
  insert into community.comments (mission, author, parent, body) values (m.id, r.id, par, v_body)
  returning * into c;
  update community.missions set comments = comments + 1 where id = m.id;
  return community.comment_json(c, m.author) || jsonb_build_object('replies', '[]'::jsonb);
end $$;

create function public.edit_comment(p jsonb) returns jsonb
language plpgsql security definer set search_path = community, public, pg_temp as $$
declare
  r community.profiles := community.member();
  c community.comments;
  v_body text := community.clean(p ->> 'body', 4000, true);
begin
  select * into c from community.comments where id = community.as_uuid(p ->> 'id') for update;
  if not found or c.author <> r.id or c.removed then
    perform community.fail('That comment is not yours to change.');
  end if;
  if char_length(v_body) < 1 or char_length(v_body) > 2000 then
    perform community.fail('A comment is 1 to 2000 characters.');
  end if;
  perform community.rate('comment', 60);
  update community.comments set body = v_body, edited_at = now() where id = c.id returning * into c;
  return community.comment_json(c, (select author from community.missions where id = c.mission));
end $$;

-- yours: gone (or "removed" when it has replies); on your mission, or a moderator: removed
create function public.delete_comment(p jsonb) returns jsonb
language plpgsql security definer set search_path = community, public, pg_temp as $$
declare
  r community.profiles := community.member();
  c community.comments;
  v_owner text;
begin
  select * into c from community.comments where id = community.as_uuid(p ->> 'id') for update;
  if not found or c.removed then
    perform community.fail('That comment is not there any more.');
  end if;
  select author into v_owner from community.missions where id = c.mission;
  if c.author <> r.id and v_owner <> r.id and not community.is_mod(r.id) then
    perform community.fail('That comment is not yours to remove.');
  end if;
  if c.author = r.id and not exists (select 1 from community.comments where parent = c.id and not removed) then
    -- its removed replies go with it
    delete from community.comments where id = c.id;
  else
    update community.comments set removed = true where id = c.id;
  end if;
  update community.missions set comments = greatest(comments - 1, 0) where id = c.mission;
  update community.reports set status = 'done', handled_by = r.id
   where target_type = 'comment' and target_id = c.id::text and status = 'open';
  return jsonb_build_object('deleted', c.id);
end $$;

create function public.report(p jsonb) returns jsonb
language plpgsql security definer set search_path = community, public, pg_temp as $$
declare
  r community.profiles := community.member();
  tt text := p ->> 'type';
  tid text := p ->> 'target';
  rs text := p ->> 'reason';
begin
  perform community.rate('report', 20);
  if rs is null or rs not in ('spam', 'offensive', 'stolen', 'broken', 'other') then
    perform community.fail('Say what is wrong with it.');
  end if;
  if not (case tt
      when 'mission' then exists (select 1 from community.missions where id = community.as_uuid(tid))
      when 'comment' then exists (select 1 from community.comments where id = community.as_uuid(tid))
      when 'profile' then exists (select 1 from community.profiles where id = tid)
      else false end) then
    perform community.fail('That is not there any more.');
  end if;
  insert into community.reports (target_type, target_id, reporter, reason, note)
  values (tt, tid, r.id, rs, community.clean(p ->> 'note', 1000, true));
  return jsonb_build_object('reported', true);
end $$;

-- your account's community side, gone: profile, missions, votes, comments, pulls
-- (the account itself is deleted with Neon Auth)
create function public.delete_my_data(p jsonb default '{}'::jsonb) returns jsonb
language plpgsql security definer set search_path = community, public, pg_temp as $$
declare
  me text := community.me();
  v_media uuid[];
begin
  if me is null then
    perform community.fail('Sign in to the community first.');
  end if;
  -- the counts on everyone else's missions
  update community.missions m set up = m.up - x.u, down = m.down - x.d
    from (select mission, count(*) filter (where value = 1) u, count(*) filter (where value = -1) d
            from community.votes where voter = me group by mission) x
   where m.id = x.mission;
  update community.missions m set pulls = greatest(m.pulls - x.n, 0)
    from (select mission, count(*) n from community.pulls where puller = me group by mission) x
   where m.id = x.mission;
  update community.missions m set comments = greatest(m.comments - x.n, 0)
    from (select c.mission, count(*) n from community.comments c
           where not c.removed
             and (c.author = me or c.parent in (select id from community.comments where author = me))
           group by c.mission) x
   where m.id = x.mission;
  select coalesce(array_agg(u), '{}') into v_media
    from community.missions m, unnest(community.mission_media(m)) u where m.author = me;
  delete from community.missions where author = me;
  delete from community.profiles where id = me;
  delete from community.media where owner = me;
  perform community.drop_media(v_media);
  delete from community.actions where who = me;
  return jsonb_build_object('deleted', true);
end $$;

-- ------------------------------------------------------------------ the API: moderating

create function public.mod_reports(p jsonb default '{}'::jsonb) returns jsonb
language plpgsql stable security definer set search_path = community, public, pg_temp as $$
declare
  out jsonb;
begin
  if not community.is_mod(community.me()) then
    perform community.fail('Only moderators see the reports.');
  end if;
  select coalesce(jsonb_agg(jsonb_build_object(
           'id', x.id, 'type', x.target_type, 'target', x.target_id, 'reason', x.reason, 'note', x.note,
           'status', x.status, 'created_at', x.created_at, 'reporter', community.who_short(x.reporter),
           'what', case x.target_type
             when 'mission' then (select jsonb_build_object('name', m.name, 'status', m.status,
                                                            'author', community.who_short(m.author))
                                    from community.missions m where m.id = community.as_uuid(x.target_id))
             when 'comment' then (select jsonb_build_object('body', c.body, 'mission', c.mission,
                                                            'removed', c.removed, 'author', community.who_short(c.author))
                                    from community.comments c where c.id = community.as_uuid(x.target_id))
             when 'profile' then community.who(x.target_id) end)
           order by x.created_at desc), '[]'::jsonb)
    into out
    from (select * from community.reports where status = coalesce(nullif(p ->> 'status', ''), 'open')
           order by created_at desc limit 100) x;
  return jsonb_build_object('items', out);
end $$;

-- dismiss, hide / unhide the mission, remove the comment, ban / unban the person
create function public.mod_act(p jsonb) returns jsonb
language plpgsql security definer set search_path = community, public, pg_temp as $$
declare
  r community.profiles := community.member();
  rep community.reports;
  act text := p ->> 'action';
  tgt text;
begin
  if not community.is_mod(r.id) then
    perform community.fail('Only moderators can do that.');
  end if;
  select * into rep from community.reports where id = community.as_uuid(p ->> 'report');
  if found then
    tgt := rep.target_id;
  else
    tgt := p ->> 'target';
  end if;
  case act
    when 'dismiss' then null;
    when 'hide' then update community.missions set status = 'hidden' where id = community.as_uuid(tgt);
    when 'unhide' then update community.missions set status = 'published' where id = community.as_uuid(tgt);
    when 'remove_comment' then
      update community.missions m set comments = greatest(m.comments - 1, 0)
        from community.comments c where c.id = community.as_uuid(tgt) and not c.removed and m.id = c.mission;
      update community.comments set removed = true where id = community.as_uuid(tgt);
    when 'ban' then
      update community.profiles set banned = true
       where id = coalesce((select author from community.missions where id = community.as_uuid(tgt)),
                           (select author from community.comments where id = community.as_uuid(tgt)), tgt)
         and role <> 'admin';
    when 'unban' then update community.profiles set banned = false where id = tgt;
    else perform community.fail('Unknown action.');
  end case;
  if rep.id is not null then
    update community.reports set status = case when act = 'dismiss' then 'dismissed' else 'done' end,
                                 handled_by = r.id
     where id = rep.id;
  end if;
  return jsonb_build_object('done', act);
end $$;

-- the admin makes moderators
create function public.set_role(p jsonb) returns jsonb
language plpgsql security definer set search_path = community, public, pg_temp as $$
declare
  r community.profiles := community.member();
  rl text := p ->> 'role';
begin
  if r.role <> 'admin' then
    perform community.fail('Only the admin can do that.');
  end if;
  if rl not in ('user', 'mod') then
    perform community.fail('A role is user or mod.');
  end if;
  update community.profiles set role = rl where handle_key = lower(btrim(p ->> 'handle', '@ ')) and role <> 'admin';
  return jsonb_build_object('handle', p ->> 'handle', 'role', rl);
end $$;

-- ------------------------------------------------------------------ who may call what

revoke all on all functions in schema community from public;
revoke all on function
  public.me(jsonb), public.handle_free(jsonb), public.name_free(jsonb), public.list_missions(jsonb),
  public.get_mission(jsonb), public.remixes(jsonb), public.get_plan(jsonb), public.get_media(jsonb),
  public.mission_versions(jsonb), public.list_comments(jsonb), public.get_profile(jsonb),
  public.save_profile(jsonb), public.upload_media(jsonb), public.publish_mission(jsonb),
  public.publish_version(jsonb), public.update_details(jsonb), public.set_status(jsonb),
  public.delete_mission(jsonb), public.set_vote(jsonb), public.record_pull(jsonb), public.add_comment(jsonb),
  public.edit_comment(jsonb), public.delete_comment(jsonb), public.report(jsonb), public.delete_my_data(jsonb),
  public.mod_reports(jsonb), public.mod_act(jsonb), public.set_role(jsonb)
from public;

grant execute on function
  public.me(jsonb), public.handle_free(jsonb), public.name_free(jsonb), public.list_missions(jsonb),
  public.get_mission(jsonb), public.remixes(jsonb), public.get_plan(jsonb), public.get_media(jsonb),
  public.mission_versions(jsonb), public.list_comments(jsonb), public.get_profile(jsonb)
to anonymous, authenticated;

grant execute on function
  public.save_profile(jsonb), public.upload_media(jsonb), public.publish_mission(jsonb),
  public.publish_version(jsonb), public.update_details(jsonb), public.set_status(jsonb),
  public.delete_mission(jsonb), public.set_vote(jsonb), public.record_pull(jsonb), public.add_comment(jsonb),
  public.edit_comment(jsonb), public.delete_comment(jsonb), public.report(jsonb), public.delete_my_data(jsonb),
  public.mod_reports(jsonb), public.mod_act(jsonb), public.set_role(jsonb)
to authenticated;
