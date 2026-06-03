import { test } from '@playwright/test';
test('try login', async ({ page }) => {
  test.setTimeout(20000);
  await page.goto('http://100.88.57.96:30108/auth/login', { timeout: 10000 });
  await page.waitForTimeout(3000);
  
  // Try to log in
  await page.locator('input[name="username"]').fill('allaun');
  await page.locator('input[type="password"]').first().fill('TYW82QNB!k0y!pXc');
  await page.locator('button[type="submit"]').first().click({ force: true, noWaitAfter: true });
  await page.waitForTimeout(5000);
  
  console.log('After login:', page.url());
  
  const body = await page.textContent('body');
  if (body?.includes('error') || body?.includes('invalid')) {
    console.log('Login error detected');
  }
});
