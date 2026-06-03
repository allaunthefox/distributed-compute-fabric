import { test } from '@playwright/test';
test('login v2', async ({ page }) => {
  test.setTimeout(30000);
  await page.goto('http://100.88.57.96:30108/', { timeout: 10000 });
  await page.waitForTimeout(5000);
  console.log('URL:', page.url());
  console.log('Title:', await page.title());
  
  // Check for login form or dashboard
  const buttons = await page.locator('button, a[role="button"]').all();
  for (const b of buttons) {
    const t = await b.textContent();
    if (await b.isVisible() && t?.trim()) console.log(`  "${t.trim()}"`);
  }
});
