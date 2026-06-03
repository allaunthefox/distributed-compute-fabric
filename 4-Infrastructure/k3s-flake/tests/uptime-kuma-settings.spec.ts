import { test, expect } from '@playwright/test';

test('Check Uptime Kuma settings', async ({ browser }) => {
  const context = await browser.newContext({ storageState: 'auth-state.json' });
  const page = await context.newPage();

  console.log('Navigating to Uptime Kuma...');
  await page.goto('https://uptime.researchstack.info/dashboard');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(4000);

  // If we see login inputs
  const usernameInput = page.locator('input[type="text"]');
  const passwordInput = page.locator('input[type="password"]');
  
  if (await usernameInput.isVisible()) {
    console.log('Logging in with admin...');
    await usernameInput.fill('admin');
    await passwordInput.fill('RY03KhsFez73K5va2uUb');
    await page.locator('button[type="submit"]').click();
    await page.waitForTimeout(6000);
  }

  console.log('Current URL:', page.url());
  await page.screenshot({ path: 'uptime-kuma-logged-in.png' });

  // Let's click the user icon/menu or navigate to /settings
  // Wait, let's look at the DOM to see how to go to settings.
  const textContent = await page.evaluate(() => document.body.innerText);
  console.log('Uptime Kuma text:', textContent.slice(0, 1000));

  await context.close();
});
