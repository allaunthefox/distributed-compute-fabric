import { test } from '@playwright/test';
test('Jellyfin branding SSO button', async ({ page }) => {
  test.setTimeout(60000);
  
  // Login
  await page.goto('http://100.88.57.96:30091/web/#/login.html');
  await page.waitForTimeout(3000);
  await page.locator('#txtUsername').fill('admin');
  await page.locator('#txtPassword').fill('jellyfin-admin');
  await page.locator('button.button-submit').first().click();
  await page.waitForTimeout(5000);

  // Go to general settings
  await page.goto('http://100.88.57.96:30091/web/#/dashboard/general');
  await page.waitForTimeout(5000);

  // Fill disclaimer textarea
  const textareas = page.locator('textarea');
  const count = await textareas.count();
  console.log(`Found ${count} textareas`);
  
  if (count >= 1) {
    await textareas.nth(0).fill('');
    await textareas.nth(0).fill('<form action="https://media.researchstack.info/sso/OID/start/authentik"><button class="raised block emby-button button-submit">Sign in with SSO</button></form>');
  }
  if (count >= 2) {
    await textareas.nth(1).fill('a.raised.emby-button { padding:0.9em 1em; color: inherit !important; }.disclaimerContainer { display: block; }');
  }

  // Save
  await page.locator('button:has-text("Save"):visible').first().click();
  await page.waitForTimeout(3000);
  console.log('SSO branding saved');
});
