import { expect, test, type Page, type APIRequestContext } from '@playwright/test'
import { expectNoHorizontalOverflow } from './layout'

const root = 'http://127.0.0.1:8000/api', token = 'browser-test-only-token-not-a-secret'
const headers = { Authorization: `Bearer ${token}` }
async function login(page: Page, name: string) {
  await page.goto('/')
  await page.getByLabel('Workspace access token').fill(token)
  await page.getByRole('button', { name: 'Enter your workspace' }).click()
  await page.getByRole('button', { name, exact: true }).click()
}
async function openExisting(page: Page, agentName: string) {
  await page.getByRole('button', { name: 'Agents & connections', exact: true }).click()
  await page.getByRole('region', { name: `${agentName} agent`, exact: true }).getByRole('button', { name: 'Connect', exact: true }).click()
  return page.getByRole('dialog')
}
async function project(request: APIRequestContext, name: string) {
  return request.post(`${root}/projects`, { headers, data: { name, goal: 'Verify prompt onboarding.', auto_plan: false } }).then(r => r.json())
}

test('generated prompts preserve identity, opt into credentials, choose reachable URLs and remain usable on mobile', async ({ page, request }) => {
  const p = await project(request, `Prompt onboarding ${Date.now()}`)
  await login(page, p.name)
  await page.getByRole('button', { name: 'Connect agent', exact: true }).click()
  await page.getByLabel('Teammate name').fill('Prompt "quoted" peer ü')
  await page.getByRole('button', { name: 'Create connection' }).click()
  const dialog = page.getByRole('dialog'), prompt = dialog.getByLabel('Generated connection prompt')
  const agentToken = await dialog.locator('.copy-box code').first().innerText()
  expect(await prompt.inputValue()).not.toContain(agentToken)
  expect(await prompt.inputValue()).toContain(JSON.stringify('Prompt "quoted" peer ü'))
  expect(await prompt.inputValue()).toContain(`--expected-project '${p.id}'`)
  expect(await prompt.inputValue()).toContain('--command-file agentverse-command.json')
  await expect(dialog.getByText(/A localhost address points/)).toBeVisible()
  await dialog.getByLabel('Workspace URL reachable').fill('https://workspace.example.test/')
  await dialog.getByLabel('Include this teammate’s private token').check()
  expect(await prompt.inputValue()).toContain(`$env:AGENTVERSE_AGENT_TOKEN = '${agentToken}'`)
  await dialog.getByLabel('Agent operating system').selectOption('posix')
  expect(await prompt.inputValue()).toContain(`export AGENTVERSE_AGENT_TOKEN='${agentToken}'`)
  await dialog.getByLabel('Include this teammate’s private token').uncheck()
  await dialog.getByLabel('Connection approach').selectOption('mcp')
  const text = await prompt.inputValue()
  expect(text).toContain('https://workspace.example.test/mcp/')
  expect(text).toContain('register_chat_listener')
  expect(text).toContain('finish_chat_turn')
  expect(text).toContain('cancellation_confirmed=false')
  expect(text).not.toContain(agentToken)
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write'])
  await dialog.getByRole('button', { name: 'Copy connection prompt', exact: true }).click()
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(text)
  await dialog.getByLabel('Workspace URL reachable').fill('https://username:password@workspace.example.test/private')
  await expect(dialog.getByRole('button', { name: 'Copy connection prompt', exact: true })).toBeDisabled()
  await dialog.getByLabel('Workspace URL reachable').fill('https://workspace.example.test')
  await page.setViewportSize({ width: 320, height: 844 })
  await expectNoHorizontalOverflow(page)
})

test('an existing teammate needs no token rotation and a lost test-send response verifies one real worker reply', async ({ page, request }) => {
  const fixture = await request.get('http://127.0.0.1:8200/ready').then(r => r.json())
  await login(page, fixture.project.name)
  const dialog = await openExisting(page, 'ChatAlpha')
  await expect(dialog.getByText('You can copy this prompt without replacing a working token.', { exact: false })).toBeVisible()
  const before = await request.get(`${root}/projects/${fixture.project.id}/tasks`, { headers }).then(r => r.json())
  const sent: string[] = []
  let lost = false
  await page.route(`**/api/projects/${fixture.project.id}/messages`, async route => {
    if (route.request().method() !== 'POST') return route.continue()
    sent.push(route.request().postDataJSON().client_request_id)
    if (!lost) { lost = true; await route.fetch(); return route.abort('failed') }
    return route.continue()
  })
  await dialog.getByRole('button', { name: 'Send chat test', exact: true }).click()
  await expect(dialog.getByRole('status')).toContainText('could not complete')
  await dialog.getByRole('button', { name: 'Send chat test', exact: true }).click()
  await expect(dialog.getByRole('status')).toContainText('Chat check passed', { timeout: 20000 })
  expect(sent).toHaveLength(2)
  expect(sent[0]).toBe(sent[1])
  const rows = await request.get(`${root}/projects/${fixture.project.id}/messages?recipient_id=${fixture.agents[0].id}`, { headers }).then(r => r.json())
  const input = rows.filter((m: { client_request_id: string }) => m.client_request_id === sent[0])
  expect(input).toHaveLength(1)
  expect(rows.filter((m: { reply_to_id: string }) => m.reply_to_id === input[0].id)).toHaveLength(1)
  expect(await request.get(`${root}/projects/${fixture.project.id}/tasks`, { headers }).then(r => r.json())).toEqual(before)
})

test('presence alone cannot pass a chat check and stopping the check preserves its durable message', async ({ page, request }) => {
  const p = await project(request, `Presence check ${Date.now()}`)
  const peer = await request.post(`${root}/projects/${p.id}/agents`, { headers, data: { name: 'Presence peer', kind: 'custom' } }).then(r => r.json())
  const auth = { Authorization: `Bearer ${peer.token}` }
  await request.post(`${root}/agents/announce`, { headers: auth, data: { connection: 'http', protocol_version: 1 } })
  await login(page, p.name)
  const dialog = await openExisting(page, peer.agent.name)
  await dialog.getByRole('button', { name: 'Send chat test', exact: true }).click()
  await expect(dialog.getByRole('status')).toContainText('Waiting for a persistent chat listener')
  await dialog.getByRole('button', { name: 'Stop waiting', exact: true }).click()
  await expect(dialog.getByRole('status')).toContainText('test remains in the owner DM')
  await dialog.getByRole('button', { name: 'Send chat test', exact: true }).click()
  await expect(dialog.getByRole('status')).toContainText('Waiting for a persistent chat listener')
  const session = 'c'.repeat(32)
  await request.post(`${root}/agents/chat/register`, { headers: auth, data: { session_id: session } })
  const turn = await request.post(`${root}/agents/chat/claim`, { headers: auth, data: { session_id: session } }).then(r => r.json())
  await request.post(`${root}/agents/chat/${turn.message.id}/finish`, { headers: auth, data: { session_id: session, claim_token: turn.claim_token, result: { reply: 'A canned hello without your phrase' } } })
  await expect(dialog.getByRole('status')).toContainText('did not contain the requested phrase')
  const rows = await request.get(`${root}/projects/${p.id}/messages`, { headers }).then(r => r.json())
  expect(rows.filter((m: { sender_id: string }) => m.sender_id === 'human')).toHaveLength(1)
})
