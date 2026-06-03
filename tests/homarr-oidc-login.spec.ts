import { test } from '@playwright/test';
test('OIDC login', async ({ page }) => {
  test.setTimeout(60000);
  
  // Go to Homarr login page
  await page.goto('http://100.88.57.96:30108/auth/login', { timeout: 10000 });
  await page.waitForTimeout(3000);
  
  // Click "Login with Authentik"
  const oidcBtn = page.locator('button:has-text("Authentik"):visible').first();
  if (await oidcBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
    await oidcBtn.click();
    await page.waitForTimeout(5000);
    console.log('Redirected to:', page.url());
    
    // We should be on Authentik login page
    if (page.url().includes('auth.researchstack.info')) {
      await page.locator('input[name="username"], input[type="text"]').first().fill('akadmin');
      await page.locator('input[type="password"]').first().fill('authentik');
      await page.locator('button[type="submit"]').first().click();
      await page.waitForTimeout(5000);
      console.log('After Authentik login:', page.url());
    }
  }
  
  // Check if we're logged in
  const cookies = await page.context().cookies();
  console.log('Cookies:', cookies.map(c => c.name).join(', '));
  console.log('Final URL:', page.url());
});
