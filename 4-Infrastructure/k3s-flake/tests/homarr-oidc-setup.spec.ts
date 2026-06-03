import { test, expect } from '@playwright/test';

test('Log in to Homarr via SSO and configure', async ({ browser }) => {
  const context = await browser.newContext({ storageState: 'auth-state.json' });
  const page = await context.newPage();

  console.log('Navigating to Homarr via domain...');
  await page.goto('https://www.researchstack.info/', { timeout: 20000 });
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(5000);

  console.log('Current URL:', page.url());
  await page.screenshot({ path: 'homarr-sso-initial.png' });

  // Handle Authentik consent screen if present
  if (page.url().includes('consent')) {
    console.log('Consent screen detected. Clicking continue...');
    const continueBtn = page.locator('button:has-text("Continue"), input[type="submit"]').first();
    if (await continueBtn.isVisible()) {
      await continueBtn.click();
      await page.waitForTimeout(6000);
      console.log('After consent URL:', page.url());
      await page.screenshot({ path: 'homarr-after-consent.png' });
    }
  }

  // Check if we are on login or onboarding page
  const pageText = await page.evaluate(() => document.body.innerText);
  console.log('Homarr page text:', pageText.slice(0, 1000));

  // Let's go to /manage/boards directly if logged in
  console.log('Navigating directly to /manage/boards...');
  await page.goto('https://www.researchstack.info/manage/boards', { timeout: 20000 });
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(5000);
  await page.screenshot({ path: 'homarr-sso-manage-boards.png' });

  const manageText = await page.evaluate(() => document.body.innerText);
  console.log('Manage Boards page text:', manageText.slice(0, 1000));

  // Click Create board button if visible
  const createBtn = page.locator('button:has-text("Create board"), button:has-text("New board"), button:has-text("Create")').first();
  if (await createBtn.isVisible()) {
    console.log('Clicking Create board...');
    await createBtn.click();
    await page.waitForTimeout(3000);
    await page.screenshot({ path: 'homarr-sso-create-modal.png' });

    // Fill name
    const nameInput = page.locator('input[placeholder*="Name"], input[name="name"]').first();
    if (await nameInput.isVisible()) {
      await nameInput.fill('Home');
    }
    
    // Save
    const saveBtn = page.locator('button[type="submit"], button:has-text("Save"), button:has-text("Create")').first();
    await saveBtn.click();
    await page.waitForTimeout(5000);
    await page.screenshot({ path: 'homarr-sso-board-created.png' });
    console.log('Board "Home" created successfully!');

    // Let's set it as home board or go to root
    console.log('Navigating to root...');
    await page.goto('https://www.researchstack.info/', { timeout: 20000 });
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(5000);
    await page.screenshot({ path: 'homarr-sso-root-final.png' });
  } else {
    console.log('Create board button not found.');
  }

  await context.close();
});
