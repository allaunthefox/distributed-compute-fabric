import { test, expect } from '@playwright/test';

test('Check and Configure Authentik Outpost', async ({ browser }) => {
  const context = await browser.newContext();
  const page = await context.newPage();

  console.log('Navigating to Authentik admin outposts...');
  await page.goto('https://auth.researchstack.info/if/admin/#/apps/outposts');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(4000);

  // Robust login detection: check if "Log in" button or username field is visible
  const loginInput = page.locator('input[placeholder*="Username"], input[name="uid"], input[type="text"]').first();
  if (await loginInput.isVisible()) {
    console.log('Login form detected. Logging in...');
    await loginInput.fill('akadmin');
    await page.screenshot({ path: 'authentik-login-step1.png' });
    
    const continueBtn = page.locator('button:has-text("Log in"), button:has-text("Continue"), input[type="submit"]').first();
    await continueBtn.click();
    await page.waitForTimeout(2000);

    const passwordInput = page.locator('input[name="password"], input[type="password"]').first();
    await passwordInput.fill('authentik');
    await page.screenshot({ path: 'authentik-login-step2.png' });
    
    await continueBtn.click();
    await page.waitForTimeout(6000);
    
    console.log('Logged in. Current URL:', page.url());
  }

  // Double check we are on the outposts page
  if (!page.url().includes('/apps/outposts')) {
    console.log('Navigating to outposts page directly...');
    await page.goto('https://auth.researchstack.info/if/admin/#/apps/outposts');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(4000);
  }

  await page.screenshot({ path: 'authentik-outposts-page.png' });
  console.log('Outposts URL:', page.url());

  // Wait, the page is built using web components, so finding elements might require waiting or shadow DOM piercing
  // Let's dump all text on the page to see if "authentik Embedded Outpost" is visible
  const pageText = await page.evaluate(() => document.body.innerText);
  console.log('Outposts Page text:', pageText.slice(0, 1500));

  // Let's find the edit button. In Authentik, it is often a button inside a table row.
  // We can search for edit buttons and click the first one if there is only one outpost, or find one near "Embedded Outpost"
  // Let's locate the edit button and click it
  console.log('Looking for Edit button...');
  const editBtn = page.locator('ak-table-row:has-text("authentik Embedded Outpost") button[title*="Edit"], button:has-text("Edit"), button[aria-label*="Edit"]').first();
  if (await editBtn.isVisible()) {
    console.log('Edit button is visible. Clicking...');
    await editBtn.click();
    await page.waitForTimeout(3000);
    await page.screenshot({ path: 'authentik-outpost-edit-modal.png' });

    // Let's see if we can find selected apps
    const modalText = await page.evaluate(() => document.querySelector('div[role="dialog"], ak-modal-dialog')?.innerText || 'No modal');
    console.log('Modal text:', modalText);
  } else {
    console.log('Edit button is NOT visible directly. Let us click on any edit button on the page.');
    const anyEditBtn = page.locator('button[title*="Edit"], button:has-text("Edit")').first();
    if (await anyEditBtn.isVisible()) {
      await anyEditBtn.click();
      await page.waitForTimeout(3000);
      await page.screenshot({ path: 'authentik-outpost-edit-modal.png' });
    } else {
      console.log('Could not find any Edit button at all.');
    }
  }

  await context.storageState({ path: 'auth-state.json' });
  await context.close();
});
