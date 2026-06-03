import { test, expect } from '@playwright/test';

test('Query Authentik Outposts API', async ({ browser }) => {
  const context = await browser.newContext();
  const page = await context.newPage();

  console.log('Navigating to Authentik admin home...');
  await page.goto('https://auth.researchstack.info/if/admin/#/home');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(4000);

  // Login
  const loginInput = page.locator('input[placeholder*="Username"], input[name="uid"], input[type="text"]').first();
  if (await loginInput.isVisible()) {
    console.log('Logging in...');
    await loginInput.fill('akadmin');
    const continueBtn = page.locator('button:has-text("Log in"), button:has-text("Continue"), input[type="submit"]').first();
    await continueBtn.click();
    await page.waitForTimeout(2000);
    const passwordInput = page.locator('input[name="password"], input[type="password"]').first();
    await passwordInput.fill('authentik');
    await continueBtn.click();
    await page.waitForTimeout(6000);
  }

  // Now run fetch in the browser context to query the outpost instances API
  const outposts = await page.evaluate(async () => {
    try {
      const res = await fetch('/api/v3/outposts/instances/');
      return await res.json();
    } catch (err) {
      return { error: (err as Error).message };
    }
  });

  console.log('Outpost instances response:', JSON.stringify(outposts, null, 2));

  // Also query applications to see what apps are configured
  const applications = await page.evaluate(async () => {
    try {
      const res = await fetch('/api/v3/core/applications/');
      return await res.json();
    } catch (err) {
      return { error: (err as Error).message };
    }
  });

  console.log('Applications response:', JSON.stringify(applications, null, 2));

  // Also query providers to see what providers are configured
  const providers = await page.evaluate(async () => {
    try {
      const res = await fetch('/api/v3/providers/all/');
      return await res.json();
    } catch (err) {
      return { error: (err as Error).message };
    }
  });

  console.log('Providers response:', JSON.stringify(providers, null, 2));

  await context.close();
});
