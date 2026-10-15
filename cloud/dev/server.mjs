// A stand-in for the community's Neon project, on this machine: the same
// migration in PGlite (db.mjs), answering the same HTTP calls the studio makes
// to Neon's Data API and to Neon Auth, with a pretend Google page. For
// development and the tests; nothing here is ever used by the real community.
//
//   node server.mjs [--port 8790] [--memory] [--dir <folder>] [--tools]
//
//   <base>/neondb/rest/v1/rpc/<fn>      the Data API: POST {"p": {...}}, Bearer JWT
//   <base>/neondb/auth/...              Neon Auth (Better Auth): email, codes, Google, sessions
//   <base>/dev/google                   the pretend Google sign-in page
//   <base>/dev/mail?to=<email>          the last code "emailed" there (also printed)
//   <base>/dev/sql                      POST {sql}: SQL as the owner (--tools only)
//
// Prints "COMMUNITY_DEV_READY port=N" once it listens.
import crypto from 'node:crypto'
import fs from 'node:fs'
import http from 'node:http'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { openDb } from './db.mjs'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const arg = (k, d) => { const i = process.argv.indexOf('--' + k); return i > 0 ? process.argv[i + 1] : d }
const has = k => process.argv.includes('--' + k)
const PORT = Number(arg('port', process.env.PORT || 8790))
const DIR = has('memory') ? null : path.resolve(arg('dir', path.join(HERE, '.data')))
const TOOLS = has('tools')
const JWT_TTL = Number(process.env.COMMUNITY_DEV_JWT_TTL || 900)        // seconds, as Neon's 15 minutes
const COOKIE = '__Secure-neonauth.session_token'
// the origins Neon Auth would trust: the studio's sign-in listener
const TRUSTED = (process.env.COMMUNITY_DEV_TRUSTED || 'http://127.0.0.1:38461,http://127.0.0.1:41923,http://127.0.0.1:45127')
  .split(',').map(s => s.trim()).filter(Boolean)

const db = await openDb({ dir: DIR })
const SECRET = (() => {
  if (!DIR) return crypto.randomBytes(32)
  const f = path.join(DIR, 'jwt-secret')
  if (!fs.existsSync(f)) fs.writeFileSync(f, crypto.randomBytes(32).toString('hex'))
  return Buffer.from(fs.readFileSync(f, 'utf8').trim(), 'hex')
})()
const MAIL = new Map()          // email -> the last message
const STATES = new Map()        // social sign-in state -> callbackURL

// ------------------------------------------------------------ small things
const b64u = b => Buffer.from(b).toString('base64url')
function jwt(claims) {
  const now = Math.floor(Date.now() / 1000)
  const body = b64u(JSON.stringify({ alg: 'HS256', typ: 'JWT' })) + '.' + b64u(JSON.stringify({ iat: now, exp: now + JWT_TTL, ...claims }))
  return body + '.' + b64u(crypto.createHmac('sha256', SECRET).update(body).digest())
}
function readJwt(tok) {
  const [h, p, s] = String(tok || '').split('.')
  if (!s) return null
  const want = b64u(crypto.createHmac('sha256', SECRET).update(h + '.' + p).digest())
  if (want.length !== s.length || !crypto.timingSafeEqual(Buffer.from(want), Buffer.from(s))) return null
  const c = JSON.parse(Buffer.from(p, 'base64url').toString())
  return c.exp > Date.now() / 1000 ? c : { expired: true }
}
const send = (res, status, body, headers = {}) => {
  res.writeHead(status, { 'Content-Type': 'application/json', ...headers })
  res.end(body === undefined ? '' : JSON.stringify(body))
}
const fail = (res, status, code, message) => send(res, status, { code, message })
function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = []
    req.on('data', c => chunks.push(c))
    req.on('end', () => {
      const s = Buffer.concat(chunks).toString()
      if (!s) return resolve({})
      if ((req.headers['content-type'] || '').includes('application/x-www-form-urlencoded'))
        return resolve(Object.fromEntries(new URLSearchParams(s)))
      try { resolve(JSON.parse(s)) } catch (e) { reject(e) }
    })
    req.on('error', reject)
  })
}
const cookieOf = req => {
  for (const part of String(req.headers.cookie || '').split(/;\s*/)) {
    const i = part.indexOf('=')
    if (i > 0 && part.slice(0, i) === COOKIE) return decodeURIComponent(part.slice(i + 1))
  }
  return null
}
const setCookie = tok => `${COOKIE}=${encodeURIComponent(tok)}; Path=/; HttpOnly; Secure; SameSite=None; Max-Age=${tok ? 2592000 : 0}`
const trusted = o => !!o && TRUSTED.includes(String(o).replace(/\/$/, ''))
const trustedUrl = u => { try { return trusted(new URL(u).origin) } catch { return false } }
const hashPw = (pw, salt) => crypto.scryptSync(String(pw), salt, 32).toString('hex')
const code6 = () => String(crypto.randomInt(0, 1e6)).padStart(6, '0')

