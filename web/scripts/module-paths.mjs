import { readdirSync } from 'node:fs'
import { join } from 'node:path'

// TypeScript resolves .ts before .tsx. Differently cased stems can resolve to
// the wrong module on Windows/macOS even when both files exist on Linux.
export function validateModulePaths(root) {
  const modules = new Map()
  function visit(directory) {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const path = join(directory, entry.name)
      if (entry.isDirectory()) visit(path)
      else if (/\.[jt]sx?$/.test(entry.name)) {
        const key = path.replace(/\.[jt]sx?$/, '').toLowerCase()
        if (modules.has(key)) throw new Error(`Ambiguous module paths on case-insensitive systems: ${modules.get(key)} and ${path}`)
        modules.set(key, path)
      }
    }
  }
  visit(root)
}
