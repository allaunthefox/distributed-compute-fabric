import { test } from '@playwright/test';
test('homarr step 2', async ({ page }) => {
  test.setTimeout(30000);
  await page.goto('http://100.88.57.96:30093/', { timeout: 10000, waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3000);
  await page.locator('button:has-text("Start update process"):visible').first().click({ force: true, noWaitAfter: true });
  await page.waitForTimeout(5000);
  console.log('URL:', page.url());
  
  // Dump all buttons
  for (const b of await page.locator('button').all()) {
    const text = await b.textContent();
    if (await b.isVisible()) console.log(`  Visible: "${text?.trim().substring(0,40)}"`);
  }
});
