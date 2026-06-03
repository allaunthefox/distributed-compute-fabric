import { test, expect } from '@playwright/test';

test('Configure Jellyfin OIDC', async ({ page }) => {
  console.log('Navigating to Jellyfin...');
  await page.goto('https://media.researchstack.info/');
  await page.waitForTimeout(6000);

  // If redirected to Authentik login page
  if (page.url().includes('/flow/default-authentication-flow/')) {
    console.log('Redirected to Authentik login page. Logging in...');
    await page.locator('input[name="uid"], input[id*="uid"], input[type="text"]').first().fill('akadmin');
    await page.locator('button[type="submit"], input[type="submit"], button:has-text("Continue")').first().click();
    await page.waitForTimeout(1000);

    await page.locator('input[name="password"], input[id*="password"], input[type="password"]').first().fill('authentik');
    await page.locator('button[type="submit"], input[type="submit"], button:has-text("Continue")').first().click();
    await page.waitForTimeout(5000);
  }

  // If redirected to consent page
  if (page.url().includes('default-provider-authorization-explicit-consent')) {
    console.log('On consent page. Clicking Continue...');
    const continueBtn = page.locator('button:has-text("Continue"), input[type="submit"]');
    await continueBtn.first().click();
    await page.waitForTimeout(10000);
  }

  console.log('Current URL after auth flow:', page.url());

  // We should now be on the Jellyfin home or login page
  const usernameInput = page.locator('#txtManualName');
  const passwordInput = page.locator('#txtManualPassword');

  if (await usernameInput.isVisible()) {
    console.log('Logging in to Jellyfin...');
    await usernameInput.fill('admin');
    await passwordInput.fill('RY03KhsFez73K5va2uUb');
    const signInBtn = page.locator('button[type="submit"], button:has-text("Sign In")').first();
    await signInBtn.click();
    await page.waitForTimeout(8000);
  }

  await page.screenshot({ path: 'jellyfin-dashboard.png' });
  console.log('Final Jellyfin URL:', page.url());
  console.log('Final Jellyfin Title:', await page.title());

  const textContent = await page.evaluate(() => document.body.innerText);
  console.log('Jellyfin text:', textContent.slice(0, 1000));
});
