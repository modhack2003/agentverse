import { expect, type Page } from '@playwright/test'

export async function expectNoHorizontalOverflow(page: Page) {
  await expect.poll(() => page.evaluate(() => {
    const viewport = innerWidth, width = document.documentElement.scrollWidth
    const offenders = width > viewport ? [...document.querySelectorAll<HTMLElement>('body *')].filter(el => {
      const rect = el.getBoundingClientRect()
      return getComputedStyle(el).position !== 'fixed' && rect.width > 0 && (rect.right > viewport + 1 || rect.left < -1)
    }).slice(0, 12).map(el => ({ tag: el.tagName, class: el.className, right: Math.round(el.getBoundingClientRect().right) })) : []
    return { viewport, width, offenders }
  }), { message: 'Layout should settle within the viewport; failure includes measured widths and overflowing elements.' }).toMatchObject({ width: expect.any(Number), offenders: [] })
  // The width assertion catches root overflow even when the offending element is fixed or clipped.
  await expect.poll(() => page.evaluate(() => ({ viewport: innerWidth, width: document.documentElement.scrollWidth, overflow: Math.max(0, document.documentElement.scrollWidth - innerWidth) }))).toMatchObject({ overflow: 0 })
}
