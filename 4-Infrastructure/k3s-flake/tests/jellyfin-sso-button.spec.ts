import { test } from '@playwright/test';
test('Jellyfin SSO login button setup', async ({ page }) => {
  test.setTimeout(60000);
  const BASE = 'http://100.88.57.96:30091';

  await page.goto(`${BASE}/web/#/login.html`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);
  await page.locator('#txtUsername').fill('admin');
  await page.locator('#txtPassword').fill('jellyfin-admin');
  await page.locator('.button-submit:visible').first().click();
  await page.waitForTimeout(5000);

  await page.goto(`${BASE}/web/#/dashboard/general`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(3000);

  // Fill login disclaimer
  const disclaimer = page.locator('textarea:visible').first();
  if (await disclaimer.isVisible()) {
    await disclaimer.fill('');
    await disclaimer.fill(`<form action="https://media.researchstack.info/sso/OID/start/authentik">
  <button class="raised block emby-button button-submit">
    Sign in with SSO
  </button>
</form>`);
  }

  // Fill custom CSS
  const cssArea = page.locator('textarea:visible').nth(1);
  if (await cssArea.isVisible()) {
    await cssArea.fill(`a.raised.emby-button { padding:0.9em 1em; color: inherit !important; }
.disclaimerContainer { display: block; }`);
  }

  // Save
  const saveBtn = page.locator('button:has-text("Save"):visible').first();
  if (await saveBtn.isVisible()) {
    await saveBtn.click();
    await page.waitForTimeout(2000);
  }

  console.log('SSO login button configured');
});
