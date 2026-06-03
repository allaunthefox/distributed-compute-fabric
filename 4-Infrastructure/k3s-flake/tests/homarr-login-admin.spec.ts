import { test, expect } from '@playwright/test';

test('Log in as admin to Homarr', async ({ page }) => {
  test.setTimeout(60000);

  const passwords = ['RY03KhsFez73K5va2uUb', 'homarr-admin', 'authentik', 'admin'];
  
  for (const pw of passwords) {
    console.log(`Trying login as admin with password: ${pw}...`);
    await page.goto('http://100.88.57.96:30108/auth/login', { timeout: 15000, waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3000);

    const usernameInput = page.locator('input[name="username"], input[type="text"]').first();
    if (await usernameInput.isVisible()) {
      await usernameInput.fill('admin');
      await page.locator('input[type="password"]').first().fill(pw);
      await page.locator('button:has-text("Login"), button:has-text("Sign in"), button[type="submit"]').first().click();
      await page.waitForTimeout(5000);
      
      console.log(`URL after login with password "${pw}":`, page.url());
      if (!page.url().includes('auth/login')) {
        console.log(`SUCCESS! Logged in as admin with password: ${pw}`);
        await page.screenshot({ path: `homarr-admin-success.png` });
        
        // Go to boards management
        await page.goto('http://100.88.57.96:30108/manage/boards', { timeout: 15000 });
        await page.waitForTimeout(4000);
        await page.screenshot({ path: `homarr-admin-boards.png` });
        
        const pageText = await page.evaluate(() => document.body.innerText);
        console.log('Boards page text:', pageText.slice(0, 1000));
        await page.context().close();
        return;
      }
    }
  }
  
  console.log('Failed to log in as admin with any standard password.');
  await page.context().close();
});
