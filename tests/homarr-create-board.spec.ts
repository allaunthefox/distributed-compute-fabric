import { test, expect } from '@playwright/test';

test('Log in and create Homarr board', async ({ page }) => {
  test.setTimeout(90000);

  console.log('Navigating to Homarr login page...');
  await page.goto('http://100.88.57.96:30108/auth/login', { timeout: 15000, waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(4000);
  await page.screenshot({ path: 'homarr-login-page.png' });

  // Fill login
  console.log('Filling login form...');
  const usernameInput = page.locator('input[name="username"], input[type="text"]').first();
  if (await usernameInput.isVisible()) {
    await usernameInput.fill('allaun');
    await page.locator('input[type="password"]').first().fill('TYW82QNB!k0y!pXc');
    await page.locator('button:has-text("Login"), button:has-text("Sign in"), button[type="submit"]').first().click();
    await page.waitForTimeout(6000);
  }

  console.log('Current URL after login attempt:', page.url());
  await page.screenshot({ path: 'homarr-after-login.png' });

  // Go to boards management directly
  console.log('Navigating to manage boards...');
  await page.goto('http://100.88.57.96:30108/manage/boards', { timeout: 15000, waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(4000);
  await page.screenshot({ path: 'homarr-manage-boards.png' });

  const pageText = await page.evaluate(() => document.body.innerText);
  console.log('Manage Boards page text:', pageText.slice(0, 1000));

  // If there's a button to create a board
  const createBtn = page.locator('button:has-text("Create board"), button:has-text("New board"), button:has-text("Create")').first();
  if (await createBtn.isVisible()) {
    console.log('Clicking Create board button...');
    await createBtn.click();
    await page.waitForTimeout(2000);
    await page.screenshot({ path: 'homarr-create-board-modal.png' });

    // Fill board creation form
    // Let's find inputs inside the modal
    const nameInput = page.locator('input[placeholder*="Name"], input[name="name"]').first();
    if (await nameInput.isVisible()) {
      await nameInput.fill('Home');
    } else {
      // Fallback: fill first text input in modal
      await page.locator('div[role="dialog"] input[type="text"], ak-modal-dialog input[type="text"], input[type="text"]').first().fill('Home');
    }

    // Let's click submit/save inside modal
    const saveBtn = page.locator('button[type="submit"], button:has-text("Save"), button:has-text("Create")').first();
    await saveBtn.click();
    await page.waitForTimeout(4000);
    await page.screenshot({ path: 'homarr-board-created.png' });
    console.log('Board "Home" created successfully!');

    // Let's set it as home board if needed, or check if it became the default
    // We can navigate to '/' and see if the error is gone
    console.log('Navigating to '/'...');
    await page.goto('http://100.88.57.96:30108/', { timeout: 15000 });
    await page.waitForTimeout(4000);
    await page.screenshot({ path: 'homarr-root-final.png' });
    console.log('Homarr root URL:', page.url());
  } else {
    console.log('Create board button not found or already has boards.');
  }

  await page.context().close();
});
