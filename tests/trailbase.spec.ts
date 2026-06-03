import { test, expect } from '@playwright/test';

test('Configure TrailBase SSO', async ({ page }) => {
  console.log('Navigating to TrailBase admin portal...');
  await page.goto('https://trailbase.researchstack.info/_/admin/');
  await page.waitForLoadState('networkidle');

  // Fill credentials
  const emailInput = page.locator('input[type="email"]');
  const passwordInput = page.locator('input[type="password"]');

  if (await emailInput.isVisible()) {
    console.log('Logging in...');
    await emailInput.fill('admin@localhost');
    await passwordInput.fill('RY03KhsFez73K5va2uUb');
    const loginBtn = page.locator('button[type="submit"]');
    await loginBtn.first().click();
    await page.waitForTimeout(3000);
  }

  // Click settings link
  console.log('Clicking settings link...');
  await page.locator('a[href="/_/admin/settings/"]').click();
  await page.waitForTimeout(3000);

  // Click Auth submenu
  console.log('Clicking Auth settings...');
  await page.locator('text="Auth"').first().click();
  await page.waitForTimeout(3000);

  // Find OpenID Connect toggle circle
  console.log('Locating OpenID Connect trigger...');
  const oidcItem = page.locator('div.border-b:has(button:has-text("OpenID Connect"))');
  const oidcTrigger = oidcItem.locator('button').first();
  const toggleCircle = oidcTrigger.locator('svg').first();

  // Click toggle circle (this both enables it and expands the accordion)
  console.log('Clicking OIDC toggle circle to enable and expand...');
  await toggleCircle.click();
  await page.waitForTimeout(3000); // Wait for expansion animation to complete

  // Helper function to fill fields dynamically by label text
  const fillFieldByLabel = async (labelText: string, value: string) => {
    const inputId = await page.evaluate((text) => {
      const labels = Array.from(document.querySelectorAll('label'));
      const label = labels.find(l => l.textContent?.trim() === text);
      if (!label) return null;
      
      // Traverse up to find outer label with 'for' attribute
      let outerLabel: HTMLElement | null = label;
      while (outerLabel && outerLabel.tagName !== 'LABEL') {
        outerLabel = outerLabel.parentElement;
      }
      if (outerLabel) {
        const forAttr = outerLabel.getAttribute('for');
        if (forAttr) return forAttr;
      }
      
      // Fallback: look at parent grid and find input
      const parent = label.closest('.grid');
      if (parent) {
        const input = parent.querySelector('input');
        if (input) return input.id;
      }
      return null;
    }, labelText);

    if (inputId) {
      console.log(`Filling field "${labelText}" (ID: ${inputId})...`);
      await page.locator(`#${inputId}`).fill(value);
    } else {
      throw new Error(`Could not find input ID for label "${labelText}"`);
    }
  };

  // Fill OIDC fields
  console.log('Filling OIDC fields...');
  await fillFieldByLabel('Client Id', 'sso-trailbase');
  await fillFieldByLabel('Client Secret', '64810e7e2960494a4ba5340bb0c1b19af3e61e17c6f1c6f6eb7ed9aa72cabb1a');
  await fillFieldByLabel('Auth URL', 'https://auth.researchstack.info/application/o/authorize/');
  await fillFieldByLabel('Token URL', 'https://auth.researchstack.info/application/o/token/');
  await fillFieldByLabel('User API URL', 'https://auth.researchstack.info/application/o/userinfo/');

  // Click submit button at the bottom of settings page
  console.log('Clicking Save/Submit...');
  const submitBtn = page.locator('button[type="submit"], button:has-text("Submit"), button:has-text("Save")').first();
  await submitBtn.click();
  await page.waitForTimeout(4000);

  await page.screenshot({ path: 'trailbase-oidc-saved.png' });
  console.log('Finished TrailBase OIDC configuration.');
});
