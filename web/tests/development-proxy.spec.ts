import { expect, test } from '@playwright/test'

const root = 'http://127.0.0.1:8000/api'
const token = 'browser-test-only-token-not-a-secret'
const headers = { Authorization: `Bearer ${token}` }

test('development proxy saves typed runtime settings while live updates are connected', async ({ page, request }) => {
  const project = await request.post(`${root}/projects`, { headers, data: {
    name: 'Development proxy acceptance', goal: 'Save through the HTTP proxy with an active WebSocket.', auto_plan: false,
  } }).then(response => response.json())
  const peer = await request.post(`${root}/projects/${project.id}/agents`, { headers, data: {
    name: 'Development peer', kind: 'future-tool',
  } }).then(response => response.json())
  const node = await request.post(`${root}/projects/${project.id}/nodes`, { headers, data: { name: 'Development node' } }).then(response => response.json())
  const registration = await request.post(`${root}/nodes/me/register`, { headers: { Authorization: `Bearer ${node.token}` }, data: {
    session_id: 'e'.repeat(32), profiles: [{ id: 'future-cli', name: 'Future CLI', kind: 'future-tool', settings_schema: [
      { key: 'effort', label: 'Reasoning effort', type: 'choice', default: 'low', options: ['low', 'high'] },
      { key: 'budget', label: 'Iteration budget', type: 'number', default: 3, minimum: 1, maximum: 5 },
      { key: 'respond_to_help', label: 'Respond to teammates', type: 'boolean', default: true },
    ] }],
  } })
  expect(registration.ok()).toBe(true)
  await page.goto('http://127.0.0.1:5173')
  await page.getByLabel('Workspace access token').fill(token)
  await page.getByRole('button', { name: 'Enter your workspace' }).click()
  await page.getByRole('button', { name: project.name, exact: true }).click()
  await expect(page.getByText('Live workspace', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Agents & connections', exact: true }).click()
  await page.getByRole('button', { name: 'Configure Development peer', exact: true }).click()
  await page.getByLabel('Reasoning effort').selectOption('high')
  await page.getByLabel('Iteration budget').fill('5')
  await page.getByLabel('Respond to teammates').uncheck()
  const completed = page.waitForResponse(response => response.url().endsWith(`/agents/${peer.agent.id}/runtime`) && response.request().method() === 'PUT', { timeout: 15000 })
  await page.getByRole('button', { name: 'Save runtime' }).click()
  expect((await completed).status()).toBe(200)
  await expect(page.getByRole('dialog')).toHaveCount(0)
  const snapshot = await request.get(`${root}/projects/${project.id}/snapshot`, { headers }).then(response => response.json())
  expect(snapshot.agents[0].runtime.settings).toEqual({ effort: 'high', budget: 5, respond_to_help: false })
})
