import { test } from '@playwright/test';
test('Homarr final', async ({ page }) => {
  test.setTimeout(60000);
  await page.goto('http://100.88.57.96:30093/', { timeout: 10000, waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(4000);
  
  for (const text of ["Start update process", "Next", "Next", "Next", "Finish"]) {
    const btn = page.locator(`button:has-text("${text}"):visible`).first();
    if (await btn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await btn.click({ force: true, noWaitAfter: true });
      await page.waitForTimeout(3000);
      console.log(`Clicked "${text}"`);
    } else {
      console.log(`Button "${text}" not found`);
      break;
    }
  }
  
  await page.waitForTimeout(2000);
  console.log('Final URL:', page.url());
  await page.screenshot({ path: '/tmp/homarr-final.png' });
});
