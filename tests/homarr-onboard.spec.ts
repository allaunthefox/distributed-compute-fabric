import { test } from '@playwright/test';
test('Homarr onboarding', async ({ page }) => {
  test.setTimeout(60000);
  await page.goto('http://100.88.57.96:30093/', { timeout: 10000 });
  await page.waitForTimeout(3000);
  
  // Click "Start update process"
  const startBtn = page.locator('button:has-text("Start update process"):visible').first();
  if (await startBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
    await startBtn.click();
    await page.waitForTimeout(3000);
    console.log('Step 1 clicked');
  }
  
  // Continue through steps
  for (let i = 0; i < 5; i++) {
    const nextBtn = page.locator('button:has-text("Next"):visible, button:has-text("Continue"):visible, button:has-text("Finish"):visible, button[data-button="true"]:visible').first();
    if (await nextBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
      await nextBtn.click();
      await page.waitForTimeout(2000);
      console.log(`Step ${i+2} clicked`);
    } else {
      break;
    }
  }
  
  await page.screenshot({ path: '/tmp/homarr-done.png' });
  console.log('Onboarding complete');
});
