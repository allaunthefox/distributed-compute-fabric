import { test } from '@playwright/test';
test('Jellyfin libraries', async ({ page }) => {
  test.setTimeout(60000);
  
  // Login
  await page.goto('http://100.88.57.96:30091/web/', { timeout: 10000 });
  await page.waitForTimeout(2000);
  await page.locator('#txtUsername').fill('admin');
  await page.locator('#txtPassword').fill('jellyfin-admin');
  await page.locator('.button-submit').first().click();
  await page.waitForTimeout(3000);
  
  // Navigate to library page via hash
  await page.evaluate(() => { window.location.hash = '#/dashboard/library'; });
  await page.waitForTimeout(5000);
  console.log('URL:', page.url());
  
  // Take screenshot for debug
  await page.screenshot({ path: '/tmp/jf-lib-page.png' });
  
  // Check for "Add Media Library" button
  const buttons = await page.locator('button').all();
  for (const b of buttons) {
    const text = await b.textContent();
    if (text?.includes('Add') || text?.includes('Media')) {
      console.log(`Button: "${text}" visible=${await b.isVisible()}`);
    }
  }
  console.log('Done');
});
