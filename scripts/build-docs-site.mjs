import { cp, mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises'
import { createWriteStream, existsSync } from 'node:fs'
import { Readable } from 'node:stream'
import { pipeline } from 'node:stream/promises'
import path from 'node:path'
import { spawn } from 'node:child_process'

const root = process.cwd()
const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm'
const vitepress = path.join(
  root,
  'node_modules',
  '.bin',
  process.platform === 'win32' ? 'vitepress.cmd' : 'vitepress',
)

const finalDist = path.join(root, 'docs', '.vitepress', 'dist')
// Stable docs are materialized here from the latest release tag, then built in
// the same VitePress pass as the working-tree dev docs. Gitignored; removed
// after the build so the working tree stays clean.
const stableDir = path.join(root, 'docs', 'en', 'stable')
const workingTreeDev = path.join(root, 'docs', 'en', 'dev')
const workDir = path.join(root, '.docs-channels')
const extractRoot = path.join(workDir, 'extract')
const gitArchive = path.join(workDir, 'tag.tar')
const httpTarball = path.join(workDir, 'tag.tgz')

function run(command, args, { env = {}, capture = false } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: root,
      env: { ...process.env, ...env },
      stdio: capture ? ['ignore', 'pipe', 'inherit'] : 'inherit',
    })

    let out = ''
    if (capture) {
      child.stdout.on('data', (chunk) => {
        out += chunk
      })
    }

    child.on('error', reject)
    child.on('exit', (code) => {
      if (code === 0) {
        resolve(out)
        return
      }
      reject(new Error(`${command} ${args.join(' ')} exited with ${code}`))
    })
  })
}

async function tryRun(command, args, options) {
  try {
    return { ok: true, out: await run(command, args, options) }
  } catch (error) {
    return { ok: false, error }
  }
}

// The GitHub repo to pull released docs from. Derived from the git remote (or
// REPO_SLUG) so forks and renames work without editing this script.
async function resolveRepoSlug() {
  if (process.env.REPO_SLUG) {
    return process.env.REPO_SLUG
  }
  const remote = await tryRun('git', ['remote', 'get-url', 'origin'], {
    capture: true,
  })
  const match =
    remote.ok && remote.out.trim().match(/github\.com[:/]+([^/]+\/[^/]+?)(?:\.git)?$/)
  return match ? match[1] : 'DevilsAutumn/quater'
}

// Authenticate GitHub HTTPS calls when a token is available. Unauthenticated API
// requests are capped at 60/hour per IP, which Vercel's shared build fleet can
// exhaust; a token raises that to 5000/hour.
function githubHeaders() {
  const headers = {
    'User-Agent': 'quater-docs-build',
    Accept: 'application/vnd.github+json',
  }
  const token = process.env.GITHUB_TOKEN || process.env.GH_TOKEN
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }
  return headers
}

// Order: alpha < beta < rc < final. Pre-release tags rank below their release.
const preReleaseRank = { a: 0, b: 1, rc: 2 }

function parseVersion(tag) {
  const match = /^v?(\d+)\.(\d+)\.(\d+)(?:(a|b|rc)(\d+))?$/.exec(tag.trim())
  if (match === null) {
    return null
  }
  const [, major, minor, patch, pre, preNumber] = match
  return {
    tag,
    parts: [
      Number(major),
      Number(minor),
      Number(patch),
      pre ? preReleaseRank[pre] : 3,
      pre ? Number(preNumber) : 0,
    ],
  }
}

function compareVersions(a, b) {
  for (let index = 0; index < a.parts.length; index += 1) {
    if (a.parts[index] !== b.parts[index]) {
      return a.parts[index] - b.parts[index]
    }
  }
  return 0
}

// Tag names from the remote, used when the local checkout has no tags. Uses the
// full repo URL (not "origin") so it works in builds without a configured
// remote, with a GitHub API fallback if the git protocol is blocked.
async function remoteTagNames(slug, headers) {
  const lsRemote = await tryRun(
    'git',
    ['ls-remote', '--tags', `https://github.com/${slug}.git`],
    { capture: true },
  )
  if (lsRemote.ok) {
    const names = lsRemote.out
      .split('\n')
      .map((line) => line.split('refs/tags/').pop() ?? '')
      .map((name) => name.replace(/\^\{\}$/, ''))
    if (names.some((name) => parseVersion(name))) {
      return names
    }
  }

  try {
    const response = await fetch(
      `https://api.github.com/repos/${slug}/tags?per_page=100`,
      { headers },
    )
    if (response.ok) {
      return (await response.json()).map((entry) => entry.name)
    }
  } catch {
    // Ignore and report no tags.
  }
  return []
}

// Stable tracks the newest release tag, including pre-releases (a/b/rc), since
// the project ships pre-1.0 betas. To pin stable to final releases only, drop
// versions whose parts[3] !== 3 before sorting.
async function latestReleaseTag(slug, headers) {
  const local = await tryRun('git', ['tag'], { capture: true })
  let names = local.ok ? local.out.split('\n') : []

  if (names.filter((name) => parseVersion(name)).length === 0) {
    names = await remoteTagNames(slug, headers)
  }

  const versions = names
    .map((name) => parseVersion(name))
    .filter((version) => version !== null)
  if (versions.length === 0) {
    return null
  }
  versions.sort(compareVersions)
  return versions[versions.length - 1].tag
}