async function userBy(field, value) {
  const r = await db.sql(`select id, name, email, "emailVerified", image, "createdAt" from neon_auth."user" where ${field} = $1`, [value])
  return r.rows[0] || null
}
const userJson = u => u && { id: u.id, name: u.name, email: u.email, emailVerified: u.emailVerified, image: u.image, createdAt: u.createdAt }
async function newSession(userId) {
  const token = crypto.randomBytes(24).toString('base64url')
  await db.sql(`insert into neon_auth.dev_session (token, user_id, expires_at) values ($1, $2, now() + interval '30 days')`, [token, userId])
  return token
}
async function sessionOf(token) {
  if (!token) return null
  const r = await db.sql(`select s.token, s.user_id, s.expires_at from neon_auth.dev_session s where s.token = $1 and s.expires_at > now()`, [token])
  if (!r.rows[0]) return null
  const u = await userBy('id', r.rows[0].user_id)
  return u && { session: { token: r.rows[0].token, userId: u.id, expiresAt: r.rows[0].expires_at }, user: userJson(u) }
}
async function mail(email, kind) {
  const code = code6()
  await db.sql(`insert into neon_auth.dev_code (email, kind, code, expires_at) values ($1, $2, $3, now() + interval '10 minutes')
                on conflict (email, kind) do update set code = excluded.code, expires_at = excluded.expires_at`, [email, kind, code])
  MAIL.set(email, { kind, code, at: Date.now() })
  console.log(`[mail] to ${email}: your ${kind} code is ${code}`)
}
async function useCode(email, kind, code) {
  const r = await db.sql(`delete from neon_auth.dev_code where email = $1 and kind = $2 and code = $3 and expires_at > now() returning email`,
    [email, kind, String(code || '')])
  return r.rows.length > 0
}

