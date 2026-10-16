// The community's rules, checked on the database itself (in memory):
//   cd cloud && npm install && npm test
import assert from 'node:assert/strict'
import { openDb } from './db.mjs'

const db = await openDb()
let passed = 0
async function t(name, fn) {
  try { await fn(); passed++; console.log('  ok  ' + name) } catch (e) { console.log('FAIL  ' + name + '\n      ' + (e.stack || e)); process.exitCode = 1 }
}
const as = user => (fn, p) => db.call(fn, p, { user })
const guest = as(null), u1 = as('u1'), u2 = as('u2'), u3 = as('u3')
async function fails(promise, re) {
  try { await promise } catch (e) { if (re && !re.test(e.message)) throw new Error('wrong error: ' + e.message); return e }
  throw new Error('did not fail')
}
const b64 = buf => Buffer.from(buf).toString('base64')
const WEBP = b64(Buffer.concat([Buffer.from('RIFF\x10\x00\x00\x00WEBPVP8 ', 'latin1'), Buffer.alloc(40, 7)]))
const GZ = n => b64(Buffer.concat([Buffer.from([0x1f, 0x8b, 8, 0]), Buffer.alloc(50, n)]))
const SHA = c => c.repeat(64)
async function media(who, kind, mime = 'image/webp', data = WEBP) {
  return (await who('upload_media', { kind, mime, data })).id
}
async function mission(who, name, extra = {}) {
  const p = {
    name, summary: 'A raid on the radar', description: 'Get in quietly.\nGet out.', level: 3, kind: 'copy',
    difficulty: 'hard', tags: ['stealth'], play_minutes: 20,
    objectives: [{ kind: 'reach', text: 'Reach the radar tower' }, { kind: 'destroy', text: 'Blow up the generator' }],
    facts: { guards: 12, cameras: 2, weather: 'snow', bogus: 'x' },
    cover: await media(who, 'cover'), thumb: await media(who, 'thumb'),
    plan: await media(who, 'plan', 'application/gzip', GZ(1)), plan_sha256: SHA('a'), format_version: 2,
    studio_version: '1.1.0', ...extra,
  }
  return who('publish_mission', p)
}

