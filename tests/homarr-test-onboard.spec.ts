import { test } from '@playwright/test';
test('Complete Homarr onboard', async ({ page }) => {
  test.setTimeout(60000);
  await page.goto('http://100.88.57.96:30093/', { timeout: 10000, waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3000);
  
  const title = await page.title();
  console.log('Initial title:', title);

  if (title.includes('Onboard')) {
    // Click start
    await page.evaluate(() => {
      document.querySelectorAll('button').forEach(b => {
        if (b.textContent?.trim() === 'Start update process') b.click();
      });
    });
    await page.waitForTimeout(4000);

    // Fill account form
    const usernameInput = page.locator('input[type="text"]').first();
    if (await usernameInput.isVisible({ timeout: 3000 }).catch(() => false)) {
      await usernameInput.fill('allaun');
      const pwInputs = page.locator('input[type="password"]');
      await pwInputs.nth(0).fill('TYW82QNB!k0y!pXc');
      await pwInputs.nth(1).fill('TYW82QNB!k0y!pXc');
      await page.waitForTimeout(500);
      
      // Click Continue
      await page.locator('button:has-text("Continue"):visible').first().click({ force: true, noWaitAfter: true });
      await page.waitForTimeout(3000);
      console.log('Account created');
    }

    // Click through remaining steps
    for (let i = 0; i < 20; i++) {
      const btn = page.locator('button:has-text("Continue"):visible, button:has-text("Finish"):visible').first();
      if (await btn.isVisible({ timeout: 2000 }).catch(() => false)) {
        const text = await btn.textContent();
        await btn.click({ force: true, noWaitAfter: true });
        await page.waitForTimeout(2000);
        console.log(`Step ${i+1}: clicked "${text}" url=${page.url()}`);
      } else {
        break;
      }
    }
  }

  // Check final state
  await page.waitForTimeout(3000);
  const finalTitle = await page.title();
  console.log('Final title:', finalTitle);
  console.log('Final URL:', page.url());
  
  if (!finalTitle.includes('Onboard')) {
    console.log('SUCCESS: Onboard completed!');
    // Check for apps
    const appCards = page.locator('[class*="app"], [class*="card"], a[href*="researchstack"]');
    const count = await appCards.count();
    console.log(`Found ${count} app-like elements`);
  }
  
  await page.screenshot({ path: '/tmp/homarr-test-final.png' });
});