// ------------------------------------------------------------ Neon Auth
async function auth(req, res, route, url) {
  const body = req.method === 'POST' ? await readBody(req) : {}
  if (req.method === 'POST' && !trusted(req.headers.origin)) return fail(res, 403, 'INVALID_ORIGIN', 'Invalid origin')
  const email = String(body.email || '').trim().toLowerCase()
  switch (`${req.method} ${route}`) {
    case 'POST /sign-up/email': {
      if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return fail(res, 400, 'INVALID_EMAIL', 'Invalid email')
      if (String(body.password || '').length < 8) return fail(res, 400, 'PASSWORD_TOO_SHORT', 'Password too short')
      if (await userBy('email', email)) return fail(res, 422, 'USER_ALREADY_EXISTS', 'User already exists. Use another email.')
      const id = crypto.randomBytes(12).toString('base64url')
      const salt = crypto.randomBytes(8).toString('hex')
      await db.sql(`insert into neon_auth."user" (id, name, email) values ($1, $2, $3)`, [id, String(body.name || email.split('@')[0]).slice(0, 60), email])
      await db.sql(`insert into neon_auth.dev_password (user_id, salt, hash) values ($1, $2, $3)`, [id, salt, hashPw(body.password, salt)])
      await mail(email, 'email-verification')
      return send(res, 200, { token: null, user: userJson(await userBy('id', id)) })
    }
    case 'POST /sign-in/email': {
      const u = await userBy('email', email)
      const pw = u && (await db.sql(`select salt, hash from neon_auth.dev_password where user_id = $1`, [u.id])).rows[0]
      if (!pw || hashPw(body.password, pw.salt) !== pw.hash) return fail(res, 401, 'INVALID_EMAIL_OR_PASSWORD', 'Invalid email or password')
      if (!u.emailVerified) { await mail(email, 'email-verification'); return fail(res, 403, 'EMAIL_NOT_VERIFIED', 'Email not verified') }
      const tok = await newSession(u.id)
      return send(res, 200, { redirect: false, token: tok, user: userJson(u) }, { 'Set-Cookie': setCookie(tok) })
    }
    case 'POST /email-otp/send-verification-otp': {
      if (await userBy('email', email)) await mail(email, body.type || 'email-verification')
      return send(res, 200, { success: true })
    }
    case 'POST /email-otp/verify-email': {
      const u = await userBy('email', email)
      if (!u || !(await useCode(email, 'email-verification', body.otp))) return fail(res, 400, 'INVALID_OTP', 'Invalid OTP')
      await db.sql(`update neon_auth."user" set "emailVerified" = true where id = $1`, [u.id])
      const tok = await newSession(u.id)
      return send(res, 200, { status: true, token: tok, user: userJson(await userBy('id', u.id)) }, { 'Set-Cookie': setCookie(tok) })
    }
    case 'POST /email-otp/reset-password': {
      const u = await userBy('email', email)
      if (!u || !(await useCode(email, 'forget-password', body.otp))) return fail(res, 400, 'INVALID_OTP', 'Invalid OTP')
      if (String(body.password || '').length < 8) return fail(res, 400, 'PASSWORD_TOO_SHORT', 'Password too short')
      const salt = crypto.randomBytes(8).toString('hex')
      await db.sql(`insert into neon_auth.dev_password (user_id, salt, hash) values ($1, $2, $3)
                    on conflict (user_id) do update set salt = excluded.salt, hash = excluded.hash`, [u.id, salt, hashPw(body.password, salt)])
      await db.sql(`update neon_auth."user" set "emailVerified" = true where id = $1`, [u.id])
      return send(res, 200, { success: true })
    }
    case 'GET /get-session': {
      let tok = cookieOf(req), headers = {}
      const v = url.searchParams.get('neon_auth_session_verifier')
      if (v) {
        const r = await db.sql(`delete from neon_auth.dev_verifier where verifier = $1 and expires_at > now() returning token`, [v])
        if (!r.rows[0]) return send(res, 200, null)
        tok = r.rows[0].token
        headers['Set-Cookie'] = setCookie(tok)
      }
      const s = await sessionOf(tok)
      if (!s) return send(res, 200, null)
      headers['set-auth-jwt'] = jwt({ sub: s.user.id, role: 'authenticated', email: s.user.email })
      return send(res, 200, s, headers)
    }
    case 'GET /token/anonymous': {
      const t = jwt({ role: 'anonymous' })
      return send(res, 200, { token: t, expires_at: readJwt(t).exp })
    }
    case 'POST /sign-in/social': {
      if (body.provider !== 'google') return fail(res, 400, 'PROVIDER_NOT_FOUND', 'Provider not found')
      if (!trustedUrl(body.callbackURL)) return fail(res, 403, 'INVALID_CALLBACKURL', 'Invalid callbackURL')
      const state = crypto.randomBytes(16).toString('base64url')
      STATES.set(state, body.callbackURL)
      const host = `http://${req.headers.host}`
      return send(res, 200, { url: `${host}/dev/google?state=${state}`, redirect: !body.disableRedirect })
    }
    case 'POST /sign-out': {
      const tok = cookieOf(req)
      if (tok) await db.sql(`delete from neon_auth.dev_session where token = $1`, [tok])
      return send(res, 200, { success: true }, { 'Set-Cookie': setCookie('') })
    }
    case 'POST /delete-user': {
      const s = await sessionOf(cookieOf(req))
      if (!s) return fail(res, 401, 'UNAUTHORIZED', 'Unauthorized')
      await db.sql(`delete from neon_auth.dev_session where user_id = $1`, [s.user.id])
      await db.sql(`delete from neon_auth.dev_password where user_id = $1`, [s.user.id])
      await db.sql(`delete from neon_auth."user" where id = $1`, [s.user.id])
      return send(res, 200, { success: true, message: 'User deleted' }, { 'Set-Cookie': setCookie('') })
    }
  }
  return fail(res, 404, 'NOT_FOUND', 'Not found')
}

