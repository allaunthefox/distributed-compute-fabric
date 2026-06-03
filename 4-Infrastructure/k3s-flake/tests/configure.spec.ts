import { test, expect } from '@playwright/test';

test('Configure Authentik and check Uptime Kuma', async ({ browser }) => {
  // Create first context and log in to Authentik
  const context = await browser.newContext();
  const page = await context.newPage();
  
  console.log('Navigating to Authentik login page...');
  await page.goto('https://auth.researchstack.info/flows/-/default/authentication/');
  await page.waitForLoadState('networkidle');

  // Fill username
  console.log('Logging in to Authentik...');
  await page.locator('input[name="uid"], input[id*="uid"], input[type="text"]').first().fill('akadmin');
  await page.locator('button[type="submit"], input[type="submit"], button:has-text("Continue")').first().click();
  await page.waitForTimeout(1000);

  // Fill password
  await page.locator('input[name="password"], input[id*="password"], input[type="password"]').first().fill('authentik');
  await page.locator('button[type="submit"], input[type="submit"], button:has-text("Continue")').first().click();

  // Wait for redirect to complete
  await page.waitForTimeout(5000);
  console.log('Logged in to Authentik. URL:', page.url());

  // Save storage state to reuse cookies
  console.log('Saving authentication state to auth-state.json...');
  await context.storageState({ path: 'auth-state.json' });
  await context.close();

  // Create a new context with the saved storage state
  console.log('Launching new context with saved auth state...');
  const newContext = await browser.newContext({ storageState: 'auth-state.json' });
  const newPage = await newContext.newPage();

  // Go to Uptime Kuma
  console.log('Navigating to Uptime Kuma...');
  await newPage.goto('https://uptime.researchstack.info/');
  await newPage.waitForLoadState('networkidle');
  await newPage.waitForTimeout(4000);

  // Check if we are on the consent page
  if (newPage.url().includes('default-provider-authorization-explicit-consent')) {
    console.log('On consent page. Clicking Continue...');
    const continueBtn = newPage.locator('button:has-text("Continue"), input[type="submit"]');
    await continueBtn.first().click();
    await newPage.waitForTimeout(5000);
  }

  await newPage.screenshot({ path: 'uptime-kuma-dashboard.png' });
  console.log('Uptime Kuma dashboard screenshot saved.');
  console.log('Uptime Kuma URL:', newPage.url());
  console.log('Uptime Kuma Title:', await newPage.title());

  const content = await newPage.evaluate(() => document.body.innerText);
  console.log('Uptime Kuma text:', content.slice(0, 1000));
  
  await newContext.close();
});
