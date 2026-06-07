import { cp, mkdir, readFile, rm, writeFile } from 'node:fs/promises'
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

const vitepressDir = path.join(root, 'docs', '.vitepress')
const finalDist = path.join(vitepressDir, 'dist')
// Scratch space lives outside .vitepress so copying the config into the temp
// stable source tree is not a copy-into-self.
const workDir = path.join(root, '.docs-channels')
const stableDist = path.join(workDir, 'stable')
const devDist = path.join(workDir, 'dev')
// Temp docs tree used to build the stable channel from the latest release tag.
const stableSrc = path.join(workDir, 'stable-src')
const stableSrcDocs = path.join(stableSrc, 'docs')
const tagArchive = path.join(workDir, 'stable-tag.tar')

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

// Stable tracks the newest release tag, including pre-releases (a/b/rc), since
// the project ships pre-1.0 betas. To pin stable to final releases only, drop
// versions whose parts[3] !== 3 before sorting.
async function latestReleaseTag() {
  let names = []

  const local = await tryRun('git', ['tag'], { capture: true })
  if (local.ok) {
    names = local.out.split('\n')
  }

  if (names.filter((name) => parseVersion(name)).length === 0) {
    const remote = await tryRun('git', ['ls-remote', '--tags', 'origin'], {
      capture: true,
    })
    if (remote.ok) {
      names = remote.out
        .split('\n')
        .map((line) => line.split('refs/tags/').pop() ?? '')
        .map((name) => name.replace(/\^\{\}$/, ''))
    }
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

async function ensureTagPresent(tag) {
  const present = await tryRun('git', ['cat-file', '-e', `${tag}^{tree}`])
  if (present.ok) {
    return true
  }
  // Shallow CI/Vercel clones may not carry tags; fetch just this one.
  const fetched = await tryRun('git', [
    'fetch',
    '--depth',
    '1',
    'origin',
    `refs/tags/${tag}:refs/tags/${tag}`,
  ])
  return fetched.ok
}

// Build a docs tree whose markdown content comes from the release tag but whose
// theme/config/home come from the working tree, so both channels render the
// same way. Returns the docs root to build, or null to fall back to the
// working-tree docs (used when no release tag is reachable).
async function materializeStableSource(tag) {
  if (tag === null) {
    return null
  }
  if (!(await ensureTagPresent(tag))) {
    return null
  }

  await rm(stableSrc, { recursive: true, force: true })
  await mkdir(stableSrcDocs, { recursive: true })

  const archived = await tryRun('git', [
    'archive',
    '--format=tar',
    `--output=${tagArchive}`,
    tag,
    '--',
    'docs/en/dev',
  ])
  if (!archived.ok) {
    return null
  }
  const extracted = await tryRun('tar', ['-xf', tagArchive, '-C', stableSrc])
  if (!extracted.ok) {
    return null
  }
  await rm(tagArchive, { force: true })

  // Theme, config, home, and public assets come from the working tree.
  await cp(vitepressDir, path.join(stableSrcDocs, '.vitepress'), {
    recursive: true,
    filter: (source) => {
      const rel = path.relative(vitepressDir, source)
      return !rel.startsWith('dist') && !rel.startsWith('cache')
    },
  })
  await cp(path.join(root, 'docs', 'public'), path.join(stableSrcDocs, 'public'), {
    recursive: true,
  })
  await cp(path.join(root, 'docs', 'index.md'), path.join(stableSrcDocs, 'index.md'))

  return stableSrcDocs
}

async function readJson(filePath) {
  return JSON.parse(await readFile(filePath, 'utf8'))
}

async function mergeHashmaps() {
  const stable = await readJson(path.join(stableDist, 'hashmap.json'))
  const dev = await readJson(path.join(devDist, 'hashmap.json'))
  await writeFile(
    path.join(finalDist, 'hashmap.json'),
    `${JSON.stringify({ ...stable, ...dev })}\n`,
  )
}

async function buildChannel(channel, docsRoot, outDir) {
  await rm(outDir, { recursive: true, force: true })
  await run(vitepress, ['build', docsRoot], {
    env: {
      QUATER_DOCS_CHANNEL: channel,
      QUATER_DOCS_OUT_DIR: outDir,
    },
  })
}

// The reference pages are committed, so the deploy does not need the Python
// toolchain. Skip the regeneration check on Vercel (no uv); CI still runs it.
if (!process.env.VERCEL) {
  await run(npm, ['run', 'docs:reference:check'])
}

await rm(workDir, { recursive: true, force: true })
await mkdir(workDir, { recursive: true })

const tag = await latestReleaseTag()
const stableDocsRoot = await materializeStableSource(tag)
if (stableDocsRoot === null) {
  console.warn(
    tag === null
      ? 'No release tag found; building stable from the working tree.'
      : `Could not load docs from ${tag}; building stable from the working tree.`,
  )
} else {
  console.log(`Building stable channel from ${tag}.`)
}

await buildChannel('stable', stableDocsRoot ?? 'docs', stableDist)
await buildChannel('dev', 'docs', devDist)

await rm(finalDist, { recursive: true, force: true })
await cp(stableDist, finalDist, { recursive: true })
await mkdir(path.join(finalDist, 'en'), { recursive: true })
await cp(path.join(devDist, 'en', 'dev'), path.join(finalDist, 'en', 'dev'), {
  recursive: true,
})
await cp(path.join(devDist, 'assets'), path.join(finalDist, 'assets'), {
  recursive: true,
  force: true,
})
await mergeHashmaps()
// The sitemap is intentionally stable-only: it comes from the stable dist copied
// above and is not merged with dev. Dev pages are noindex, so listing them in the
// sitemap would send crawlers conflicting signals.
await rm(workDir, { recursive: true, force: true })

console.log('Built docs/.vitepress/dist with /en/stable/ and /en/dev/.')
