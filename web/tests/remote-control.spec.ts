import { expect, test } from '@playwright/test'

const token = 'browser-test-only-token-not-a-secret'
const headers = { Authorization: `Bearer ${token}` }
const root = 'http://127.0.0.1:8000/api'

test('dashboard registers a node, selects a model, launches, stops, and reconfigures a teammate', async ({ page, request }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  const p = await request.post(`${root}/projects`, { headers, data: {
    name: 'Remote control lab', goal: 'Manage remote teammates and the right model for each role.', auto_plan: false,
  } }).then(response => response.json())
  const agent = await request.post(`${root}/projects/${p.id}/agents`, { headers, data: {
    name: 'Atlas', kind: 'opencode', capabilities: ['architecture', 'review'],
  } }).then(response => response.json())
  await page.goto('/')
  await page.getByLabel('Workspace access token').fill(token)
  await page.getByRole('button', { name: 'Enter your workspace' }).click()
  await page.getByRole('button', { name: 'Agents & connections', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Your team, ready on command.' })).toBeVisible()
  await page.getByRole('button', { name: 'Add remote node', exact: true }).click()
  await page.getByLabel('Node name').fill('Development VPS')
  await page.getByRole('button', { name: 'Register node' }).click()
  await expect(page.getByRole('heading', { name: 'Development VPS is ready to connect.' })).toBeVisible()
  const nodeToken = await page.locator('.copy-box code').innerText()
  expect(nodeToken).toMatch(/^acn_/)
  await page.getByRole('button', { name: 'I saved the node token' }).click()
  const nodes = await request.get(`${root}/projects/${p.id}/nodes`, { headers }).then(response => response.json())
  const node = nodes[0]
  const nodeHeaders = { Authorization: `Bearer ${nodeToken}` }
  const session = 'c'.repeat(32)
  const registration = await request.post(`${root}/nodes/me/register`, { headers: nodeHeaders, data: {
    session_id: session,
    profiles: [{ id: 'opencode', name: 'OpenCode CLI', kind: 'opencode', models: [
      { id: 'provider/fast', name: 'Fast coding' }, { id: 'provider/reasoning', name: 'Deep reasoning' },
    ] }],
  } })
  expect(registration.ok()).toBeTruthy()
  await expect(page.locator('.node-card .badge')).toHaveText('Online')
  await page.getByRole('button', { name: 'Configure Atlas', exact: true }).click()
  await page.getByLabel('Remote node', { exact: true }).selectOption(node.id)
  await page.getByLabel('Agent runtime', { exact: true }).selectOption('opencode')
  await page.getByLabel('Model', { exact: true }).selectOption('provider/reasoning')
  await page.getByRole('button', { name: 'Save runtime' }).click()
  const card = page.getByRole('region', { name: 'Atlas agent' })
  await expect(card.locator('.runtime-summary')).toContainText('Deep reasoning')
  await page.getByRole('button', { name: 'Launch Atlas', exact: true }).click()
  await expect(card.locator('.badge')).toHaveText('queued')
  await expect(page.getByRole('button', { name: 'Configure Atlas', exact: true })).toBeDisabled()
  const poll = await request.post(`${root}/nodes/me/poll`, { headers: nodeHeaders, data: { session_id: session } }).then(response => response.json())
  const runtime = poll.runtimes[0]
  expect(runtime.model).toBe('provider/reasoning')
  await request.post(`${root}/nodes/me/report`, { headers: nodeHeaders, data: {
    session_id: session, agent_id: agent.agent.id, run_id: runtime.run_id, state: 'running', pid: 4242,
  } })
  await expect(card.locator('.badge')).toHaveText('running')
  await expect(card.locator('.runtime-summary')).toContainText('Worker PID 4242')
  if (process.env.UPDATE_SCREENSHOTS) await page.screenshot({ path: '../docs/assets/remote-control.png', fullPage: true })
  await page.getByRole('button', { name: 'Stop Atlas', exact: true }).click()
  await expect(card.locator('.badge')).toHaveText('stopping')
  await expect(page.getByRole('button', { name: 'Stop Atlas', exact: true })).toBeDisabled()
  await request.post(`${root}/nodes/me/report`, { headers: nodeHeaders, data: {
    session_id: session, agent_id: agent.agent.id, run_id: runtime.run_id, state: 'stopped',
  } })
  await expect(card.locator('.badge')).toHaveText('stopped')
  await page.getByRole('button', { name: 'Configure Atlas', exact: true }).click()
  await page.getByLabel('Model', { exact: true }).selectOption('provider/fast')
  await page.getByRole('button', { name: 'Save runtime' }).click()
  await expect(card.locator('.runtime-summary')).toContainText('Fast coding')
  await request.post(`${root}/nodes/me/disconnect`, { headers: nodeHeaders, data: { session_id: session } })
  await expect(page.locator('.node-card .badge')).toHaveText('Offline')
  await expect(page.getByRole('button', { name: 'Launch Atlas', exact: true })).toBeDisabled()
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(card).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  expect(errors).toEqual([])
})
