import { test } from '@playwright/test';
test('homarr2', async ({ page }) => {
  test.setTimeout(20000);
  console.log('Going...');
  await page.goto('http://100.88.57.96:30093/', { timeout: 10000, waitUntil: 'domcontentloaded' });
  console.log('Loaded');
  await page.waitForTimeout(2000);
  console.log('Finding button...');
  const btn = page.locator('button:has-text("Start update process"):visible').first();
  const visible = await btn.isVisible({ timeout: 3000 }).catch(() => false);
  console.log('Visible:', visible);
  if (visible) {
    console.log('Clicking...');
    await btn.click();
    await page.waitForTimeout(3000);
    console.log('Clicked, URL:', page.url());
  }
});