// ------------------------------------------------------------ the pretend Google
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))
async function google(req, res, url) {
  if (req.method === 'GET') {
    const state = url.searchParams.get('state') || ''
    if (!STATES.has(state)) { res.writeHead(400, { 'Content-Type': 'text/plain' }); return res.end('This sign-in has expired.') }
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' })
    return res.end(`<!doctype html><meta charset="utf-8"><title>Sign in - Google (pretend)</title>
<body style="font:15px system-ui;max-width:360px;margin:60px auto">
<h2>Google (pretend)</h2><p>The community's stand-in on this machine. Who are you?</p>
<form method="post" action="/dev/google"><input type="hidden" name="state" value="${esc(state)}">
<p><input name="email" placeholder="email" value="player@gmail.com" style="width:100%"></p>
<p><input name="name" placeholder="name" value="Player One" style="width:100%"></p>
<p><button id="go">Continue</button></p></form></body>`)
  }
  const body = await readBody(req)
  const back = STATES.get(body.state)
  STATES.delete(body.state)
  const email = String(body.email || '').trim().toLowerCase()
  if (!back || !email) { res.writeHead(400, { 'Content-Type': 'text/plain' }); return res.end('This sign-in has expired.') }
  let u = await userBy('email', email)
  if (!u) {
    const id = crypto.randomBytes(12).toString('base64url')
    await db.sql(`insert into neon_auth."user" (id, name, email, "emailVerified", image) values ($1, $2, $3, true, null)`,
      [id, String(body.name || email.split('@')[0]).slice(0, 60), email])
    u = await userBy('id', id)
  }
  const tok = await newSession(u.id)
  const verifier = crypto.randomBytes(24).toString('base64url')
  await db.sql(`insert into neon_auth.dev_verifier (verifier, token, expires_at) values ($1, $2, now() + interval '5 minutes')`, [verifier, tok])
  const to = new URL(back)
  to.searchParams.set('neon_auth_session_verifier', verifier)
  res.writeHead(302, { Location: to.toString() })
  res.end()
}

// ------------------------------------------------------------ the Data API
async function rpc(req, res, fn) {
  const m = /^Bearer\s+(.+)$/i.exec(req.headers.authorization || '')
  const claims = m ? readJwt(m[1]) : null
  if (!claims) return send(res, 401, { code: 'PGRST301', message: 'No suitable key or wrong key type' })
  if (claims.expired) return send(res, 401, { code: 'PGRST303', message: 'JWT expired' })
  const body = await readBody(req)
  try {
    const out = await db.call(fn, body.p ?? {}, { user: claims.role === 'authenticated' ? claims.sub : null })
    return send(res, 200, out)
  } catch (e) {
    return send(res, e.status || 500, e.body || { code: 'XX000', message: e.message })
  }
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`)
  const p = url.pathname
  try {
    let m
    if (req.method === 'POST' && (m = /^\/neondb\/rest\/v1\/rpc\/([a-z_]+)$/.exec(p))) return await rpc(req, res, m[1])
    if ((m = /^\/neondb\/auth(\/.*)$/.exec(p))) return await auth(req, res, m[1], url)
    if (p === '/dev/google') return await google(req, res, url)
    if (p === '/dev/mail') return send(res, 200, MAIL.get(String(url.searchParams.get('to') || '').toLowerCase()) || null)
    if (p === '/dev/sql' && req.method === 'POST' && TOOLS) {
      const b = await readBody(req)
      return send(res, 200, (await db.sql(b.sql, b.params || [])).rows)
    }
    return fail(res, 404, 'NOT_FOUND', 'Not found')
  } catch (e) {
    console.error(e)
    return fail(res, 500, 'INTERNAL', e.message)
  }
})
server.listen(PORT, '127.0.0.1', () => {
  console.log(`COMMUNITY_DEV_READY port=${server.address().port}`)
  console.log(`  data API  http://127.0.0.1:${server.address().port}/neondb/rest/v1`)
  console.log(`  auth      http://127.0.0.1:${server.address().port}/neondb/auth`)
  console.log(`  kept in   ${DIR || 'memory'}`)
})
