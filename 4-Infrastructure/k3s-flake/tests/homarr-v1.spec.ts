import { test } from '@playwright/test';
test('Check Homarr v1', async ({ page }) => {
  test.setTimeout(30000);
  await page.goto('http://100.88.57.96:30108/', { timeout: 10000, waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(5000);
  console.log('Title:', await page.title());
  
  // Check for buttons
  const buttons = await page.locator('button, a[role="button"]').all();
  for (const b of buttons) {
    const text = await b.textContent();
    if (await b.isVisible()) console.log(`  "${text?.trim()}"`);
  }
  
  // Check for OIDC
  const hasOidc = await page.locator('text=Authentik').count();
  console.log('Authentik button:', hasOidc > 0);
  await page.screenshot({ path: '/tmp/homarr-v1.png' });
});
