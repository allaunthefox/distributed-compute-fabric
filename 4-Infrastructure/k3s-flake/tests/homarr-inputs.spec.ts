import { test } from '@playwright/test';
test('homarr inputs', async ({ page }) => {
  test.setTimeout(20000);
  await page.goto('http://100.88.57.96:30093/', { timeout: 10000, waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(4000);
  
  // Check for all interactive elements
  for (const type of ['input', 'select', 'textarea', '[role="button"]', '[role="checkbox"]', '[type="checkbox"]']) {
    const els = page.locator(type);
    const count = await els.count();
    if (count > 0) console.log(`Found ${count} ${type}`);
  }
  
  // Check what's inside forms
  const forms = page.locator('form').count();
  console.log(`Forms: ${await forms}`);
});
