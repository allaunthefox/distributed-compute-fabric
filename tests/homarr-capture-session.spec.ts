import { test } from '@playwright/test';
import fs from 'fs';

test('capture session', async ({ page }) => {
  test.setTimeout(20000);
  await page.goto('http://100.88.57.96:30108/auth/login', { timeout: 10000 });
  await page.waitForTimeout(3000);
  
  await page.locator('input[name="username"]').fill('allaun');
  await page.locator('input[type="password"]').first().fill('TYW82QNB!k0y!pXc');
  await page.locator('button[type="submit"]').first().click({ force: true });
  await page.waitForTimeout(5000);
  
  console.log('URL:', page.url());
  const cookies = await page.context().cookies();
  for (const c of cookies) {
    console.log(`${c.name}=${c.value}`);
  }
});
