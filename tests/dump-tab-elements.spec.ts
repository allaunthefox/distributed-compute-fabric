import { test, expect } from '@playwright/test';

test('Dump tab elements HTML', async ({ browser }) => {
  const context = await browser.newContext({ storageState: 'auth-state.json' });
  const page = await context.newPage();

  await page.goto('https://media.researchstack.info/web/#/dashboard/plugins');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(4000);

  const elementsHtml = await page.evaluate(() => {
    const results: string[] = [];
    // Find all links, buttons, spans, divs with class
    const selectors = ['a', 'button', 'span', 'div.tabButton', '.button-flat', '.emby-button'];
    selectors.forEach(sel => {
      document.querySelectorAll(sel).forEach(el => {
        const text = el.textContent?.trim() || '';
        if (text === 'Available' || text === 'Installed' || text === 'All') {
          results.push(`<${el.tagName.toLowerCase()} class="${el.className}" id="${el.id}" href="${el.getAttribute('href') || ''}" outer="${el.outerHTML.slice(0, 300)}">`);
        }
      });
    });
    return results;
  });

  console.log('Tab elements found:', elementsHtml);
  await context.close();
});
