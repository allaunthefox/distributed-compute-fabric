import { test } from '@playwright/test';
test('Homarr setup', async ({ page }) => {
  test.setTimeout(60000);
  await page.goto('http://100.88.57.96:30093/', { timeout: 10000, waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3000);
  
  // Click buttons with force (don't wait for navigation)
  for (const text of ["Start update process", "Next", "Next", "Next", "Finish"]) {
    const btn = page.locator(`button:has-text("${text}"):visible`).first();
    if (await btn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await btn.click({ force: true, timeout: 5000 });
      await page.waitForTimeout(3000);
      console.log(`Clicked "${text}"`);
    } else {
      console.log(`Button "${text}" not found at step`);
      break;
    }
  }
  
  await page.screenshot({ path: '/tmp/homarr-done.png' });
  console.log('Done at:', page.url());
});
