import { test } from '@playwright/test';
test('login test', async ({ page }) => {
  test.setTimeout(20000);
  await page.goto('http://100.88.57.96:30091/web/', { timeout: 10000 });
  await page.waitForTimeout(2000);
  console.log('Page loaded');
  await page.locator('#txtUsername').fill('admin');
  console.log('Username filled');
  await page.locator('#txtPassword').fill('jellyfin-admin');
  console.log('Password filled');
  await page.locator('.button-submit').first().click();
  await page.waitForTimeout(3000);
  console.log('Logged in, URL:', page.url());
});
