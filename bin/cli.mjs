#!/usr/bin/env node
// Installer for the img2threejs skill.
//
// One canonical checkout, one symlink per agent host. The shebang above is load-bearing: npm's bin
// shim executes a shebang-less file through the shell.
//
// Every subprocess call goes through execFileSync with an argv array -- no shell, so no path or ref
// can be interpolated into a command line.

import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import readline from 'node:readline'
import { fileURLToPath } from 'node:url'

const EXIT = { OK: 0, FAIL: 1, REFUSED: 2, NEEDS_INPUT: 3 }
const MIN_NODE = 18
const DEFAULT_REPO_URL = 'https://github.com/img2threejs/img2threejs.git'
const LINK_NAME = 'img2threejs'
const LOCK_STALE_MS = 60 * 60 * 1000
const MAX_RETRIES = 3
const REQUIRED_PATHS = ['SKILL.md', 'forge', 'grimoire']

// Resolution goes through os.homedir(), which honours $HOME; os.userInfo().homedir does not, and a
// test that injects HOME against it would operate on the developer's real skills directories.
const home = () => os.homedir()
const xdgConfig = () => process.env.XDG_CONFIG_HOME || path.join(home(), '.config')

const HOSTS = {
  claude: {
    label: 'Claude Code',
    configRoot: () => path.join(home(), '.claude'),
    global: () => path.join(home(), '.claude', 'skills'),
    local: path.join('.claude', 'skills'),
  },
  codex: {
    label: 'Codex',
    configRoot: () => path.join(home(), '.codex'),
    global: () => path.join(home(), '.codex', 'skills'),
    local: path.join('.codex', 'skills'),
  },
  opencode: {
    label: 'OpenCode',
    configRoot: () => path.join(xdgConfig(), 'opencode'),
    global: () => path.join(xdgConfig(), 'opencode', 'skills'),
    local: path.join('.opencode', 'skills'),
  },
}

let flagAllowFork = false

class CliError extends Error {
  constructor(code, message, detail) {
    super(message)
    this.code = code
    this.detail = detail
  }
}

// ---------------------------------------------------------------- layout

function stateHome() {
  const raw = process.env.IMG2THREEJS_HOME
  if (!raw) return path.join(home(), '.img2threejs')
  if (raw.startsWith('~')) {
    throw new CliError(EXIT.REFUSED, 'IMG2THREEJS_HOME must not begin with "~" -- the shell expands it, the CLI does not', raw)
  }
  if (!path.isAbsolute(raw)) throw new CliError(EXIT.REFUSED, 'IMG2THREEJS_HOME must be an absolute path', raw)
  return raw
}

// IMG2THREEJS_HOME names the PARENT. The checkout sits at repo/ so backups, the receipt and the lock
// have a home beside it, and so a bare ~/.img2threejs cannot collide with the in-project state
// directory that forge/state.py writes.
const repoDir = () => path.join(stateHome(), 'repo')
const backupsDir = () => path.join(stateHome(), 'backups')
const receiptsPath = () => path.join(stateHome(), 'receipts.json')
const lockPath = () => path.join(stateHome(), '.lock')
const repoUrl = () => process.env.IMG2THREEJS_REPO_URL || DEFAULT_REPO_URL

// ---------------------------------------------------------------- git

