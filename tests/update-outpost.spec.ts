import { test, expect } from '@playwright/test';

test('Configure Authentik Outpost Applications', async ({ browser }) => {
  const context = await browser.newContext();
  const page = await context.newPage();

  console.log('Navigating to Authentik admin home...');
  await page.goto('https://auth.researchstack.info/if/admin/#/outpost/outposts');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(4000);

  // Login
  const loginInput = page.locator('input[placeholder*="Username"], input[name="uid"], input[type="text"]').first();
  if (await loginInput.isVisible()) {
    console.log('Logging in...');
    await loginInput.fill('akadmin');
    const continueBtn = page.locator('button:has-text("Log in"), button:has-text("Continue"), input[type="submit"]').first();
    await continueBtn.click();
    await page.waitForTimeout(2000);
    const passwordInput = page.locator('input[name="password"], input[type="password"]').first();
    await passwordInput.fill('authentik');
    await continueBtn.click();
    await page.waitForTimeout(6000);
  }

  // Go to outposts
  if (!page.url().includes('#/outpost/outposts')) {
    await page.goto('https://auth.researchstack.info/if/admin/#/outpost/outposts');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(4000);
  }

  console.log('On outposts page. Capturing screenshot...');
  await page.screenshot({ path: 'authentik-outposts-page.png' });

  // Piercing shadow DOM to find the Edit button
  // Let's find "authentik Embedded Outpost" and click the Edit button in its row
  console.log('Looking for Edit button...');
  
  // Let's run a script in browser context to click the Edit button inside the shadow DOM
  const clicked = await page.evaluate(() => {
    function findAndClickEdit(): boolean {
      // Find the row containing "authentik Embedded Outpost"
      // In Authentik UI, the outposts list is typically rendered by a web component ak-table or similar
      const rows = document.querySelectorAll('*');
      for (const el of Array.from(rows)) {
        // If it is an element with text or label
        if (el.shadowRoot) {
          const innerRows = el.shadowRoot.querySelectorAll('tr, div.tr, ak-table-row');
          for (const row of Array.from(innerRows)) {
            const rowText = (row as HTMLElement).innerText || '';
            if (rowText.includes('authentik Embedded Outpost') || rowText.includes('Embedded')) {
              // Find the edit button in this row or shadow root of the row
              const buttons = row.querySelectorAll('button, a, [role="button"]');
              for (const btn of Array.from(buttons)) {
                if (btn.textContent?.includes('Edit') || btn.getAttribute('title')?.includes('Edit') || btn.innerHTML.includes('edit')) {
                  (btn as HTMLElement).click();
                  return true;
                }
              }
              // Check shadow root of row elements
              const cellElements = row.querySelectorAll('*');
              for (const cell of Array.from(cellElements)) {
                if (cell.shadowRoot) {
                  const shadowBtns = cell.shadowRoot.querySelectorAll('button, a');
                  for (const sBtn of Array.from(shadowBtns)) {
                    if (sBtn.textContent?.includes('Edit') || sBtn.getAttribute('title')?.includes('Edit')) {
                      (sBtn as HTMLElement).click();
                      return true;
                    }
                  }
                }
              }
            }
          }
        }
      }
      
      // Fallback: search globally for any edit button or action button next to "Embedded Outpost"
      const anyEdit = document.querySelector('button[title*="Edit"], ak-table-row button');
      if (anyEdit) {
        (anyEdit as HTMLElement).click();
        return true;
      }
      return false;
    }
    return findAndClickEdit();
  });

  console.log('Clicked edit button:', clicked);
  await page.waitForTimeout(3000);
  await page.screenshot({ path: 'authentik-outpost-edit-clicked.png' });

  // In the edit modal, check the available applications
  // Let's see if we can select all options in the multi-select
  console.log('Checking modal multi-select...');
  const selectedAll = await page.evaluate(() => {
    // Look for multi-select element or list of applications
    // Usually it has a select element with multiple attribute, or a search input
    // Let's search inside the open ak-modal-dialog
    const modal = document.querySelector('ak-modal-dialog, div[role="dialog"]');
    if (!modal) return 'No modal found';
    
    // Find all select elements inside the modal shadow root
    function findSelects(root: Element | ShadowRoot): HTMLSelectElement[] {
      const results: HTMLSelectElement[] = [];
      const selects = root.querySelectorAll('select');
      selects.forEach(s => results.push(s));
      const all = root.querySelectorAll('*');
      all.forEach(el => {
        if (el.shadowRoot) {
          results.push(...findSelects(el.shadowRoot));
        }
      });
      return results;
    }
    
    const rootToSearch = modal.shadowRoot || modal;
    const selects = findSelects(rootToSearch);
    if (selects.length > 0) {
      const select = selects[0];
      // Select all options
      let selectedNames: string[] = [];
      for (let i = 0; i < select.options.length; i++) {
        select.options[i].selected = true;
        selectedNames.push(select.options[i].text || select.options[i].value);
      }
      // Trigger change event
      select.dispatchEvent(new Event('change', { bubbles: true }));
      select.dispatchEvent(new Event('input', { bubbles: true }));
      
      // Find the update button to submit the form
      let submitBtn: HTMLElement | null = null;
      const modalBtns = rootToSearch.querySelectorAll('button, input[type="submit"]');
      for (const btn of Array.from(modalBtns)) {
        if (btn.textContent?.includes('Update') || btn.textContent?.includes('Save') || btn.textContent?.includes('Submit')) {
          submitBtn = btn as HTMLElement;
          break;
        }
      }
      if (submitBtn) {
        submitBtn.click();
        return `Selected options: ${selectedNames.join(', ')}. Clicked submit.`;
      }
      return `Selected options: ${selectedNames.join(', ')}. Could not find submit button.`;
    }
    
    // Fallback: dual list select
    // Let's check if there is an ak-duallist-select component
    const duallist = modal.querySelector('ak-duallist-select') || rootToSearch.querySelector('ak-duallist-select');
    if (duallist) {
      // dual-list selector has custom properties or shadow DOM
      // Let's look inside its shadow root
      const dlRoot = duallist.shadowRoot || duallist;
      // It usually has "Add all" button or similar, or checkboxes
      const addAllBtn = dlRoot.querySelector('button[title*="Add all"], button:has-text("Add all")') || 
                         Array.from(dlRoot.querySelectorAll('button')).find(b => b.textContent?.includes('Add all') || b.innerHTML.includes('forward'));
      if (addAllBtn) {
        (addAllBtn as HTMLElement).click();
        
        // Find submit button in main modal
        let submitBtn: HTMLElement | null = null;
        const modalBtns = rootToSearch.querySelectorAll('button, input[type="submit"]');
        for (const btn of Array.from(modalBtns)) {
          if (btn.textContent?.includes('Update') || btn.textContent?.includes('Save') || btn.textContent?.includes('Submit')) {
            submitBtn = btn as HTMLElement;
            break;
          }
        }
        if (submitBtn) {
          submitBtn.click();
          return 'Found duallist, clicked Add all, clicked submit.';
        }
        return 'Found duallist, clicked Add all, but no submit button.';
      }
    }

    return 'No standard select or duallist found in modal';
  });

  console.log('Selected all result:', selectedAll);
  await page.waitForTimeout(5000);
  await page.screenshot({ path: 'authentik-outpost-updated.png' });

  await context.close();
});
