import { test } from '@playwright/test';
test('Homarr check integrations', async ({ page }) => {
  test.setTimeout(30000);
  await page.goto('http://100.88.57.96:30108/manage/integrations', { timeout: 10000, waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(5000);
  console.log('URL:', page.url());
  
  // Check for visible elements
  const text = await page.locator('h1,h2,h3,p,label,span,button').all();
  for (const el of text) {
    const t = (await el.textContent())?.trim();
    if (t && t.length > 1 && t.length < 100) console.log(`  "${t}"`);
  }
  
  await page.screenshot({ path: '/tmp/homarr-integrations.png' });
});
