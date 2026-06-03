import { test, expect } from '@playwright/test';

test('Find tab pills HTML', async ({ browser }) => {
  const context = await browser.newContext({ storageState: 'auth-state.json' });
  const page = await context.newPage();

  await page.goto('https://media.researchstack.info/web/#/dashboard/plugins');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(4000);

  const elements = await page.evaluate(() => {
    // Find all elements that contain the word "Available"
    const results: string[] = [];
    const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
    let n;
    while (n = walk.nextNode()) {
      const el = n as HTMLElement;
      // If it contains the exact text "Available" (no children or children text is just "Available")
      if (el.textContent?.trim() === 'Available') {
        results.push(`Tag: ${el.tagName.toLowerCase()}, Class: ${el.className}, ID: ${el.id}, OuterHTML: ${el.outerHTML.slice(0, 300)}`);
      }
    }
    return results;
  });

  console.log('Found Available elements:', elements);
  await context.close();
});
