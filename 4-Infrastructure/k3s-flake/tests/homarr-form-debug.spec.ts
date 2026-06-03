import { test } from '@playwright/test';
test('form debug', async ({ page }) => {
  test.setTimeout(20000);
  await page.goto('http://100.88.57.96:30093/', { timeout: 10000, waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3000);
  await page.evaluate(() => {
    document.querySelectorAll('button').forEach(b => {
      if (b.textContent?.includes('Start update process')) b.click();
    });
  });
  await page.waitForTimeout(4000);

  // Check ALL input types
  console.log('input[type=text]:', await page.locator('input[type="text"]').count());
  console.log('input[type=password]:', await page.locator('input[type="password"]').count());
  console.log('input[type=email]:', await page.locator('input[type="email"]').count());
  console.log('input:not([type]):', await page.locator('input:not([type])').count());
  console.log('All inputs:', await page.locator('input').count());
  console.log('[contenteditable]:', await page.locator('[contenteditable]').count());
  
  // Dump all input HTML
  const html = await page.content();
  const inputMatches = html.match(/<input[^>]*>/g) || [];
  console.log('Input HTML elements found:', inputMatches.length);
  for (const m of inputMatches.slice(0,5)) console.log('  ' + m.substring(0,120));
});
