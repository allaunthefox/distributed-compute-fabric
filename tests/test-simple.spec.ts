import { test } from '@playwright/test';
test('simple', async ({ page }) => {
  test.setTimeout(30000);
  console.log('Going to page...');
  await page.goto('http://100.88.57.96:30091/web/', { timeout: 15000 });
  console.log('Page loaded:', await page.title());
});
