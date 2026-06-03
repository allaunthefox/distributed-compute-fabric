import { test } from '@playwright/test';
test('do init', async ({ page }) => {
  test.setTimeout(60000);

  // 1. Go to init page
  await page.goto('http://100.88.57.96:30108/', { timeout: 10000 });
  await page.waitForTimeout(3000);
  
  // 2. Click "Start from scratch"
  await page.evaluate(() => {
    document.querySelectorAll('button').forEach(b => {
      if (b.textContent?.includes('Start from scratch')) b.click();
    });
  });
  await page.waitForTimeout(3000);
  console.log('1:', page.url());

  // 3. Fill account form
  const usernameInput = page.locator('input').first();
  if (await usernameInput.isVisible({ timeout: 3000 }).catch(() => false)) {
    await usernameInput.fill('allaun');
    const pwInput = page.locator('input[type="password"]').first();
    if (await pwInput.isVisible()) await pwInput.fill('TYW82QNB!k0y!pXc');
    
    // Submit
    await page.locator('button[type="submit"]').first().click({ force: true, noWaitAfter: true });
    await page.waitForTimeout(3000);
    console.log('2:', page.url());
  }

  // 4. Continue through remaining steps
  for (let i = 0; i < 15; i++) {
    const btn = page.locator('button[type="submit"]:visible, button:has-text("Continue"):visible').first();
    if (await btn.isVisible({ timeout: 2000 }).catch(() => false)) {
      await btn.click({ force: true, noWaitAfter: true });
      await page.waitForTimeout(3000);
      console.log(`${i+3}: ${page.url().split('?')[0]}`);
    } else {
      const url = page.url();
      if (!url.includes('init')) {
        console.log('SETUP COMPLETE at:', url);
        break;
      }
    }
  }

  console.log('Final:', page.url());
  await page.context().cookies().then(c => console.log('Cookies:', c.map(x => x.name).join(', ')));
  await page.screenshot({ path: '/tmp/homarr-init-done.png' });
});
