import { expect, test } from '@playwright/test'

const token = 'browser-test-only-token-not-a-secret'
const headers = { Authorization: `Bearer ${token}` }

test('human conversations invoke workers, dispatch one plan, execute and independently review work, and recover failed replies', async ({ page, request }) => {
  test.setTimeout(60000)
  const fixture = await request.get('http://127.0.0.1:8200/ready').then(r => r.json())
  await page.goto('/')
  await page.getByLabel('Workspace access token').fill(token)
  await page.getByRole('button', { name: 'Enter your workspace' }).click()
  await page.getByRole('button', { name: fixture.project.name, exact: true }).click()
  await page.getByRole('button', { name: 'Team conversations', exact: true }).click()
  const send = async (content: string) => {
    await page.getByLabel('Message', { exact: true }).fill(content)
    await page.getByRole('button', { name: 'Send message' }).click()
  }
  await send('hi')
  await expect(page.getByText('Hello! I can talk with you.', { exact: true })).toHaveCount(2)
  await expect(page.getByText('ChatAlpha · Replied', { exact: true })).toBeVisible()
  await expect(page.getByText('ChatBeta · Replied', { exact: true })).toBeVisible()
  await send('can we talk?')
  await expect(page.getByText('Hello! I can talk with you.', { exact: true })).toHaveCount(4)
  await expect.poll(async () => request.get(`http://127.0.0.1:8000/api/projects/${fixture.project.id}/tasks`, { headers }).then(r => r.json())).toEqual([])
  await send('Build feature.txt')
  await expect.poll(async () => {
    const snapshot = await request.get(`http://127.0.0.1:8000/api/projects/${fixture.project.id}/snapshot`, { headers }).then(r => r.json())
    return snapshot.tasks.length === 2 && snapshot.tasks.every((t: { status: string }) => t.status === 'done') && snapshot.reviews.length === 1
  }, { timeout: 30000 }).toBe(true)
  await expect(page.getByText('Feature committed and ready for independent review.', { exact: true })).toBeVisible()
  await expect(page.getByText('Independent reviewer verified feature.txt.', { exact: true })).toBeVisible()
  await send('@ChatAlpha fail once')
  await expect(page.getByRole('button', { name: 'Retry reply from ChatAlpha', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Retry reply from ChatAlpha', exact: true }).click()
  await expect(page.getByText('The retry recovered successfully.', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Agents & connections', exact: true }).click()
  await expect(page.getByText('Chat reply verified', { exact: true })).toHaveCount(2)
})

test('an HTTP-only peer is not shown as a verified chat listener, and explicit tasks are created from the composer', async ({ page, request }) => {
  const project = await request.post('http://127.0.0.1:8000/api/projects', { headers, data: { name: 'Presence is not readiness', goal: 'Honest conversation status', auto_plan: false } }).then(r => r.json())
  const peer = await request.post(`http://127.0.0.1:8000/api/projects/${project.id}/agents`, { headers, data: { name: 'Heartbeat only', kind: 'cline' } }).then(r => r.json())
  await request.post('http://127.0.0.1:8000/api/agents/announce', { headers: { Authorization: `Bearer ${peer.token}` }, data: { connection: 'http', protocol_version: 1 } })
  await page.goto('/')
  await page.getByLabel('Workspace access token').fill(token)
  await page.getByRole('button', { name: 'Enter your workspace' }).click()
  await page.getByRole('button', { name: project.name, exact: true }).click()
  await page.getByRole('button', { name: 'Agents & connections', exact: true }).click()
  await expect(page.getByText('Chat listener not running', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Team conversations', exact: true }).click()
  await page.getByLabel('Message', { exact: true }).fill('hi')
  await page.getByRole('button', { name: 'Send message' }).click()
  await expect(page.getByText('Heartbeat only · Waiting for a chat listener', { exact: true })).toBeVisible()
  await page.getByLabel('Message action').selectOption('task')
  await page.getByLabel('Message', { exact: true }).fill('Build the requested homepage')
  await page.getByRole('button', { name: 'Send message' }).click()
  await expect(page.getByText('Linked to Build the requested homepage', { exact: false })).toBeVisible()
  const tasks = await request.get(`http://127.0.0.1:8000/api/projects/${project.id}/tasks`, { headers }).then(r => r.json())
  expect(tasks).toHaveLength(1)
  expect(tasks[0].kind).toBe('planning')
})

test('a lost send response can be retried once and typing during a send preserves the new draft', async ({ page, request }) => {
  const project = await request.post('http://127.0.0.1:8000/api/projects', { headers, data: { name: 'Conversation send recovery', goal: 'Preserve drafts and avoid duplicate work requests', auto_plan: false } }).then(r => r.json())
  await page.goto('/')
  await page.getByLabel('Workspace access token').fill(token)
  await page.getByRole('button', { name: 'Enter your workspace' }).click()
  await page.getByRole('button', { name: project.name, exact: true }).click()
  await page.getByRole('button', { name: 'Team conversations', exact: true }).click()
  let lost = false
  await page.getByLabel('Message action').selectOption('task')
  await page.route(`**/api/projects/${project.id}/messages`, async route => {
    if (route.request().method() !== 'POST') return route.continue()
    const response = await route.fetch()
    if (!lost) { lost = true; await route.abort('failed') }
    else await route.fulfill({ response })
  })
  await page.getByLabel('Message', { exact: true }).fill('This message must only be saved once')
  await page.getByRole('button', { name: 'Send message' }).click()
  await expect(page.locator('.chat-compose [role="alert"]')).toBeVisible()
  await expect(page.getByLabel('Message', { exact: true })).toHaveValue('This message must only be saved once')
  await page.getByRole('button', { name: 'Send message' }).click()
  await expect(page.getByLabel('Message', { exact: true })).toHaveValue('')
  await page.unroute(`**/api/projects/${project.id}/messages`)
  const tasks = await request.get(`http://127.0.0.1:8000/api/projects/${project.id}/tasks`, { headers }).then(r => r.json())
  expect(tasks).toHaveLength(1)
  await page.getByLabel('Message action').selectOption('chat')
  let release!: () => void
  const held = new Promise<void>(resolve => { release = resolve })
  await page.route(`**/api/projects/${project.id}/messages`, async route => {
    if (route.request().method() !== 'POST') return route.continue()
    const response = await route.fetch()
    await held
    await route.fulfill({ response })
  })
  await page.getByLabel('Message', { exact: true }).fill('The previous draft being sent')
  await page.getByRole('button', { name: 'Send message' }).click()
  await page.getByLabel('Message', { exact: true }).fill('The next unsent draft')
  release()
  await expect(page.getByRole('button', { name: 'Send message' })).toBeEnabled()
  await expect(page.getByLabel('Message', { exact: true })).toHaveValue('The next unsent draft')
  const messages = await request.get(`http://127.0.0.1:8000/api/projects/${project.id}/messages`, { headers }).then(r => r.json())
  expect(messages.map((m: { content: string }) => m.content)).toEqual(['This message must only be saved once', 'The previous draft being sent'])
})
