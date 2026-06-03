import { test } from '@playwright/test';
test('check', async ({ page }) => {
  test.setTimeout(10000);
  await page.goto('http://100.88.57.96:30108/', { timeout: 10000, waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3000);
  console.log('URL:', page.url());
  console.log('Title:', await page.title());
  const btns = await page.locator('button').all();
  for (const b of btns) {
    const t = await b.textContent();
    if (t?.trim()) console.log(`  "${t.trim().substring(0,40)}"`);
  }
});
