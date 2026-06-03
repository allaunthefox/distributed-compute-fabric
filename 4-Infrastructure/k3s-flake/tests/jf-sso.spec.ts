import { test } from '@playwright/test';
test('sso button', async ({ page }) => {
  test.setTimeout(30000);
  
  await page.goto('http://100.88.57.96:30091/web/', { timeout: 10000 });
  await page.waitForTimeout(2000);
  
  // Login
  await page.locator('#txtUsername').fill('admin');
  await page.locator('#txtPassword').fill('jellyfin-admin');
  await page.locator('.button-submit').first().click();
  await page.waitForTimeout(3000);
  
  // Use hash navigation instead of goto
  await page.evaluate(() => { window.location.hash = '#/dashboard/general'; });
  await page.waitForTimeout(4000);
  
  // Fill textareas
  const tas = page.locator('textarea');
  const n = await tas.count();
  console.log(`Textareas: ${n}`);
  if (n > 0) await tas.nth(0).fill('<form action="https://media.researchstack.info/sso/OID/start/authentik"><button class="raised block emby-button button-submit">Sign in with SSO</button></form>');
  if (n > 1) await tas.nth(1).fill('a.raised.emby-button { padding:0.9em 1em; color:inherit!important; } .disclaimerContainer { display:block; }');
  
  // Save
  await page.locator('.button-submit').first().click();
  await page.waitForTimeout(2000);
  console.log('Done');
});