function git(args, cwd) {
  try {
    return execFileSync('git', args, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim()
  } catch (err) {
    if (err.code === 'ENOENT') {
      throw new CliError(EXIT.FAIL, 'git is not on PATH; install git, or point --dir at an existing checkout')
    }
    throw new Error('git ' + args.join(' ') + ' failed: ' + String(err.stderr || '').trim())
  }
}

function gitOk(args, cwd) {
  try {
    git(args, cwd)
    return true
  } catch (err) {
    if (err instanceof CliError) throw err
    return false
  }
}

const isGitRepo = (dir) => fs.existsSync(dir) && gitOk(['rev-parse', '--git-dir'], dir)
const normaliseRemote = (url) => url.trim().replace(/\.git$/, '').replace(/\/+$/, '').toLowerCase()

function originMatches(dir) {
  try {
    return normaliseRemote(git(['remote', 'get-url', 'origin'], dir)) === normaliseRemote(repoUrl())
  } catch {
    return false
  }
}

// Untracked files never block: two of the three checkouts on the author's machine are "dirty" only
// because of an artifact directory belonging to an unrelated tool.
const trackedDirt = (dir) =>
  git(['status', '--porcelain', '--untracked-files=no'], dir).split('\n').map((l) => l.trim()).filter(Boolean)

function unpushedCommits(dir) {
  const onBranches = git(['log', '--branches', '--not', '--remotes', '--oneline'], dir).split('\n').filter(Boolean)
  if (onBranches.length) return onBranches
  // A detached HEAD belongs to no branch, so the check above cannot see it.
  if (git(['rev-parse', '--abbrev-ref', 'HEAD'], dir) === 'HEAD' && !git(['branch', '-r', '--contains', 'HEAD'], dir)) {
    return [git(['log', '-1', '--oneline'], dir)]
  }
  return []
}

function midOperation(dir) {
  const gitDir = path.resolve(dir, git(['rev-parse', '--git-dir'], dir))
  for (const marker of ['rebase-merge', 'rebase-apply', 'MERGE_HEAD', 'CHERRY_PICK_HEAD']) {
    if (fs.existsSync(path.join(gitDir, marker))) return marker
  }
  return null
}

function describeRef(dir) {
  const branch = git(['rev-parse', '--abbrev-ref', 'HEAD'], dir)
  const short = git(['rev-parse', '--short', 'HEAD'], dir)
  return branch === 'HEAD' ? 'detached@' + short : branch + '@' + short
}

// ---------------------------------------------------------------- channels

const STABLE_TAG = /^v(\d+)\.(\d+)\.(\d+)$/
const BETA_TAG = /^v(\d+)\.(\d+)\.(\d+)-beta\.(\d+)$/

const remoteTags = () =>
  git(['ls-remote', '--tags', repoUrl()])
    .split('\n')
    .map((line) => line.split('refs/tags/')[1])
    .filter((t) => t && !t.endsWith('^{}'))

function resolveChannel(channel, explicitRef) {
  if (explicitRef) return { ref: explicitRef, skipped: [] }
  if (channel === 'main') return { ref: 'HEAD', skipped: [] }

  const pattern = channel === 'beta' ? BETA_TAG : STABLE_TAG
  const matching = []
  const skipped = []
  for (const tag of remoteTags()) {
    const m = pattern.exec(tag)
    if (m) matching.push({ tag, key: m.slice(1).map(Number) })
    else skipped.push(tag)
  }
  if (!matching.length) {
    throw new CliError(EXIT.FAIL, 'no tag matches the "' + channel + '" channel', 'rejected: ' + (skipped.join(', ') || '(no tags)'))
  }
  matching.sort((a, b) => {
    for (let i = 0; i < a.key.length; i += 1) if (a.key[i] !== b.key[i]) return b.key[i] - a.key[i]
    return 0
  })
  return { ref: matching[0].tag, skipped }
}

// ---------------------------------------------------------------- checkout

function skillVersion(dir) {
  try {
    const m = /^version: (\d+\.\d+\.\d+(?:-beta\.\d+)?)$/m.exec(fs.readFileSync(path.join(dir, 'SKILL.md'), 'utf8'))
    return m ? m[1] : null
  } catch {
    return null
  }
}

function verifyCheckout(dir) {
  const missing = REQUIRED_PATHS.filter((p) => !fs.existsSync(path.join(dir, p)))
  if (missing.length) {
    throw new CliError(EXIT.FAIL, 'checkout is incomplete; no host was linked', 'missing: ' + missing.join(', '))
  }
  const version = skillVersion(dir)
  if (!version) throw new CliError(EXIT.FAIL, 'checkout SKILL.md has no parseable version field; no host was linked')
  return version
}

function assertUsable(dir) {
  if (!isGitRepo(dir)) {
    throw new CliError(EXIT.REFUSED, dir + ' exists but is not a git checkout; move it aside or set IMG2THREEJS_HOME')
  }
  if (!originMatches(dir) && !flagAllowFork) {
    throw new CliError(EXIT.REFUSED, dir + ' points at a different remote', 'origin: ' + git(['remote', 'get-url', 'origin'], dir) + ' -- pass --allow-fork to accept it')
  }
  const op = midOperation(dir)
  if (op) throw new CliError(EXIT.REFUSED, dir + ' is mid-' + op + '; finish or abort it first')
  const dirt = trackedDirt(dir)
  if (dirt.length) {
    throw new CliError(EXIT.REFUSED, dir + ' has modified tracked files; nothing was stashed or discarded', dirt.join('\n'))
  }
}

function ensureCheckout(ref, steps) {
  const dir = repoDir()
  const target = ref === 'HEAD' ? 'origin/HEAD' : ref
  if (fs.existsSync(dir)) {
    assertUsable(dir)
    const before = skillVersion(dir)
    git(['fetch', '--tags', '--force', 'origin'], dir)
    // Never `git pull`: a resolved tag leaves a detached HEAD, where pull fails outright.
    git(['checkout', '--detach', target], dir)
    steps.push({ step: 'update', from: before, to: skillVersion(dir), ref })
  } else {
    fs.mkdirSync(path.dirname(dir), { recursive: true })
    // --filter=blob:none, never --depth 1: a shallow clone cannot resolve tags.
    git(['clone', '--filter=blob:none', repoUrl(), dir])
    git(['checkout', '--detach', target], dir)
    steps.push({ step: 'clone', to: skillVersion(dir), ref })
  }
  return dir
}

// ---------------------------------------------------------------- targets

function samePath(a, b) {
  const norm = (p) => {
    let r
    try {
      r = fs.realpathSync(p)
    } catch {
      r = path.resolve(p)
    }
    return process.platform === 'darwin' || process.platform === 'win32' ? r.toLowerCase() : r
  }
  return norm(a) === norm(b)
}

// lstat, never stat: stat follows symlinks, so a symlink-to-directory would be misclassified as a
// real directory and wrongly routed to the refuse-or---force path.
function classify(target, canonical) {
  let st
  try {
    st = fs.lstatSync(target)
  } catch (err) {
    if (err.code === 'ENOENT') return { state: 'absent' }
    throw err
  }
  if (st.isSymbolicLink()) {
    const raw = fs.readlinkSync(target)
    if (!fs.existsSync(target)) return { state: 'dangling', raw }
    return samePath(target, canonical)
      ? { state: 'linked', raw }
      : { state: 'divergent', raw, real: fs.realpathSync(target) }
  }
  if (st.isDirectory()) return { state: 'directory' }
  return { state: 'file' }
}

function adoptability(dir) {
  if (!isGitRepo(dir)) return { adoptable: false, why: 'not a git checkout' }
  if (!originMatches(dir)) return { adoptable: false, why: 'different remote (' + git(['remote', 'get-url', 'origin'], dir) + ')' }
  const op = midOperation(dir)
  if (op) return { adoptable: false, why: 'mid-' + op }
  const dirt = trackedDirt(dir)
  if (dirt.length) return { adoptable: false, why: dirt.length + ' modified tracked file(s)' }
  const unpushed = unpushedCommits(dir)
  if (unpushed.length) return { adoptable: false, why: unpushed.length + ' unpushed commit(s)' }
  return { adoptable: true, ref: describeRef(dir) }
}

// The seam exists so the failure path is verifiable without the target platform.
let linkImpl = (target, canonical) => {
  try {
    fs.symlinkSync(canonical, target, 'junction')
  } catch (err) {
    if (err.code === 'EPERM' || err.code === 'ENOSYS') {
      // Never degrade to copying: a copy is the drift this installer exists to end.
      throw new CliError(EXIT.FAIL, 'cannot create a link at ' + target, err.code + ': on Windows this needs Developer Mode or an elevated shell')
    }
    throw err
  }
}

if (process.env.IMG2THREEJS_FORCE_LINK_FAILURE === '1') {
  linkImpl = (target) => {
    throw new CliError(EXIT.FAIL, 'cannot create a link at ' + target, 'forced failure (IMG2THREEJS_FORCE_LINK_FAILURE)')
  }
}

function link(target, canonical) {
  fs.mkdirSync(path.dirname(target), { recursive: true })
  try {
    linkImpl(target, canonical)
  } catch (err) {
    // EEXIST is authoritative "the target appeared" -- re-classify and report rather than
    // unlink-then-symlink, which would race a concurrent writer into data loss.
    if (err.code === 'EEXIST') {
      const again = classify(target, canonical)
      if (again.state === 'linked') return 'already linked'
      throw new CliError(EXIT.REFUSED, target + ' appeared while linking (now: ' + again.state + ')')
    }
    throw err
  }
  return 'linked'
}

function backup(target, hostKey) {
  const stamp = new Date().toISOString().replace(/[:.]/g, '-')
  const dest = path.join(backupsDir(), hostKey + '-' + stamp)
  if (fs.existsSync(dest)) throw new CliError(EXIT.FAIL, 'backup destination already exists: ' + dest)
  fs.mkdirSync(backupsDir(), { recursive: true })
  fs.renameSync(target, dest)
  return dest
}

// ---------------------------------------------------------------- receipts

function readReceipts() {
  try {
    const parsed = JSON.parse(fs.readFileSync(receiptsPath(), 'utf8'))
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function writeReceipts(entries) {
  fs.mkdirSync(stateHome(), { recursive: true })
  fs.writeFileSync(receiptsPath(), JSON.stringify(entries, null, 2) + '\n')
}

function recordReceipt(entry) {
  const entries = readReceipts().filter((e) => e.target !== entry.target)
  entries.push(entry)
  writeReceipts(entries)
}

// ---------------------------------------------------------------- lock

let heldLock = null

function acquireLock() {
  const p = lockPath()
  fs.mkdirSync(stateHome(), { recursive: true })
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      const fd = fs.openSync(p, 'wx')
      fs.writeFileSync(fd, JSON.stringify({ pid: process.pid, hostname: os.hostname(), at: new Date().toISOString() }))
      fs.closeSync(fd)
      heldLock = p
      return
    } catch (err) {
      if (err.code !== 'EEXIST') throw err
      if (Date.now() - fs.statSync(p).mtimeMs < LOCK_STALE_MS) {
        let holder = '(unreadable)'
        try {
          const h = JSON.parse(fs.readFileSync(p, 'utf8'))
          holder = 'pid ' + h.pid + ' on ' + h.hostname + ' since ' + h.at
        } catch { /* keep the placeholder */ }
        throw new CliError(EXIT.FAIL, 'another img2threejs run holds the lock', holder)
      }
      fs.rmSync(p, { force: true })
    }
  }
}

function releaseLock() {
  if (heldLock) {
    fs.rmSync(heldLock, { force: true })
    heldLock = null
  }
}

// ---------------------------------------------------------------- prompts

function requireTty(what) {
  if (!process.stdin.isTTY) {
    throw new CliError(
      EXIT.NEEDS_INPUT,
      what + ' requires interactive input, but stdin is not a terminal',
      'pass hosts as arguments plus --yes, e.g. `install claude codex --yes`, or use --dir <path>',
    )
  }
}

// readline's answer callback never fires on EOF -- only 'close' does -- so a naive implementation
// falls through every prompt and exits 0 having installed nothing.
function ask(rl, prompt) {
  return new Promise((resolve) => {
    let settled = false
    const onClose = () => {
      if (!settled) {
        settled = true
        resolve(null)
      }
    }
    rl.once('close', onClose)
    rl.question(prompt, (answer) => {
      settled = true
      rl.removeListener('close', onClose)
      resolve(answer)
    })
  })
}

async function confirm(rl, prompt) {
  const answer = await ask(rl, prompt + ' [y/N] ')
  // EOF and every non-affirmative input mean no.
  return answer !== null && /^(y|yes)$/i.test(answer.trim())
}

// ---------------------------------------------------------------- selection

// One predicate, pinned: the host's config root exists. It is what decides whether --yes installs
// anything, so it must not be ambiguous.
const detectedHosts = () => Object.keys(HOSTS).filter((k) => fs.existsSync(HOSTS[k].configRoot()))

function projectRoot() {
  let dir = process.cwd()
  for (;;) {
    if (fs.existsSync(path.join(dir, '.git'))) return dir
    const up = path.dirname(dir)
    if (up === dir) return null
    dir = up
  }
}

const isIgnored = (root, relative) => gitOk(['check-ignore', '-q', '--', relative], root)

function validateDir(p, yes) {
  if (!p || !path.isAbsolute(p)) throw new CliError(EXIT.REFUSED, '--dir needs an absolute path', p || '(empty)')
  if (!fs.existsSync(p) || !fs.statSync(p).isDirectory()) {
    throw new CliError(EXIT.REFUSED, '--dir must name an existing directory', p)
  }
  if (!yes && !path.resolve(p).startsWith(path.resolve(home()) + path.sep)) {
    throw new CliError(EXIT.REFUSED, '--dir resolves outside your home directory: ' + p, 'pass --yes to accept it')
  }
  return p
}

function targetFor(hostKey, scope, dirOverride) {
  if (hostKey === '--dir') return path.join(dirOverride, LINK_NAME)
  const host = HOSTS[hostKey]
  if (scope === 'local') {
    const root = projectRoot()
    if (!root) {
      throw new CliError(EXIT.REFUSED, '--local needs a project: no .git directory in any parent of the current directory')
    }
    const relative = path.join(host.local, LINK_NAME)
    if (!isIgnored(root, relative)) {
      throw new CliError(
        EXIT.REFUSED,
        relative + ' is not ignored by this repository',
        "git stores the symlink's literal absolute target, so a committed link resolves on no other machine; add the path to .gitignore first",
      )
    }
    return path.join(root, relative)
  }
  return path.join(host.global(), LINK_NAME)
}

async function chooseHosts(rl, detected) {
  const keys = Object.keys(HOSTS)
  console.log('\nWhich AI tools should get the skill?\n')
  keys.forEach((k, i) => {
    const mark = detected.includes(k) ? 'detected' : 'not found'
    console.log('  ' + (i + 1) + ') ' + HOSTS[k].label.padEnd(12) + ' ' + HOSTS[k].global().replace(home(), '~').padEnd(36) + '[' + mark + ']')
  })
  // --dir belongs in the menu, not only in the flags: it is the answer to "and other agents", and a
  // flag-only escape hatch cannot be discovered from a menu that never mentions it.
  console.log('  ' + (keys.length + 1) + ') Another tool (enter a skills directory)\n')

  for (let attempt = 0; attempt < MAX_RETRIES; attempt += 1) {
    const fallback = detected.length ? detected.map((k) => keys.indexOf(k) + 1).join(',') : ''
    const answer = await ask(rl, 'Numbers, comma separated' + (fallback ? ' [' + fallback + ']' : '') + ': ')
    if (answer === null) throw new CliError(EXIT.FAIL, 'input ended before anything was installed')

    const raw = answer.trim() || fallback
    if (!raw) {
      console.log('  Nothing selected.')
      continue
    }
    const chosen = []
    let bad = null
    for (const pick of raw.split(',').map((s) => s.trim()).filter(Boolean)) {
      const n = Number(pick)
      if (!Number.isInteger(n) || n < 1 || n > keys.length + 1) {
        bad = pick
        break
      }
      chosen.push(n === keys.length + 1 ? '--dir' : keys[n - 1])
    }
    if (bad !== null) {
      console.log('  "' + bad + '" is not one of 1-' + (keys.length + 1) + '.')
      continue
    }
    if (!chosen.length) {
      console.log('  Nothing selected.')
      continue
    }
    let dirOverride = null
    if (chosen.includes('--dir')) {
      const p = await ask(rl, '  Skills directory (absolute path): ')
      if (p === null) throw new CliError(EXIT.FAIL, 'input ended before anything was installed')
      dirOverride = validateDir(p.trim(), false)
    }
    return { hosts: chosen, dirOverride }
  }
  throw new CliError(EXIT.REFUSED, 'no valid selection after ' + MAX_RETRIES + ' attempts')
}

async function chooseScope(rl) {
  console.log('\nInstall scope:\n')
  console.log('  1) Global -- every project     (default)')
  console.log('  2) Local  -- this project only (' + process.cwd() + ')\n')
  for (let attempt = 0; attempt < MAX_RETRIES; attempt += 1) {
    const answer = await ask(rl, 'Number [1]: ')
    if (answer === null) throw new CliError(EXIT.FAIL, 'input ended before anything was installed')
    const raw = answer.trim() || '1'
    if (raw === '1') return 'global'
    if (raw === '2') return 'local'
    console.log('  "' + raw + '" is not 1 or 2.')
  }
  throw new CliError(EXIT.REFUSED, 'no valid scope after ' + MAX_RETRIES + ' attempts')
}

// ---------------------------------------------------------------- commands

async function cmdInstall(opts) {
  const canonical = repoDir()
  const result = { command: 'install', checkout: canonical, source: repoUrl(), steps: [], targets: [] }
  const detected = detectedHosts()
  let hosts = opts.hosts
  let dirOverride = opts.dir
  let scope = opts.scope
  let rl = null

  try {
    if (!hosts.length && !dirOverride) {
      if (opts.yes) {
        // --yes applies the detected set; it never widens beyond what a human would have seen.
        hosts = detected
        if (!hosts.length) {
          throw new CliError(EXIT.REFUSED, 'no host detected on this machine', 'known hosts: ' + Object.keys(HOSTS).join(', ') + ' -- or use --dir <path>')
        }
      } else {
        requireTty('choosing which tools to install into')
        rl = readline.createInterface({ input: process.stdin, output: process.stdout })
        const picked = await chooseHosts(rl, detected)
        hosts = picked.hosts
        if (picked.dirOverride) dirOverride = picked.dirOverride
      }
    }
    if (dirOverride) {
      dirOverride = validateDir(dirOverride, opts.yes)
      if (!hosts.includes('--dir')) hosts = hosts.concat('--dir')
    }
    if (!scope) {
      if (opts.yes || hosts.every((h) => h === '--dir')) {
        scope = 'global'
      } else {
        requireTty('choosing global or local scope')
        if (!rl) rl = readline.createInterface({ input: process.stdin, output: process.stdout })
        scope = await chooseScope(rl)
      }
    }

    const resolved = resolveChannel(opts.channel, opts.ref)
    result.ref = resolved.ref
    result.channel = opts.ref ? 'explicit' : opts.channel
    if (resolved.skipped.length) result.skippedTags = resolved.skipped

    const plan = hosts.map((hostKey) => {
      const itemScope = hostKey === '--dir' ? 'dir' : scope
      const target = targetFor(hostKey, itemScope, dirOverride)
      return Object.assign({ host: hostKey, scope: itemScope, target }, classify(target, canonical))
    })

    // A directory at the target is the majority case, because the old README told everyone to clone
    // into it. Adopt when it is safe rather than refusing the users who most need the installer.
    let promote = null
    for (const item of plan) {
      if (item.state !== 'directory') continue
      const verdict = adoptability(item.target)
      item.adoptable = verdict.adoptable
      item.why = verdict.why
      item.currentRef = verdict.ref
      if (verdict.adoptable && !promote && !fs.existsSync(canonical)) promote = item
    }

    console.log('\nCheckout : ' + canonical)
    console.log('Source   : ' + repoUrl())
    console.log('Ref      : ' + resolved.ref + (resolved.skipped.length ? '  (skipped non-conforming: ' + resolved.skipped.join(', ') + ')' : ''))
    console.log('\nPlan:')
    for (const item of plan) {
      const name = item.host === '--dir' ? 'dir' : item.host
      let note = item.state
      if (item.state === 'divergent') note = 'symlink -> ' + item.real
      if (item.state === 'directory') note = item.adoptable ? 'directory, adoptable (' + item.currentRef + ')' : 'directory, NOT adoptable: ' + item.why
      console.log('  ' + name.padEnd(10) + item.target)
      console.log('  ' + ''.padEnd(10) + note)
    }
    if (promote) {
      console.log('\n  ' + promote.target)
      console.log('  will be MOVED to the canonical checkout (untracked files come with it).')
    }
    // Every existing entrypoint on the author's machine sits on an unmerged feature branch, so
    // repointing one at a release tag must never be silent.
    for (const item of plan) {
      if (item.currentRef && item.currentRef !== resolved.ref) {
        console.log('\n  ' + item.target)
        console.log('  moves from ' + item.currentRef + ' to ' + resolved.ref + '.')
      }
    }

    if (opts.dryRun) {
      result.dryRun = true
      result.plan = plan.map((i) => ({ host: i.host, scope: i.scope, target: i.target, state: i.state, adoptable: i.adoptable, why: i.why, currentRef: i.currentRef }))
      if (promote) result.promote = promote.target
      return result
    }

    if (!opts.yes) {
      requireTty('confirming the plan')
      if (!rl) rl = readline.createInterface({ input: process.stdin, output: process.stdout })
      if (!(await confirm(rl, '\nProceed?'))) throw new CliError(EXIT.REFUSED, 'cancelled; nothing was changed')
    }
    if (rl) {
      rl.close()
      rl = null
    }

    acquireLock()

    if (promote) {
      fs.mkdirSync(path.dirname(canonical), { recursive: true })
      fs.renameSync(promote.target, canonical)
      result.steps.push({ step: 'promote', from: promote.target, to: canonical })
      promote.state = 'absent'
    }

    // The checkout must fully succeed before the first symlink is attempted.
    ensureCheckout(resolved.ref, result.steps)
    result.version = verifyCheckout(canonical)

    let failures = 0
    for (const item of plan) {
      const entry = { host: item.host, scope: item.scope, target: item.target }
      try {
        const current = classify(item.target, canonical)
        if (current.state === 'linked') {
          entry.outcome = 'already linked'
        } else if (current.state === 'absent') {
          entry.outcome = link(item.target, canonical)
        } else if (current.state === 'file') {
          throw new CliError(EXIT.REFUSED, item.target + ' is a regular file')
        } else if (!opts.force) {
          throw new CliError(
            EXIT.REFUSED,
            item.target + ' already exists (' + current.state + (current.real ? ' -> ' + current.real : '') + ')',
            'pass --force to back it up and replace it',
          )
        } else if (current.state === 'dangling' || current.state === 'divergent') {
          fs.unlinkSync(item.target)
          entry.outcome = link(item.target, canonical)
        } else {
          entry.backup = backup(item.target, item.host === '--dir' ? 'dir' : item.host)
          entry.outcome = link(item.target, canonical)
        }
        recordReceipt(Object.assign({}, entry, { canonical, createdAt: new Date().toISOString(), cliVersion: cliVersion() }))
      } catch (err) {
        // Partial failure is reported, never rolled back: linking is idempotent, so a re-run
        // reconciles the remainder, and undoing a good link helps nobody.
        failures += 1
        entry.outcome = 'failed'
        entry.error = err.message
        if (err.detail) entry.detail = err.detail
      }
      result.targets.push(entry)
      console.log('  ' + String(entry.outcome).padEnd(16) + entry.target + (entry.backup ? '  (backup: ' + entry.backup + ')' : ''))
    }

    result.failures = failures
    if (failures) result.exitCode = EXIT.FAIL
    return result
  } finally {
    if (rl) rl.close()
    releaseLock()
  }
}

async function cmdUpdate(opts) {
  const dir = repoDir()
  if (!fs.existsSync(dir)) throw new CliError(EXIT.FAIL, 'no checkout at ' + dir, 'run `install` first')
  assertUsable(dir)

  const resolved = resolveChannel(opts.channel, opts.ref)
  const result = { command: 'update', checkout: dir, ref: resolved.ref, steps: [] }
  if (resolved.skipped.length) result.skippedTags = resolved.skipped

  acquireLock()
  try {
    ensureCheckout(resolved.ref, result.steps)
    result.version = verifyCheckout(dir)
    result.linked = readReceipts().map((e) => ({ host: e.host, target: e.target }))
    const step = result.steps[result.steps.length - 1]
    console.log((step.from || '(none)') + ' -> ' + result.version + '   ref ' + resolved.ref)
    for (const l of result.linked) console.log('  covers ' + String(l.host).padEnd(10) + l.target)
    return result
  } finally {
    releaseLock()
  }
}

async function cmdUninstall(opts) {
  const canonical = repoDir()
  const entries = readReceipts()
  const wanted = opts.hosts.length ? entries.filter((e) => opts.hosts.includes(e.host)) : entries
  const result = { command: 'uninstall', targets: [] }

  if (!wanted.length && !opts.purge) {
    console.log('Nothing recorded to remove.')
    return result
  }

  acquireLock()
  try {
    const kept = []
    for (const entry of entries) {
      if (!wanted.includes(entry)) {
        kept.push(entry)
        continue
      }
      const out = { host: entry.host, target: entry.target }
      const state = classify(entry.target, entry.canonical || canonical)
      if (state.state === 'linked') {
        fs.unlinkSync(entry.target) // unlink, never rm -rf, and never follow the link
        out.outcome = 'removed'
      } else {
        // A recorded target that is now a directory, or that points somewhere else, is left alone.
        out.outcome = 'left in place (' + state.state + ')'
        kept.push(entry)
      }
      result.targets.push(out)
      console.log('  ' + out.outcome.padEnd(28) + entry.target)
    }
    writeReceipts(kept)

    if (opts.purge) {
      if (!fs.existsSync(canonical)) {
        console.log('  checkout already absent')
      } else {
        assertUsable(canonical)
        const unpushed = unpushedCommits(canonical)
        if (unpushed.length) {
          throw new CliError(EXIT.REFUSED, 'checkout has commits that are not on the remote', unpushed.join('\n'))
        }
        // --purge always confirms, even under --yes: it is the one path that removes a work tree.
        requireTty('confirming --purge')
        const rl = readline.createInterface({ input: process.stdin, output: process.stdout })
        try {
          if (!(await confirm(rl, 'Delete the checkout at ' + canonical + '?'))) {
            throw new CliError(EXIT.REFUSED, 'purge cancelled; the checkout was kept')
          }
        } finally {
          rl.close()
        }
        fs.rmSync(canonical, { recursive: true, force: true })
        result.purged = canonical
        console.log('  removed ' + canonical)
      }
    }
    return result
  } finally {
    releaseLock()
  }
}

// ---------------------------------------------------------------- entry

function cliVersion() {
  try {
    const here = path.dirname(fileURLToPath(import.meta.url))
    return JSON.parse(fs.readFileSync(path.join(here, '..', 'package.json'), 'utf8')).version
  } catch {
    return 'unknown'
  }
}

const HELP = [
  'img2threejs -- install the img2threejs skill into your agent hosts',
  '',
  'Usage',
  '  npx -y github:img2threejs/img2threejs install [hosts...] [options]',
  '  npx -y github:img2threejs/img2threejs update [options]',
  '  npx -y github:img2threejs/img2threejs uninstall [hosts...] [--purge]',
  '',
  'Hosts',
  '  claude     ~/.claude/skills    or  <project>/.claude/skills',
  '  codex      ~/.codex/skills     or  <project>/.codex/skills',
  '  opencode   $XDG_CONFIG_HOME/opencode/skills  or  <project>/.opencode/skills',
  '',
  'Options',
  '  --global        install for every project (default)',
  '  --local         install for the current project only',
  '  --dir <path>    link into any other skills directory',
  '  --channel <c>   stable (default) | beta | main',
  '  --ref <ref>     check out an explicit tag, branch or commit',
  '  --allow-fork    accept a checkout whose origin is not the project remote',
  '  --force         back up and replace an existing target',
  '  --purge         uninstall: also remove the canonical checkout',
  '  --yes           never prompt; applies the detected host set',
  '  --dry-run       print the plan and change nothing',
  '  --json          print the resolved plan and per-target outcome as JSON',
  '  --version       print the CLI version and the installed skill version',
  '  --help          this text',
  '',
  'Environment',
  '  IMG2THREEJS_HOME      parent directory (default ~/.img2threejs); checkout is <home>/repo',
  '  IMG2THREEJS_REPO_URL  clone source; accepts file:// for offline use',
  '  XDG_CONFIG_HOME       honoured for the OpenCode path',
  '',
  'Exit codes',
  '  0  success',
  '  1  operational failure',
  '  2  refused; a flag is needed to proceed',
  '  3  interactive input required but stdin is not a terminal',
].join('\n')

function parseArgs(argv) {
  const opts = { hosts: [], channel: 'stable', scope: null, dir: null, ref: null, yes: false, force: false, purge: false, json: false, dryRun: false, help: false, showVersion: false }
  let command = null
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i]
    if (arg === '--help' || arg === '-h') opts.help = true
    else if (arg === '--version' || arg === '-v') opts.showVersion = true
    else if (arg === '--global') opts.scope = 'global'
    else if (arg === '--local') opts.scope = 'local'
    else if (arg === '--yes' || arg === '-y') opts.yes = true
    else if (arg === '--force') opts.force = true
    else if (arg === '--purge') opts.purge = true
    else if (arg === '--json') opts.json = true
    else if (arg === '--dry-run') opts.dryRun = true
    else if (arg === '--allow-fork') flagAllowFork = true
    else if (arg === '--dir') { i += 1; opts.dir = argv[i] }
    else if (arg === '--channel') { i += 1; opts.channel = argv[i] }
    else if (arg === '--ref') { i += 1; opts.ref = argv[i] }
    else if (arg.startsWith('-')) throw new CliError(EXIT.REFUSED, 'unknown option: ' + arg, 'run --help for the flag list')
    else if (!command) command = arg
    else opts.hosts.push(arg)
  }
  if (['stable', 'beta', 'main'].indexOf(opts.channel) === -1) {
    throw new CliError(EXIT.REFUSED, 'unknown channel: ' + opts.channel, 'use stable, beta or main')
  }
  for (const h of opts.hosts) {
    if (!HOSTS[h]) {
      throw new CliError(EXIT.REFUSED, 'unknown host: ' + h, 'known hosts: ' + Object.keys(HOSTS).join(', ') + ' -- or use --dir <path>')
    }
  }
  return { command, opts }
}

