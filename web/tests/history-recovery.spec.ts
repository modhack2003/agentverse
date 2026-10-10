import { expect, test } from '@playwright/test'

const root = 'http://127.0.0.1:8000/api'
const token = 'browser-test-only-token-not-a-secret'
const headers = { Authorization: `Bearer ${token}` }

for (const initialCount of [0, 5, 105]) {
  test(`conversation recovers a multi-page reconnect burst after ${initialCount} messages`, async ({ page, request }) => {
    test.setTimeout(90000)
    const project = await request.post(`${root}/projects`, { headers, data: {
      name: `History recovery ${initialCount}`, goal: 'Retain every message across reconnects', auto_plan: false,
    } }).then(response => response.json())
    for (let i = 0; i < initialCount; i++) {
      expect((await request.post(`${root}/projects/${project.id}/messages`, { headers, data: { content: `Before burst ${i}` } })).status()).toBe(201)
    }
    await page.routeWebSocket('**/api/live*', socket => socket.close())
    await page.goto('/')
    await page.getByLabel('Workspace access token').fill(token)
    await page.getByRole('button', { name: 'Enter your workspace' }).click()
    await page.getByRole('button', { name: project.name, exact: true }).click()
    await page.getByRole('button', { name: 'Team conversations', exact: true }).click()
    if (initialCount > 100) await page.getByRole('button', { name: 'Load older messages', exact: true }).click()
    if (initialCount) await expect(page.locator('.message-body').getByText('Before burst 0', { exact: true })).toBeVisible()
    else await expect(page.getByRole('heading', { name: 'Start the conversation', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Load older messages', exact: true })).toHaveCount(0)

    // Hold delivery during the burst, so it cannot accidentally become 205 tiny refreshes.
    let gateOpen = true
    let resume!: () => void
    let burstDone = Promise.resolve()
    await page.route(`**/api/projects/${project.id}/messages?*`, async route => {
      if (!gateOpen) await burstDone
      await route.continue()
    })
    gateOpen = false
    burstDone = new Promise<void>(resolve => { resume = resolve })
    try {
      for (let i = 0; i < 205; i++) {
        expect((await request.post(`${root}/projects/${project.id}/messages`, { headers, data: { content: `During burst ${i}` } })).status()).toBe(201)
      }
    } finally { gateOpen = true; resume() }
    await expect(page.locator('.message-body').getByText('During burst 204', { exact: true })).toBeVisible({ timeout: 25000 })
    if (!initialCount) {
      await page.getByRole('button', { name: 'Load older messages', exact: true }).click()
      await page.getByRole('button', { name: 'Load older messages', exact: true }).click()
    }
    await expect(page.locator('.message')).toHaveCount(initialCount + 205)
    for (const index of [0, 4, 5, 104, 105, 204]) {
      await expect(page.locator('.message-body').getByText(`During burst ${index}`, { exact: true })).toHaveCount(1)
    }
    await expect(page.getByRole('button', { name: 'Load older messages', exact: true })).toHaveCount(0)
  })
}