// Stream an HTTPS response body to disk without buffering the whole file in
// memory (Vercel caps build heap; repo tarballs would otherwise sit in the heap).
async function downloadToFile(url, dest, headers) {
  const response = await fetch(url, { headers })
  if (!response.ok || response.body === null) {
    return false
  }
  await pipeline(Readable.fromWeb(response.body), createWriteStream(dest))
  return true
}

// Extract docs/en/dev at the tag using local git. Fast and offline when the tag
// is present; fetches it once if a shallow clone lacks it.
async function fetchTagViaGit(tag, slug) {
  const present = await tryRun('git', ['cat-file', '-e', `${tag}^{tree}`])
  if (!present.ok) {
    const fetched = await tryRun('git', [
      'fetch',
      '--depth',
      '1',
      `https://github.com/${slug}.git`,
      `refs/tags/${tag}:refs/tags/${tag}`,
    ])
    if (!fetched.ok) {
      return false
    }
  }
  const archived = await tryRun('git', [
    'archive',
    '--format=tar',
    `--output=${gitArchive}`,
    tag,
    '--',
    'docs/en/dev',
  ])
  if (!archived.ok) {
    return false
  }
  const extracted = await tryRun('tar', ['-xf', gitArchive, '-C', extractRoot])
  await rm(gitArchive, { force: true })
  return extracted.ok
}

// Extract docs/en/dev at the tag from the GitHub source tarball over HTTPS. This
// is the path that works in builds without git history or a remote (Vercel).
async function fetchTagViaTarball(tag, slug, headers) {
  let downloaded
  try {
    downloaded = await downloadToFile(
      `https://codeload.github.com/${slug}/tar.gz/refs/tags/${tag}`,
      httpTarball,
      headers,
    )
  } catch {
    return false
  }
  if (!downloaded) {
    return false
  }
  // Strip the "<repo>-<tag>/" top-level directory.
  const extracted = await tryRun('tar', [
    '-xzf',
    httpTarball,
    '-C',
    extractRoot,
    '--strip-components=1',
  ])
  await rm(httpTarball, { force: true })
  return extracted.ok
}

// Copy a docs tree, rewriting in-page Markdown links from the dev channel to the
// stable channel. Only link targets ("](/en/dev/") are touched, never prose or
// inline code that documents the source tree.
async function copyWithStableLinks(srcDir, destDir) {
  await mkdir(destDir, { recursive: true })
  for (const entry of await readdir(srcDir, { withFileTypes: true })) {
    const from = path.join(srcDir, entry.name)
    const to = path.join(destDir, entry.name)
    if (entry.isDirectory()) {
      await copyWithStableLinks(from, to)
    } else if (entry.name.endsWith('.md')) {
      const text = await readFile(from, 'utf8')
      await writeFile(to, text.replaceAll('](/en/dev/', '](/en/stable/'))
    } else {
      await cp(from, to)
    }
  }
}

// Materialize docs/en/stable (links pointed at the stable channel) so the
// channel — and the homepage links that target it — always exist in the
// deployable build. Prefers the latest release tag. If a tag exists but cannot
// be fetched, throws so the build fails loudly (the platform keeps the previous
// good deploy) rather than silently shipping stable from unreleased content.
// With no tag yet, mirrors the working tree until the first release is cut.
// Returns true when stable came from the tag.
async function materializeStable(tag, slug, headers) {
  await rm(workDir, { recursive: true, force: true })
  await mkdir(extractRoot, { recursive: true })

  let stableContent = workingTreeDev
  if (tag !== null) {
    // Prefer local git; fall back to the HTTPS tarball for git-less build hosts.
    const fetched =
      (await fetchTagViaGit(tag, slug)) ||
      (await fetchTagViaTarball(tag, slug, headers))
    const tagDev = path.join(extractRoot, 'docs', 'en', 'dev')
    if (!fetched || !existsSync(tagDev)) {
      await rm(workDir, { recursive: true, force: true })
      throw new Error(
        `Could not fetch docs for release tag ${tag}. Refusing to publish ` +
          `stable docs from unreleased content. Check network access or set ` +
          `GITHUB_TOKEN, then retry.`,
      )
    }
    stableContent = tagDev
  }

  await rm(stableDir, { recursive: true, force: true })
  await copyWithStableLinks(stableContent, stableDir)
  await rm(workDir, { recursive: true, force: true })
  return tag !== null
}

// The reference pages are committed, so the deploy does not need the Python
// toolchain. Skip the regeneration check on Vercel (no uv); CI still runs it.
if (!process.env.VERCEL) {
  await run(npm, ['run', 'docs:reference:check'])
}

const slug = await resolveRepoSlug()
const headers = githubHeaders()
const tag = await latestReleaseTag(slug, headers)
const fromTag = await materializeStable(tag, slug, headers)
console.log(
  fromTag
    ? `Materialized stable channel from ${tag}.`
    : 'No release tag found; stable mirrors the working tree until the first release is tagged.',
)

// A single VitePress build over both channels keeps one consistent client-side
// site config, so the sidebar and in-app navigation work on every channel.
try {
  await rm(finalDist, { recursive: true, force: true })
  await run(vitepress, ['build', 'docs'])
} finally {
  await rm(stableDir, { recursive: true, force: true })
}

console.log('Built docs/.vitepress/dist with /en/stable/ and /en/dev/.')
