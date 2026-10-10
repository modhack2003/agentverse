import { expect, test } from '@playwright/test'

const token = 'browser-test-only-token-not-a-secret'
const headers = { Authorization: `Bearer ${token}` }

test('owner creates a project, connects a teammate, chats, manages tasks and memory', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', e => errors.push(e.message))
  await page.goto('/')
  await page.getByLabel('Workspace access token').fill(token)
  await page.getByRole('button', { name: 'Enter your workspace' }).click()
  await page.getByRole('button', { name: 'Create project', exact: true }).click()
  await page.getByLabel('Project name', { exact: true }).fill('Orbital workspace')
  await page.getByLabel('The goal', { exact: true }).fill('Build a beautiful launch site for our next big idea.')
  await page.getByLabel('Git repository URL').fill('https://github.com/example/orbital')
  await page.getByRole('dialog').getByRole('button', { name: 'Create project', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Your team, in sync.' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Break the project goal into a team plan', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Connect agent', exact: true }).click()
  await page.getByLabel('Teammate name').fill('Atlas')
  await page.getByLabel('Strengths').fill('frontend, review')
  await page.getByRole('button', { name: 'Create connection' }).click()
  await expect(page.getByRole('heading', { name: 'Atlas is ready to connect.' })).toBeVisible()
  await expect(page.locator('.copy-box code')).toContainText('ac_')
  await page.getByRole('button', { name: 'I saved the token' }).click()
  await page.getByLabel('Message', { exact: true }).fill('Welcome, Atlas. Let’s build something great together.')
  await page.getByRole('button', { name: 'Send message' }).click()
  await expect(page.locator('.message-body')).toContainText('Welcome, Atlas.')
  await page.getByRole('button', { name: 'New task', exact: true }).click()
  await page.getByLabel('Task title').fill('Polish the launch experience')
  await page.getByLabel('Description & acceptance criteria').fill('Responsive layout, clear navigation, and thoughtful interactions.')
  await page.getByRole('button', { name: 'Add task', exact: true }).click()
  await page.getByRole('button', { name: 'Task board', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Polish the launch experience' })).toBeVisible()
  await page.getByRole('button', { name: 'Shared memory', exact: true }).click()
  await page.getByRole('button', { name: 'Add memory' }).click()
  await page.getByLabel('Title', { exact: true }).fill('Design direction')
  await page.getByLabel('Shared knowledge').fill('Use a restrained dark palette and a warm green accent.')
  await page.getByLabel('Tags', { exact: true }).fill('design, decision')
  await page.getByRole('button', { name: 'Save memory' }).click()
  await expect(page.getByRole('heading', { name: 'Design direction' })).toBeVisible()
  await page.getByRole('button', { name: 'Design direction' }).click()
  await page.getByLabel('Shared knowledge').fill('Dark palette, warm green accent, and accessible focus states.')
  await page.getByRole('button', { name: 'Save memory' }).click()
  await expect(page.locator('.memory-top')).toContainText('v2')
  await page.getByLabel('Search memory').fill('does-not-exist')
  await expect(page.getByRole('heading', { name: 'No matching memories' })).toBeVisible()
  await page.getByLabel('Search memory').fill('accessible')
  await expect(page.getByRole('heading', { name: 'Design direction' })).toBeVisible()
  await page.getByRole('button', { name: 'Overview', exact: true }).click()
  await page.getByRole('button', { name: 'Pause', exact: true }).click()
  await expect(page.locator('.pause-banner')).toBeVisible()
  await page.getByRole('button', { name: 'Resume', exact: true }).click()
  await expect(page.locator('.pause-banner')).not.toBeVisible()
  expect(errors).toEqual([])
})

test('dashboard live updates, task details, DMs, and mobile navigation', async ({ page, request }) => {
  const p = await request.post('http://127.0.0.1:8000/api/projects', { headers, data: {
    name: 'Launchpad', goal: 'Build a thoughtful developer platform. Make the first five minutes feel effortless.',
    repo_url: 'github.com/team/launchpad', auto_plan: false,
  } }).then(r => r.json())
  const peers: { agent: { id: string; name: string }; token: string }[] = []
  for (const [name, kind, capabilities] of [
    ['OpenCode', 'opencode', ['architecture', 'backend']], ['Cline', 'cline', ['frontend', 'design']],
    ['Omnirush', 'omnirush', ['testing', 'review']], ['Agent Zero', 'agentzero', ['research', 'docs']],
  ] as const) {
    const peer = await request.post(`http://127.0.0.1:8000/api/projects/${p.id}/agents`, { headers, data: { name, kind, capabilities } }).then(r => r.json())
    peers.push(peer)
    await request.post('http://127.0.0.1:8000/api/agents/heartbeat', { headers: { Authorization: `Bearer ${peer.token}` }, data: { status: kind === 'opencode' || kind === 'cline' ? 'working' : 'idle' } })
  }
  const data = [
    ['Set up the application foundation', 'API structure, project conventions, and a clean development workflow.', 'high', 'done'],
    ['Design the onboarding flow', 'A welcoming first-run experience with clear next steps for every user.', 'high', 'in_progress'],
    ['Connect the project API', 'Typed endpoints and real-time updates across the workspace.', 'medium', 'in_progress'],
    ['Write the getting-started guide', 'A simple path from installation to the first successful project.', 'medium', 'backlog'],
    ['Review the shared component library', 'Verify keyboard interactions, focus states, and responsive layouts.', 'medium', 'review'],
  ]
  for (let index = 0; index < data.length; index++) {
    const [title, description, priority, status] = data[index]
    const t = await request.post(`http://127.0.0.1:8000/api/projects/${p.id}/tasks`, { headers, data: { title, description, priority } }).then(r => r.json())
    const owner = peers[index === 4 ? 3 : index === 2 ? 1 : 0]
    const h = { Authorization: `Bearer ${owner.token}` }
    if (status !== 'backlog') await request.post(`http://127.0.0.1:8000/api/projects/${p.id}/tasks/${t.id}/claim`, { headers: h })
    if (status === 'done' || status === 'review') {
      await request.post(`http://127.0.0.1:8000/api/projects/${p.id}/tasks/${t.id}/submit`, { headers: h, data: { summary: 'Implementation complete. Relevant checks pass; ready for independent review.', branch: `agentcommons/task-${index}`, commit_sha: 'a'.repeat(40), diff: '+export function collaboration() { return "together" }' } })
    }
    if (status === 'done') {
      await request.post(`http://127.0.0.1:8000/api/projects/${p.id}/tasks/${t.id}/review-claim`, { headers: { Authorization: `Bearer ${peers[2].token}` } })
      await request.post(`http://127.0.0.1:8000/api/projects/${p.id}/tasks/${t.id}/review`, { headers: { Authorization: `Bearer ${peers[2].token}` }, data: { decision: 'approve', comment: 'The foundation looks solid. Checked the API contracts and ran the test suite.' } })
    }
  }
  for (const [index, content] of [
    [0, 'The foundation is ready. I’ve saved the API conventions in shared memory so we’re all working from the same context.'],
    [1, 'Nice! I’m taking the onboarding experience. Keeping it simple, with a clear path to the first project.'],
    [2, 'I can review the components when you’re ready. I’ll focus on keyboard navigation and smaller screens.'],
    [3, 'I’ll turn our setup notes into a getting-started guide. Let me know if there are any rough edges worth documenting.'],
  ] as const) await request.post(`http://127.0.0.1:8000/api/projects/${p.id}/messages`, { headers: { Authorization: `Bearer ${peers[index].token}` }, data: { content } })
  await page.goto('/')
  await page.getByLabel('Workspace access token').fill(token)
  await page.getByRole('button', { name: 'Enter your workspace' }).click()
  await expect(page.getByRole('heading', { name: 'Your team, in sync.' })).toBeVisible()
  await expect(page.getByText('Live workspace', { exact: true })).toBeVisible()
  if (process.env.UPDATE_SCREENSHOTS) await page.screenshot({ path: '../docs/assets/dashboard.png', fullPage: true })
  await request.post(`http://127.0.0.1:8000/api/projects/${p.id}/messages`, { headers: { Authorization: `Bearer ${peers[0].token}` }, data: { content: 'A live update from a remote teammate.' } })
  await expect(page.locator('.chat-messages').getByText('A live update from a remote teammate.', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: /Review the shared component library/ }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.getByText('Inspect submitted diff').click()
  await expect(page.getByRole('dialog').locator('pre')).toContainText('collaboration')
  await page.getByRole('button', { name: 'Close dialog' }).click()
  await page.getByRole('button', { name: 'Team conversations', exact: true }).click()
  await page.getByLabel('Conversation').selectOption(peers[0].agent.id)
  await page.getByLabel('Message', { exact: true }).fill('A private note for OpenCode.')
  await page.getByRole('button', { name: 'Send message' }).click()
  await expect(page.locator('.message-body')).toContainText('A private note for OpenCode.')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: 'Open navigation' }).click()
  await page.getByRole('button', { name: 'Task board', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Task board' })).toBeVisible()
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})
