import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { validateModulePaths } from './module-paths.mjs'

test('reject a ts/tsx name that resolves differently on Windows and macOS', () => {
  const root = mkdtempSync(join(tmpdir(), 'agentverse-module-paths-'))
  try {
    writeFileSync(join(root, 'ConnectionPrompt.tsx'), 'export default function Component() {}')
    writeFileSync(join(root, 'connectionPrompt.ts'), 'export function builder() {}')
    assert.throws(() => validateModulePaths(root), /Ambiguous module paths/)
    rmSync(join(root, 'connectionPrompt.ts'))
    writeFileSync(join(root, 'agentConnectionRecipe.ts'), 'export function builder() {}')
    assert.doesNotThrow(() => validateModulePaths(root))
  } finally { rmSync(root, { recursive: true, force: true }) }
})
