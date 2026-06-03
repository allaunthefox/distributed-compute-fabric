import { test } from '@playwright/test';
test('branding', async ({ page }) => {
  test.setTimeout(60000);
  await page.goto('http://100.88.57.96:30091/web/', { timeout: 15000 });
  await page.waitForTimeout(2000);
  
  // Login
  await page.locator('#txtUsername').fill('admin');
  await page.locator('#txtPassword').fill('jellyfin-admin');
  await page.locator('.button-submit').first().click();
  await page.waitForTimeout(3000);
  
  // Navigate to settings
  await page.goto('http://100.88.57.96:30091/web/#/dashboard/general', { timeout: 15000 });
  await page.waitForTimeout(3000);
  
  // Fill and save
  const ta = page.locator('textarea').first();
  if (await ta.isVisible()) {
    await ta.fill('<form action="https://media.researchstack.info/sso/OID/start/authentik"><button class="raised block emby-button button-submit">Sign in with SSO</button></form>');
  }
  const ta2 = page.locator('textarea').nth(1);
  if (await ta2.isVisible()) {
    await ta2.fill('a.raised.emby-button { padding:0.9em 1em; color:inherit!important; }.disclaimerContainer { display:block; }');
  }
  
  await page.locator('.button-submit').first().click();
  await page.waitForTimeout(2000);
  console.log('Done');
});
