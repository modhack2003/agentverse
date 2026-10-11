// Ship the dashboard with the Python package; CI checks it against a fresh build.
import { cpSync, existsSync, readdirSync, readFileSync, rmSync, unlinkSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join, relative } from 'node:path'

const source = fileURLToPath(new URL('../dist/', import.meta.url))
const target = fileURLToPath(new URL('../../src/agentcommons/web/', import.meta.url))
const files = (root, directory = root) => readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
  const path = join(directory, entry.name)
  return entry.isDirectory() ? files(root, path) : [relative(root, path)]
}).sort()

if (process.argv.includes('--check')) {
  if (!existsSync(target) || JSON.stringify(files(source)) !== JSON.stringify(files(target)) ||
      files(source).some(path => !readFileSync(join(source, path)).equals(readFileSync(join(target, path))))) {
    console.error('Packaged dashboard is stale. Run: cd web && npm run bundle')
    process.exit(1)
  }
  console.log('Packaged dashboard matches the fresh frontend build.')
} else {
  if (existsSync(target)) for (const path of files(target)) unlinkSync(join(target, path))
  rmSync(target, { recursive: true, force: true })
  cpSync(source, target, { recursive: true })
  console.log('Dashboard copied into the Python package.')
}
