import { test } from '@playwright/test';
test('login check', async ({ page }) => {
  test.setTimeout(20000);
  await page.goto('http://100.88.57.96:30108/auth/login', { timeout: 10000, waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3000);
  
  console.log('Page loaded');
  const url = page.url();
  console.log('URL:', url);
  
  // Check for error messages
  const errorText = await page.locator('[class*="error"], [class*="alert"], [role="alert"]').all();
  for (const e of errorText) {
    const t = await e.textContent();
    if (t?.trim()) console.log('Error:', t.trim());
  }
  
  console.log('Login page check done');
});
