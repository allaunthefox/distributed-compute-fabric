import { test } from '@playwright/test';
test('homarr test', async ({ page }) => {
  test.setTimeout(30000);
  await page.goto('http://100.88.57.96:30093/', { timeout: 10000, waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(5000);
  const title = await page.title();
  console.log('Title:', title);
  const buttons = await page.locator('button').count();
  console.log(`Found ${buttons} buttons`);
  for (const b of await page.locator('button').all()) {
    const text = await b.textContent();
    console.log(`  Button: "${text?.trim().substring(0,30)}" visible=${await b.isVisible()}`);
  }
});
