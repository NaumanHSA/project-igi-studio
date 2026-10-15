// Runs the community's migrations on its Neon database, each once, in order.
//
//   DATABASE_URL=postgresql://... node migrate.mjs           the ones not run yet
//   DATABASE_URL=postgresql://... node migrate.mjs --check   what Neon has, and what has run
//
// The address (with its password) comes from the environment only: it is the
// database owner's, and never goes into the repository or the studio. The
// studio needs only the project's two public addresses: the Data API and Neon
// Auth (studio/server/community.py).
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import pg from 'pg'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const MIGRATIONS = path.join(HERE, 'migrations')
const url = process.env.DATABASE_URL
if (!url) {
  console.log('Set DATABASE_URL to the Neon database\'s address (the console\'s connection string).')
  process.exit(2)
}
// pg reads sslmode=require as verify-full already; said outright, it does not warn
const db = new pg.Client({ connectionString: url.replace(/sslmode=require(?=&|$)/, 'sslmode=verify-full') })
await db.connect()
const one = async (sql, p) => (await db.query(sql, p)).rows[0]

async function check() {
  const v = await one('select current_user as who, current_database() as db, version() as v')
  console.log(`connected as ${v.who} to ${v.db}: ${v.v.split(',')[0]}`)
  for (const r of ['anonymous', 'authenticated'])
    console.log(`  role ${r}: ${(await one('select count(*)::int n from pg_roles where rolname = $1', [r])).n ? 'there' : 'MISSING (turn the Data API on)'}`)
  const ext = (await db.query(`select extname, extversion from pg_extension order by 1`)).rows
  console.log('  extensions: ' + ext.map(e => e.extname + ' ' + e.extversion).join(', '))
  const fn = await one(`select count(*)::int n from pg_proc p join pg_namespace s on s.oid = p.pronamespace
                         where s.nspname = 'auth' and p.proname = 'user_id'`)
  console.log(`  auth.user_id(): ${fn.n ? 'there' : 'MISSING (the Data API brings it)'}`)
  const na = await one(`select to_regclass('neon_auth."user"') is not null as ok`)
  console.log(`  Neon Auth's users: ${na.ok ? 'there' : 'not there (turn Neon Auth on)'}`)
  const done = await one(`select to_regclass('community._migrations') is not null as ok`)
  const ran = done.ok ? (await db.query('select name, at from community._migrations order by name')).rows : []
  console.log('  migrations run: ' + (ran.length ? ran.map(r => r.name).join(', ') : 'none'))
}

async function migrate() {
  // kept in the schema the Data API does not show
  await db.query('create schema if not exists community')
  await db.query('create table if not exists community._migrations (name text primary key, at timestamptz not null default now())')
  const done = new Set((await db.query('select name from community._migrations')).rows.map(r => r.name))
  const todo = fs.readdirSync(MIGRATIONS).filter(f => f.endsWith('.sql') && !done.has(f)).sort()
  if (!todo.length) { console.log('Nothing to run: every migration has run.'); return }
  for (const f of todo) {
    const text = fs.readFileSync(path.join(MIGRATIONS, f), 'utf8')
    try {
      await db.query('begin')
      await db.query(text)
      await db.query('insert into community._migrations (name) values ($1)', [f])
      await db.query('commit')
      console.log('ran ' + f)
    } catch (e) {
      await db.query('rollback')
      const at = e.position ? text.slice(0, Number(e.position)).split(/\n/).length : null
      console.log(`${f}${at ? ' line ' + at : ''}: ${e.message} - nothing of it was kept`)
      process.exitCode = 1
      return
    }
  }
  // the Data API reads the functions afresh
  await db.query(`notify pgrst, 'reload schema'`)
}

try {
  if (process.argv.includes('--check')) await check()
  else await migrate()
} finally {
  await db.end()
}
