import { existsSync, readdirSync, rmSync, unlinkSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { validateModulePaths } from './module-paths.mjs'

validateModulePaths(fileURLToPath(new URL('../src/', import.meta.url)))

const output = fileURLToPath(new URL('../dist/', import.meta.url))
function removeFiles(directory) {
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) removeFiles(path)
    else unlinkSync(path)
  }
}
if (existsSync(output)) { removeFiles(output); rmSync(output, { recursive: true, force: true }) }