async function main() {
  if (Number(process.versions.node.split('.')[0]) < MIN_NODE) {
    console.error('img2threejs: needs Node ' + MIN_NODE + ' or newer, found ' + process.versions.node)
    return EXIT.FAIL
  }

  const parsed = parseArgs(process.argv.slice(2))
  const opts = parsed.opts

  if (opts.showVersion) {
    // Two versions, because npm caches git dependencies: a stale CLI against a fresh checkout is a
    // real state, and printing one number is how that becomes invisible.
    console.log('cli   ' + cliVersion())
    console.log('skill ' + (skillVersion(repoDir()) || '(not installed)'))
    return EXIT.OK
  }
  if (opts.help || !parsed.command) {
    console.log(HELP)
    return opts.help ? EXIT.OK : EXIT.REFUSED
  }

  let result
  if (parsed.command === 'install') result = await cmdInstall(opts)
  else if (parsed.command === 'update') result = await cmdUpdate(opts)
  else if (parsed.command === 'uninstall') result = await cmdUninstall(opts)
  else throw new CliError(EXIT.REFUSED, 'unknown command: ' + parsed.command, 'expected install, update or uninstall')

  if (opts.json) console.log(JSON.stringify(result, null, 2))
  return result.exitCode || EXIT.OK
}

process.on('SIGINT', () => {
  releaseLock()
  process.exit(EXIT.FAIL)
})

main()
  .then((code) => process.exit(code))
  .catch((err) => {
    releaseLock()
    console.error('img2threejs: ' + err.message)
    if (err.detail) console.error(err.detail)
    process.exit(err instanceof CliError ? err.code : EXIT.FAIL)
  })
