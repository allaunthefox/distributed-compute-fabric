import { test } from '@playwright/test';
import fs from 'fs';

test('Get Homarr cookie', async ({ page }) => {
  test.setTimeout(30000);
  await page.goto('http://100.88.57.96:30108/auth/login', { timeout: 10000 });
  await page.waitForTimeout(3000);
  
  await page.locator('input[name="username"]').fill('allaun');
  await page.locator('input[type="password"]').first().fill('TYW82QNB!k0y!pXc');
  await page.locator('button:has-text("Login"):visible').first().click();
  await page.waitForTimeout(5000);
  
  // Get cookies
  const cookies = await page.context().cookies();
  for (const c of cookies) {
    if (c.name.includes('sid') || c.name.includes('token') || c.name.includes('session')) {
      console.log(`${c.name}=${c.value}`);
    }
  }
  console.log('All cookies:', cookies.map(c => c.name).join(', '));
});