console.log('the community database')
let M1, M2
await t('a guest is no one, and sees an empty community', async () => {
  assert.deepEqual(await guest('me'), { signed_in: false, profile: null })
  // Neon's anonymous token says sub "anonymous": still no one
  assert.deepEqual(await db.call('me', {}, { user: 'anonymous', role: 'anonymous' }), { signed_in: false, profile: null })
  assert.deepEqual((await guest('list_missions', {})).items, [])
})
await t('a guest cannot write at all (no grant)', async () => {
  const e = await fails(guest('publish_mission', {}))
  assert.equal(e.status, 401)
})
await t('the tables are out of the API\'s reach', async () => {
  await db.sql('set role anonymous')
  try { await fails(db.sql('select * from community.missions'), /permission denied/) } finally { await db.sql('reset role') }
  await db.sql('set role authenticated')
  try { await fails(db.sql('select * from community.media'), /permission denied/) } finally { await db.sql('reset role') }
})
await t('signed in without a profile: suggested from the account, asked to choose a name', async () => {
  await db.sql(`insert into neon_auth."user" (id, name, email, image) values ('u1', 'Nouman', 'n@x.com', 'https://g/p.png')`)
  const me = await u1('me')
  assert.equal(me.signed_in, true); assert.equal(me.profile, null); assert.equal(me.suggest.name, 'Nouman')
  await fails(u1('upload_media', { kind: 'cover', mime: 'image/webp', data: WEBP }), /Choose your name/)
})
await t('handles: the shape, kept names, taken however written', async () => {
  assert.equal((await u1('handle_free', { handle: 'ab' })).free, false)
  assert.equal((await u1('handle_free', { handle: 'Admin' })).free, false)
  await u1('save_profile', { handle: 'Nouman_A', name: 'Nouman', bio: 'Maker', links: ['https://nomihsa965.me'] })
  assert.equal((await u2('handle_free', { handle: 'nouman_a' })).free, false)
  await fails(u2('save_profile', { handle: 'NOUMAN_A', name: 'X' }), /taken/)
  await fails(u2('save_profile', { handle: 'second', name: 'Two', links: ['http://no'] }), /https/)
  await u2('save_profile', { handle: 'second', name: 'Two' })
  await u3('save_profile', { handle: 'third', name: 'Three' })
  const me = await u1('me')
  assert.equal(me.profile.handle, 'Nouman_A'); assert.deepEqual(me.profile.links, ['https://nomihsa965.me'])
})
await t('uploads: what it says it is, and not too big', async () => {
  await fails(u1('upload_media', { kind: 'cover', mime: 'image/webp', data: b64('not a picture') }), /not what it says/)
  await fails(u1('upload_media', { kind: 'thumb', mime: 'image/webp', data: b64(Buffer.concat([Buffer.from('RIFF\0\0\0\0WEBP', 'latin1'), Buffer.alloc(100000)])) }), /too big/)
  await fails(u1('upload_media', { kind: 'plan', mime: 'image/png', data: WEBP }), /does not go there/)
  assert.ok(await media(u1, 'avatar'))
})
await t('sharing needs an objective, and a name of its own', async () => {
  await fails(mission(u1, 'Radar Dome Raid', { objectives: [] }), /at least one objective/)
  M1 = await mission(u1, 'Radar Dome Raid')
  assert.equal(M1.version, 1)
  await fails(mission(u2, 'radar  dome-RAID!'), /already a mission called/)
  assert.equal((await guest('name_free', { name: 'RADAR DOME RAID' })).free, false)
  assert.equal((await guest('name_free', { name: 'Radar Dome Raid', except: M1.id })).free, true)
})
await t('a guest browses, searches (words, objectives, typos) and opens it', async () => {
  const all = await guest('list_missions', {})
  assert.equal(all.items.length, 1); assert.equal(all.items[0].author.handle, 'Nouman_A')
  assert.equal(all.items[0].objectives, 2); assert.deepEqual(all.items[0].facts, { guards: 12, cameras: 2, weather: 'snow' })
  assert.equal((await guest('list_missions', { q: 'generator' })).items.length, 1)
  assert.equal((await guest('list_missions', { q: 'radr dome' })).items.length, 1)
  assert.equal((await guest('list_missions', { q: 'radr' })).items.length, 1)
  assert.equal((await guest('list_missions', { q: 'helicopter' })).items.length, 0)
  assert.equal((await guest('list_missions', { level: 4 })).items.length, 0)
  assert.equal((await guest('list_missions', { tag: 'stealth', difficulty: 'hard' })).items.length, 1)
  assert.deepEqual(await guest('community_stats', {}), { missions: 1, people: 3, pulls: 0, comments: 0 })
  const m = await guest('get_mission', { id: M1.id })
  assert.equal(m.objectives[1].text, 'Blow up the generator'); assert.equal(m.my_vote, null); assert.equal(m.mine, false)
  assert.equal(m.versions.length, 1)
  const plan = await guest('get_plan', { id: M1.id })
  assert.equal(plan.version, 1); assert.equal(Buffer.from(plan.data, 'base64')[0], 0x1f)
})
await t('votes: not your own, one each, changed or taken back; not as a guest', async () => {
  await fails(u1('set_vote', { id: M1.id, value: 1 }), /your own/)
  await fails(guest('set_vote', { id: M1.id, value: 1 }))
  assert.equal((await u2('set_vote', { id: M1.id, value: 1 })).up, 1)
  let v = await u2('set_vote', { id: M1.id, value: -1 }); assert.equal(v.up, 0); assert.equal(v.down, 1)
  v = await u2('set_vote', { id: M1.id, value: 0 }); assert.equal(v.score, 0); assert.equal(v.my_vote, null)
  await u2('set_vote', { id: M1.id, value: 1 }); await u3('set_vote', { id: M1.id, value: 1 })
  assert.equal((await u2('get_mission', { id: M1.id })).my_vote, 1)
  assert.equal((await guest('list_missions', { sort: 'week' })).items[0].score, 2)
})
await t('pulls: signed in, counted once a person', async () => {
  await fails(guest('record_pull', { id: M1.id }))
  assert.equal((await u2('record_pull', { id: M1.id, version: 1 })).pulls, 1)
  assert.equal((await u2('record_pull', { id: M1.id, version: 1 })).pulls, 1)
  assert.equal((await u2('get_mission', { id: M1.id })).my_pull, 1)
})
await t('a remix: changed, carrying the line; unchanged refused', async () => {
  await fails(mission(u2, 'Radar Dome Raid II', { parent: { id: M1.id, version: 1 }, plan_sha256: SHA('a') }), /Nothing has changed/)
  M2 = await mission(u2, 'Radar Dome Raid II', { parent: { id: M1.id, version: 1 }, plan_sha256: SHA('b') })
  const m = await guest('get_mission', { id: M2.id })
  assert.equal(m.lineage.length, 1); assert.equal(m.lineage[0].author.handle, 'Nouman_A'); assert.equal(m.remix_of.name, 'Radar Dome Raid')
  assert.equal((await guest('remixes', { id: M1.id })).items.length, 1)
  assert.equal((await guest('list_missions', { remixes: 'only' })).items.length, 1)
})
await t('an author can forbid remixes', async () => {
  const own = await mission(u3, 'Locked Down', { allow_remix: false })
  await fails(mission(u2, 'Locked Down Mine', { parent: { id: own.id }, plan_sha256: SHA('c') }), /does not allow/)
  await u3('delete_mission', { id: own.id })
})
await t('a new version: yours, changed, with notes', async () => {
  const base = { id: M1.id, name: 'Radar Dome Raid', summary: 'A raid on the radar, again', level: 3, kind: 'copy',
    objectives: [{ kind: 'reach', text: 'Reach the radar tower' }] }
  const next = async (who, extra) => who('publish_version', { ...base, cover: await media(who, 'cover'), thumb: await media(who, 'thumb'),
    plan: await media(who, 'plan', 'application/gzip', GZ(2)), plan_sha256: SHA('d'), format_version: 2, notes: 'Fewer guards', ...extra })
  const oldCover = (await guest('get_mission', { id: M1.id })).cover
  await fails(next(u2), /not yours/)
  await fails(next(u1, { plan_sha256: SHA('a') }), /not changed since version 1/)
  await fails(next(u1, { notes: '' }), /what is new/)
  await fails(next(u1, { level: 4 }), /keeps the base level/)
  assert.equal((await next(u1)).version, 2)
  const m = await guest('get_mission', { id: M1.id })
  assert.equal(m.version, 2); assert.equal(m.versions[0].notes, 'Fewer guards'); assert.equal(m.objectives.length, 1)
  assert.equal((await guest('get_plan', { id: M1.id, version: 1 })).version, 1)
  // the old cover went; the plans of both versions stay
  assert.equal((await db.sql(`select count(*)::int n from community.media where id = $1`, [oldCover])).rows[0].n, 0)
  assert.equal((await db.sql(`select count(*)::int n from community.versions where mission = $1`, [M1.id])).rows[0].n, 2)
})
await t('details without a version; a name must still be free', async () => {
  await fails(u1('update_details', { id: M1.id, name: 'Radar Dome Raid II' }), /already a mission/)
  const m = await u1('update_details', { id: M1.id, summary: 'Shorter', tags: ['stealth', 'timed'] })
  assert.equal(m.summary, 'Shorter'); assert.equal(m.version, 2)
  await fails(u1('update_details', { id: M1.id, tags: ['nonsense'] }), /Unknown tag/)
})
let C1
await t('comments: signed in, replies one deep, removed by the mission\'s author', async () => {
  await fails(guest('add_comment', { id: M1.id, body: 'hi' }))
  C1 = await u2('add_comment', { id: M1.id, body: 'Great mission!' })
  const rep = await u1('add_comment', { id: M1.id, parent: C1.id, body: 'Thanks' })
  await fails(u3('add_comment', { id: M1.id, parent: rep.id, body: 'deeper' }), /not there/)
  let list = await guest('list_comments', { id: M1.id })
  assert.equal(list.items.length, 1); assert.equal(list.items[0].replies.length, 1); assert.equal(list.items[0].can_remove, false)
  assert.equal((await u1('list_comments', { id: M1.id })).items[0].can_remove, true)
  await fails(u3('delete_comment', { id: C1.id }), /not yours/)
  await u1('delete_comment', { id: C1.id })
  list = await guest('list_comments', { id: M1.id })
  assert.equal(list.items[0].removed, true); assert.equal(list.items[0].body, '')
  assert.equal((await guest('get_mission', { id: M1.id })).comments, 1)
  const e = await u1('edit_comment', { id: rep.id, body: 'Thanks a lot' }); assert.ok(e.edited_at)
})
await t('unlisted: off the lists, still there by its link and on its author\'s own page', async () => {
  await u2('set_status', { id: M2.id, status: 'unlisted' })
  assert.equal((await guest('list_missions', {})).items.length, 1)
  assert.equal((await guest('get_mission', { id: M2.id })).status, 'unlisted')
  assert.equal((await guest('get_profile', { handle: 'second' })).missions.items.length, 0)
  assert.equal((await u2('get_profile', { handle: 'SECOND' })).missions.items.length, 1)
  await fails(u2('set_status', { id: M2.id, status: 'hidden' }), /Unknown status/)
  await u2('set_status', { id: M2.id, status: 'published' })
})
await t('reports and moderators', async () => {
  await u3('report', { type: 'mission', target: M2.id, reason: 'stolen', note: 'copied' })
  await fails(u3('report', { type: 'mission', target: M2.id, reason: 'boring' }), /what is wrong/)
  await fails(u1('mod_reports', {}), /Only moderators/)
  await db.sql(`update community.profiles set role = 'admin' where id = 'u1'`)
  const reps = await u1('mod_reports', {})
  assert.equal(reps.items.length, 1); assert.equal(reps.items[0].what.name, 'Radar Dome Raid II')
  await u1('mod_act', { report: reps.items[0].id, action: 'hide' })
  await fails(guest('get_mission', { id: M2.id }), /not in the community/)
  assert.equal((await u2('get_mission', { id: M2.id })).status, 'hidden')
  await fails(u2('set_status', { id: M2.id, status: 'published' }), /moderator has hidden/)
  await u1('mod_act', { target: M2.id, action: 'unhide' })
  await u1('set_role', { handle: 'third', role: 'mod' })
  assert.equal((await u3('mod_reports', { status: 'done' })).items.length, 1)
})
await t('a banned person cannot post', async () => {
  await u1('mod_act', { target: 'u3', action: 'ban' })
  await fails(u3('add_comment', { id: M1.id, body: 'hello' }), /can no longer post/)
  await u1('mod_act', { target: 'u3', action: 'unban' })
  assert.ok(await u3('add_comment', { id: M1.id, body: 'hello' }))
})
await t('the rate limits hold', async () => {
  for (let i = 0; i < 19; i++) await u3('report', { type: 'mission', target: M1.id, reason: 'other' })
  await fails(u3('report', { type: 'mission', target: M1.id, reason: 'other' }), /short time/)
})
await t('deleting a mission: its name free at once, its remix keeps the line', async () => {
  const before = (await db.sql(`select count(*)::int n from community.media`)).rows[0].n
  await fails(u2('delete_mission', { id: M1.id }), /not yours/)
  await u1('delete_mission', { id: M1.id })
  assert.equal((await guest('name_free', { name: 'Radar Dome Raid' })).free, true)
  const m = await guest('get_mission', { id: M2.id })
  assert.equal(m.parent, null); assert.equal(m.lineage[0].name, 'Radar Dome Raid'); assert.equal(m.remix_of.name, 'Radar Dome Raid')
  const after = (await db.sql(`select count(*)::int n from community.media`)).rows[0].n
  assert.ok(after < before)
  // shared again under the same name: a new mission, from the line it carries
  const again = await mission(u1, 'Radar Dome Raid', { parent: { id: M1.id }, lineage: [{ id: M1.id, version: 2, name: 'Old one', author: { handle: 'x' } }] })
  assert.equal((await guest('get_mission', { id: again.id })).lineage[0].name, 'Old one')
})
await t('deleting your data: your votes, pulls and comments come off the counts', async () => {
  const m = (await guest('list_missions', { q: 'Radar Dome Raid' })).items.find(x => x.author.handle === 'Nouman_A')
  await u2('set_vote', { id: m.id, value: 1 }); await u2('record_pull', { id: m.id }); await u2('add_comment', { id: m.id, body: 'x' })
  let g = await guest('get_mission', { id: m.id }); assert.equal(g.up, 1); assert.equal(g.pulls, 1); assert.equal(g.comments, 1)
  await u2('delete_my_data', {})
  g = await guest('get_mission', { id: m.id }); assert.equal(g.up, 0); assert.equal(g.pulls, 0); assert.equal(g.comments, 0)
  assert.equal((await u2('me')).profile, null)
  await fails(guest('get_mission', { id: M2.id }), /not in the community/)
  assert.equal((await db.sql(`select count(*)::int n from community.media where owner = 'u2'`)).rows[0].n, 0)
})
await t('paging: 24 a page, then the rest', async () => {
  for (let i = 0; i < 26; i++) await db.sql(
    `insert into community.missions (author, name, name_key, summary, base_level, base_kind, objectives, cover, thumb)
     select 'u3', 'Bulk ' || $1, 'bulk ' || $1, 's', 1, 'copy', '[{"kind":"x","text":"y"}]', id, id
       from community.media where owner = 'u1' and kind = 'cover' limit 1`, [String(i)])
  const a = await guest('list_missions', { q: 'bulk', sort: 'new' })
  assert.equal(a.items.length, 24); assert.equal(a.next, '24')
  const b = await guest('list_missions', { q: 'bulk', sort: 'new', cursor: a.next })
  assert.equal(b.items.length, 2); assert.equal(b.next, null)
})

console.log(`${passed} passed${process.exitCode ? ', some FAILED' : ''}`)
await db.close()
