import { test, expect } from '@playwright/test';

test('Find Available element HTML', async ({ browser }) => {
  const context = await browser.newContext({ storageState: 'auth-state.json' });
  const page = await context.newPage();

  await page.goto('https://media.researchstack.info/web/#/dashboard/plugins');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(4000);

  // Print HTML of elements containing "Available"
  const elementsHtml = await page.evaluate(() => {
    // Find all elements containing the text "Available"
    const results: string[] = [];
    const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
    let n;
    while (n = walk.nextNode()) {
      const el = n as HTMLElement;
      if (el.textContent === 'Available' || el.getAttribute('class')?.includes('Available') || el.innerText === 'Available') {
        results.push(`<${el.tagName.toLowerCase()} class="${el.className}" id="${el.id}" href="${el.getAttribute('href') || ''}">${el.outerHTML.slice(0, 300)}</${el.tagName.toLowerCase()}>`);
      }
    }
    return results;
  });

  console.log('Available elements found:', elementsHtml);
  await context.close();
});
