import { test } from '@playwright/test';
test('login', async ({ page }) => {
  test.setTimeout(20000);
  await page.goto('http://100.88.57.96:30108/auth/login', { timeout: 10000 });
  await page.waitForTimeout(3000);
  
  await page.locator('input[name="username"]').fill('allaun');
  await page.locator('input[type="password"]').first().fill('TYW82QNB!k0y!pXc');
  await page.locator('button[type="submit"]').first().click();
  await page.waitForTimeout(5000);
  
  console.log('After login URL:', page.url());
  
  const cookies = await page.context().cookies();
  for (const c of cookies) {
    if (c.name.includes('sid') || c.name.includes('token')) {
      console.log(`${c.name}=${c.value}`);
    }
  }
});
