import { test } from '@playwright/test';
test('login wait', async ({ page }) => {
  test.setTimeout(30000);
  await page.goto('http://100.88.57.96:30091/web/', { timeout: 10000 });
  // Wait for txtUsername to appear (JS rendered)
  await page.locator('#txtUsername').waitFor({ state: 'visible', timeout: 15000 });
  await page.locator('#txtUsername').fill('admin');
  await page.locator('#txtPassword').fill('jellyfin-admin');
  await page.locator('.button-submit').first().click();
  await page.waitForTimeout(5000);
  console.log('URL:', page.url());
});
