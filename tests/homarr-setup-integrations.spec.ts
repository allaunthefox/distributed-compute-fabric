import { test } from '@playwright/test';
test('Homarr setup integrations', async ({ page }) => {
  test.setTimeout(60000);
  
  // Login
  await page.goto('http://100.88.57.96:30108/auth/login', { timeout: 10000, waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3000);
  
  // Fill credentials
  await page.locator('input[name="username"], input[type="text"]').first().fill('allaun');
  await page.locator('input[type="password"]').first().fill('TYW82QNB!k0y!pXc');
  await page.locator('button:has-text("Login"):visible').first().click();
  await page.waitForTimeout(5000);
  
  // Now go to integrations
  await page.goto('http://100.88.57.96:30108/manage/integrations', { timeout: 10000, waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(5000);
  console.log('URL:', page.url());
  
  // Check available integrations
  const items = await page.locator('button, a, [role="button"], [class*="card"], [class*="item"]').all();
  console.log(`Found ${items.length} clickable items`);
  for (const el of items) {
    if (await el.isVisible()) {
      const t = (await el.textContent())?.trim();
      if (t && t.length < 60) console.log(`  "${t}"`);
    }
  }
  
  await page.screenshot({ path: '/tmp/homarr-int.png' });
});
