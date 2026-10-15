// The community's database on this machine: PGlite (Postgres in WebAssembly)
// with what Neon has before our migration runs - the API roles, auth.user_id()
// and Neon Auth's user table - and then cloud/migrations/*.sql, in order.
//
//   const db = await openDb({ dir })        dir: a folder to keep it in; none: in memory
//   await db.call('list_missions', {...}, { user: 'u1' })     as the Data API would run it
//   await db.sql('select ...')                                as the owner (tests, tools)
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { PGlite } from '@electric-sql/pglite'
import { pg_trgm } from '@electric-sql/pglite/contrib/pg_trgm'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const MIGRATIONS = path.resolve(HERE, '..', 'migrations')

// What Neon provides: the roles the Data API switches to, the person from the
// JWT (pg_session_jwt's auth.user_id(); here a setting the server makes for
// each request), and Neon Auth's own tables (the users).
const NEON = `
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'anonymous') then create role anonymous nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then create role authenticated nologin; end if;
end $$;
create schema if not exists auth;
create or replace function auth.user_id() returns text language sql stable as
  $$ select nullif(current_setting('request.user_id', true), '') $$;
grant usage on schema auth to anonymous, authenticated;
grant execute on function auth.user_id() to anonymous, authenticated;
grant usage on schema public to anonymous, authenticated;
create schema if not exists neon_auth;
create table if not exists neon_auth."user" (
  id text primary key, name text not null, email text not null unique, "emailVerified" boolean not null default false,
  image text, "createdAt" timestamptz not null default now(), "updatedAt" timestamptz not null default now());
-- the stand-in's own: passwords, sessions, codes (Neon Auth keeps these its own way)
create table if not exists neon_auth.dev_password (user_id text primary key, salt text not null, hash text not null);
create table if not exists neon_auth.dev_session (token text primary key, user_id text not null, expires_at timestamptz not null);
create table if not exists neon_auth.dev_code (email text not null, kind text not null, code text not null,
  expires_at timestamptz not null, primary key (email, kind));
create table if not exists neon_auth.dev_verifier (verifier text primary key, token text not null, expires_at timestamptz not null);
create table if not exists public._migrations (name text primary key, at timestamptz not null default now());
`

export async function openDb({ dir } = {}) {
  if (dir) fs.mkdirSync(dir, { recursive: true })
  const pg = await PGlite.create({ dataDir: dir || undefined, extensions: { pg_trgm } })
  await pg.exec(NEON)
  const done = new Set((await pg.query('select name from public._migrations')).rows.map(r => r.name))
  for (const f of fs.readdirSync(MIGRATIONS).filter(f => f.endsWith('.sql')).sort()) {
    if (done.has(f)) continue
    const text = fs.readFileSync(path.join(MIGRATIONS, f), 'utf8')
    try {
      await pg.transaction(async tx => {
        await tx.exec(text)
        await tx.query('insert into public._migrations (name) values ($1)', [f])
      })
    } catch (e) {
      // where in the file, for whoever is writing it
      const at = e.position ? text.slice(0, Number(e.position)).split(/\n/).length : null
      throw new Error(`${f}${at ? ' line ' + at : ''}: ${e.message}${e.where ? ' (' + e.where + ')' : ''}`)
    }
  }
  // one request at a time: the role and the person are per connection
  let chain = Promise.resolve()
  const serial = fn => { const r = chain.then(fn, fn); chain = r.catch(() => {}); return r }
  return {
    pg,
    /** Runs public.<fn>(p) as the Data API would: as anonymous, or authenticated as user. */
    call(fn, p = {}, { user = null } = {}) {
      if (!/^[a-z_]{1,40}$/.test(fn)) return Promise.reject(Object.assign(new Error('Not found'), { status: 404 }))
      return serial(async () => {
        await pg.query(`select set_config('request.user_id', $1, false)`, [user || ''])
        await pg.exec(`set role ${user ? 'authenticated' : 'anonymous'}`)
        try {
          const r = await pg.query(`select public.${fn}($1::jsonb) as r`, [JSON.stringify(p ?? {})])
          return r.rows[0].r
        } catch (e) {
          throw pgError(e)
        } finally {
          await pg.exec('reset role')
          await pg.query(`select set_config('request.user_id', '', false)`)
        }
      })
    },
    /** SQL as the owner. */
    sql(text, params) { return serial(() => pg.query(text, params)) },
    close() { return pg.close() },
  }
}

// a Postgres error as PostgREST reports it
function pgError(e) {
  const code = e.code || ''
  const out = new Error(e.message)
  out.code = code
  out.status = code === 'P0001' ? 400 : code === '42883' ? 404 : code === '42501' ? 401 : 400
  out.body = { code, message: e.message, details: e.detail || null, hint: e.hint || null }
  return out
}
