import { test } from '@playwright/test';
test('quick login', async ({ page }) => {
  test.setTimeout(20000);
  await page.goto('http://100.88.57.96:30108/auth/login', { timeout: 10000, waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3000);
  
  await page.locator('input[name="username"]').fill('allaun');
  await page.locator('input[type="password"]').first().fill('TYW82QNB!k0y!pXc');
  await page.locator('button[type="submit"]').first().click({ force: true, noWaitAfter: true, timeout: 3000 });
  await page.waitForTimeout(5000);
  
  console.log('URL:', page.url());
  const c = await page.context().cookies();
  c.forEach(x => console.log(x.name + '=' + x.value.substring(0,30)));
});
