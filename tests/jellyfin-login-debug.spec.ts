import { test, expect } from '@playwright/test';

test('Debug Jellyfin login', async ({ browser }) => {
  const context = await browser.newContext({ storageState: 'auth-state.json' });
  const page = await context.newPage();

  console.log('Navigating to Jellyfin...');
  await page.goto('https://media.researchstack.info/');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(4000);

  console.log('Initial URL:', page.url());
  await page.screenshot({ path: 'jellyfin-login-initial.png' });

  const usernameInput = page.locator('input[type="text"], input#txtManualName');
  const passwordInput = page.locator('input[type="password"], input#txtManualPassword');

  if (await usernameInput.isVisible()) {
    console.log('Filling login form...');
    await usernameInput.fill('admin');
    await passwordInput.fill('RY03KhsFez73K5va2uUb');
    await page.screenshot({ path: 'jellyfin-login-filled.png' });

    console.log('Clicking login button...');
    const signInBtn = page.locator('button[type="submit"], button:has-text("Sign In")').first();
    await signInBtn.click();
    
    // Wait for URL change or error
    for (let i = 0; i < 10; i++) {
      await page.waitForTimeout(1000);
      console.log(`Step ${i}: URL is ${page.url()}`);
      await page.screenshot({ path: `jellyfin-login-step-${i}.png` });
      
      const bodyText = await page.evaluate(() => document.body.innerText);
      if (bodyText.includes('Invalid') || bodyText.includes('incorrect') || bodyText.includes('failed')) {
        console.log('Login failed message detected!');
        break;
      }
    }
  } else {
    console.log('No login inputs found!');
  }

  await context.close();
});
