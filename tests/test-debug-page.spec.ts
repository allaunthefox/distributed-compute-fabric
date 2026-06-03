import { test } from '@playwright/test';
test('debug page', async ({ page }) => {
  test.setTimeout(15000);
  await page.goto('http://100.88.57.96:30091/web/', { timeout: 10000, waitUntil: 'domcontentloaded' });
  await page.screenshot({ path: '/tmp/jf-debug.png' });
  const title = await page.title();
  console.log('Title:', title);
  const html = await page.content();
  console.log('Has login:', html.includes('txtUsername'));
  console.log('Has button:', html.includes('button-submit'));
});
