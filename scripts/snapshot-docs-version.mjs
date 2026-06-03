import { access, cp, mkdir, readdir, rm } from 'node:fs/promises'
import path from 'node:path'

const requestedVersion = process.argv[2]
const force = process.argv.includes('--force')

if (
  !requestedVersion ||
  !/^v?\d+\.\d+(?:\.\d+)?(?:a\d+|b\d+|rc\d+)?(?:-[0-9A-Za-z.-]+)?$/.test(requestedVersion)
) {
  console.error('Usage: npm run docs:snapshot -- 0.1.0b1 [--force]')
  process.exit(1)
}

const version = requestedVersion.replace(/^v/, '')
const root = process.cwd()
const source = path.join(root, 'docs', 'en', 'dev')
const target = path.join(root, 'docs', 'en', version)

async function pathExists(targetPath) {
  try {
    await access(targetPath)
    return true
  } catch {
    return false
  }
}

if (!(await pathExists(source))) {
  console.error('docs/en/dev does not exist.')
  process.exit(1)
}

if (await pathExists(target)) {
  const existingFiles = await readdir(target)
  if (existingFiles.length > 0 && !force) {
    console.error(`docs/en/${version} already exists. Re-run with --force to replace it.`)
    process.exit(1)
  }
  if (force) {
    await rm(target, { recursive: true, force: true })
  }
}

await mkdir(path.dirname(target), { recursive: true })
await cp(source, target, { recursive: true })

console.log(`Created docs/en/${version}`)
