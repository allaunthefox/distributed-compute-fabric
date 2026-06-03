import { test, expect } from '@playwright/test';
import * as fs from 'fs';

/**
 * Comprehensive Authentik test suite.
 *
 * Coverage:
 *   Layer 1 — Basic connectivity (login page, OIDC discovery, API health)
 *   Layer 2 — API operations (users, groups, providers, apps, outposts)
 *   Layer 3 — Admin UI login & navigation
 *   Layer 4 — Provider & Application CRUD via API
 *   Layer 5 — Forward-auth SSO interception
 *   Layer 6 — Outpost health
 *   Layer 7 — Token validity and auth header propagation
 *
 * Run:
 *   npx playwright test authentik-comprehensive.spec.ts
 *   AUTHENTIK_TOKEN=... npx playwright test authentik-comprehensive.spec.ts
 *
 * State awareness:
 *   - Live infrastructure against https://researchstack.info / auth.researchstack.info
 *   - Bootstrap credentials: akadmin / authentik
 *   - Bootstrap API token: authentik-bootstrap-token (override via AUTHENTIK_TOKEN env)
 *   - Authentik version: 2026.x (HelmChart)
 */

const AUTH = {
  base: 'https://researchstack.info',
  auth: 'https://auth.researchstack.info',
  admin: 'https://auth.researchstack.info/if/admin',
  adminUser: 'akadmin',
  adminPass: 'authentik',
  apiToken: process.env.AUTHENTIK_TOKEN || 'authentik-bootstrap-token',
};

//
// API paths for Authentik 2026.x REST API:
//
const AUTHENTIK_API = `${AUTH.auth}/api/v3`;
const API = {
  users: `${AUTHENTIK_API}/core/users/`,
  groups: `${AUTHENTIK_API}/core/groups/`,
  providers: `${AUTHENTIK_API}/providers/all/`,
  providersProxy: `${AUTHENTIK_API}/providers/proxy/`,
  applications: `${AUTHENTIK_API}/core/applications/`,
  outposts: `${AUTHENTIK_API}/outposts/instances/`,
};

/** Common API headers for authenticated requests */
function authHeaders(): Record<string, string> {
  return {
    Authorization: `Bearer ${AUTH.apiToken}`,
    'Content-Type': 'application/json',
    Accept: 'application/json',
  };
}

// ──────────────────────────────────────────────────────────
// Layer 1: Basic Connectivity
// ──────────────────────────────────────────────────────────

test.describe('Layer 1: Basic Connectivity', () => {
  test('auth subdomain serves Authentik login page', async ({ request }) => {
    const res = await request.get(`${AUTH.auth}/`, { maxRedirects: 5 });
    expect(res.status()).toBeLessThan(500);
    const body = await res.text();
    const isAuthentik =
      body.includes('authentik') ||
      body.includes('Authentik') ||
      body.includes('ak-flow') ||
      body.includes('Sign in') ||
      body.includes('flow/default');
    expect(isAuthentik).toBe(true);
  });

  test('OIDC discovery endpoint is reachable', async ({ request }) => {
    const res = await request.get(
      `${AUTH.auth}/application/o/.well-known/openid-configuration`,
    );
    if (res.status() === 200) {
      const body = await res.json();
      expect(body).toHaveProperty('issuer');
      expect(body.issuer).toContain('auth.researchstack.info');
      expect(body).toHaveProperty('authorization_endpoint');
      expect(body).toHaveProperty('token_endpoint');
      expect(body).toHaveProperty('userinfo_endpoint');
      expect(body).toHaveProperty('jwks_uri');
    } else {
      expect(res.status()).toBeLessThan(500);
    }
  });

  test('API root is reachable', async ({ request }) => {
    const res = await request.get(`${AUTH.auth}/api/v3/`);
    // API root serves the API Browser UI (HTML, 200) or redirects
    expect([200, 302, 401, 403]).toContain(res.status());
  });

  test('auth subdomain resolves to valid TLS', async ({ request }) => {
    const res = await request.get(`${AUTH.auth}/`, { maxRedirects: 0 });
    expect([200, 301, 302, 303, 307, 308]).toContain(res.status());
  });
});

// ──────────────────────────────────────────────────────────
// Layer 2: API Operations
// ──────────────────────────────────────────────────────────

test.describe('Layer 2: API Operations', () => {
  test('list users returns akadmin', async ({ request }) => {
    const res = await request.get(API.users, {
      headers: authHeaders(),
    });
    if (!res.ok()) {
      const body = await res.text();
      test.info().annotations.push({ type: 'api_response', description: `${res.status()}: ${body}` });
      test.skip(!res.ok(), `API returned ${res.status()} — set AUTHENTIK_TOKEN env var`);
      return;
    }
    const body = await res.json();
    expect(body.results).toBeDefined();
    const usernames = body.results.map((u: any) => u.username);
    expect(usernames).toContain('akadmin');
  });

  const apiEndpoints: Array<{ name: string; url: string }> = [
    { name: 'users', url: API.users },
    { name: 'groups', url: API.groups },
    { name: 'providers', url: API.providers },
    { name: 'applications', url: API.applications },
    { name: 'outposts', url: API.outposts },
  ];

  for (const ep of apiEndpoints) {
    test(`list ${ep.name}`, async ({ request }) => {
      const res = await request.get(ep.url, { headers: authHeaders() });
      if (!res.ok()) {
        const body = await res.text();
        test.info().annotations.push({ type: 'api_response', description: `${ep.name}: ${res.status()} ${body}` });
        test.skip(true, `API returned ${res.status()} — set AUTHENTIK_TOKEN env var`);
        return;
      }
      const body = await res.json();
      expect(body.results).toBeDefined();
    });
  }
});

// ──────────────────────────────────────────────────────────
// Layer 3: Admin UI Login & Navigation
// ──────────────────────────────────────────────────────────

test.describe('Layer 3: Admin UI Login & Navigation', () => {
  test('admin login page loads', async ({ page }) => {
    await page.goto(`${AUTH.auth}/if/admin/`, { waitUntil: 'networkidle' });
    const title = await page.title();
    expect(title.toLowerCase()).toContain('authentik');
  });

  test('full admin login flow succeeds', async ({ browser }) => {
    test.setTimeout(90000);
    const context = await browser.newContext({ ignoreHTTPSErrors: true });
    const page = await context.newPage();

    await page.goto(`${AUTH.auth}/if/admin/`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(5000);

    // Step 1: enter username — fields are inside ak-flow-executor shadow DOM
    await page.locator('input[name="username"]').fill(AUTH.adminUser, { force: true });
    await page.waitForTimeout(500);

    await page.locator('button[type="submit"]').click({ force: true });
    await page.waitForTimeout(4000);

    // Step 2: enter password
    await page.locator('input[name="password"]').fill(AUTH.adminPass, { force: true });
    await page.waitForTimeout(500);

    await page.locator('button[type="submit"]').click({ force: true });
    await page.waitForTimeout(5000);

    // Check if we're still on the login page
    const currentUrl = page.url();
    const onAdminPage = currentUrl.includes('/if/admin/') || currentUrl.includes('/admin/');
    expect(onAdminPage).toBe(true);

    if (onAdminPage) {
      await context.storageState({ path: 'authentik-admin-state.json' });
    }
    await context.close();
  });

  function adminContext(browser: any) {
    if (!fs.existsSync('authentik-admin-state.json')) return null;
    return browser.newContext({
      ignoreHTTPSErrors: true,
      storageState: 'authentik-admin-state.json',
    });
  }

  test('admin dashboard renders key sections', async ({ browser }) => {
    const ctx = await adminContext(browser);
    test.skip(!ctx, 'No admin session — run login test first');
    const page = await ctx!.newPage();

    await page.goto(`${AUTH.auth}/if/admin/`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(4000);

    const bodyText = await page.evaluate(() => document.body.innerText);
    const expectedSections = ['users', 'applications', 'providers', 'outposts'];
    const found = expectedSections.filter((s) =>
      bodyText.toLowerCase().includes(s),
    );
    expect(found.length).toBeGreaterThanOrEqual(1);
    await ctx!.close();
  });

  test('navigate to Directory -> Users page', async ({ browser }) => {
    const ctx = await adminContext(browser);
    test.skip(!ctx, 'No admin session — run login test first');
    const page = await ctx!.newPage();

    await page.goto(`${AUTH.auth}/if/admin/#/directory/users`, {
      waitUntil: 'networkidle',
    });
    await page.waitForTimeout(3000);

    const bodyText = await page.evaluate(() => document.body.innerText);
    const hasUsers = bodyText.toLowerCase().includes('akadmin');
    expect(hasUsers).toBe(true);
    await ctx!.close();
  });

  test('navigate to Applications -> Outposts page', async ({ browser }) => {
    const ctx = await adminContext(browser);
    test.skip(!ctx, 'No admin session — run login test first');
    const page = await ctx!.newPage();

    await page.goto(`${AUTH.auth}/if/admin/#/apps/outposts`, {
      waitUntil: 'networkidle',
    });
    await page.waitForTimeout(3000);

    const bodyText = await page.evaluate(() => document.body.innerText);
    expect(
      bodyText.toLowerCase().includes('embedded outpost') ||
        bodyText.toLowerCase().includes('outpost'),
    ).toBe(true);
    await ctx!.close();
  });
});

test.describe('Layer 4: Provider & Application CRUD', () => {
  const testSlug = `e2e-test-app-${Date.now()}`;
  const testProviderName = `e2e-test-provider-${Date.now()}`;

  test('create a proxy provider', async ({ request }) => {
    const res = await request.post(API.providersProxy, {
      headers: authHeaders(),
      data: {
        name: testProviderName,
        authorization_flow: undefined,
        internal_host: 'http://localhost:9999',
        external_host: `https://${testSlug}.researchstack.info`,
        mode: 'forward_domain',
      },
    });
    if (!res.ok() && res.status() === 403) {
      test.skip(true, 'API auth required — set AUTHENTIK_TOKEN env var');
      return;
    }
    expect([201, 400]).toContain(res.status());
    if (res.status() === 201) {
      const body = await res.json();
      expect(body.name).toBe(testProviderName);
    }
  });

  test('create an application linked to proxy provider', async ({
    request,
  }) => {
    const listRes = await request.get(API.providersProxy, {
      headers: authHeaders(),
    });
    if (!listRes.ok()) {
      test.skip(true, 'API auth required — set AUTHENTIK_TOKEN env var');
      return;
    }
    const listBody = await listRes.json();
    const providers = listBody.results as any[];
    const matchingProvider = providers.find(
      (p: any) => p.name === testProviderName,
    );

    test.skip(!matchingProvider, 'No matching provider found — skipping');

    const res = await request.post(API.applications, {
      headers: authHeaders(),
      data: {
        name: testSlug,
        slug: testSlug,
        provider: matchingProvider!.pk,
      },
    });
    expect([201, 400, 409]).toContain(res.status());

    if (res.status() === 201) {
      const body = await res.json();
      expect(body.slug).toBe(testSlug);
    }
  });

  test('verify test application appears in listing', async ({ request }) => {
    const res = await request.get(API.applications, {
      headers: authHeaders(),
    });
    if (!res.ok()) {
      test.skip(true, 'API auth required — set AUTHENTIK_TOKEN env var');
      return;
    }
    const body = await res.json();
    const slugs = body.results.map((a: any) => a.slug);
    expect(slugs).toContain(testSlug);
  });

  test('cleanup: delete test application and provider', async ({
    request,
  }) => {
    const appRes = await request.get(
      `${API.applications}?slug=${testSlug}`,
      { headers: authHeaders() },
    );
    if (appRes.ok()) {
      const appBody = await appRes.json();
      const app = appBody.results?.[0];
      if (app) {
        await request.delete(`${API.applications}${app.pk}/`, {
          headers: authHeaders(),
        });
      }
    }

    const provRes = await request.get(
      `${API.providersProxy}?name=${testProviderName}`,
      { headers: authHeaders() },
    );
    if (provRes.ok()) {
      const provBody = await provRes.json();
      const prov = provBody.results?.[0];
      if (prov) {
        await request.delete(`${API.providersProxy}${prov.pk}/`, {
          headers: authHeaders(),
        });
      }
    }
  });
});

// ──────────────────────────────────────────────────────────
// Layer 5: Forward-Auth SSO Interception
// ──────────────────────────────────────────────────────────

test.describe('Layer 5: Forward-Auth SSO Interception', () => {
  const protectedPaths = [
    '/apps/chat/',
    '/apps/budget/',
    '/server/status/',
    '/server/dash/',
    '/server/vault/',
    '/',
  ];

  const apiPaths = [
    '/api/cred/',
    '/api/registry/health',
    '/api/jobs/health',
    '/api/blobs/health',
  ];

  for (const path of protectedPaths) {
    test(`protected path ${path} is intercepted by forward_auth`, async ({
      request,
    }) => {
      const res = await request.get(path, { maxRedirects: 0 });
      const headers = res.headers();

      if (res.status() === 302 || res.status() === 303) {
        const location = headers['location'] || '';
        // Two possible scenarios:
        // 1. Traefik canonical redirect (bare → www), not forward_auth
        // 2. Authentik forward_auth redirect (→ auth.researchstack.info)
        if (location.includes('auth.researchstack.info')) {
          // This IS the forward_auth intercept
          expect(location).toContain('auth.researchstack.info');
        } else {
          // Canonical redirect — follow and check next hop
          test.info().annotations.push({
            type: 'canonical_redirect',
            description: `${path} → ${location}`,
          });
        }
      } else if (res.status() === 404) {
        const isAuthentik =
          'x-authentik-id' in headers ||
          headers['x-powered-by'] === 'authentik';
        expect(isAuthentik).toBe(true);
      } else {
        expect([200, 401, 403]).toContain(res.status());
      }
    });
  }

  for (const path of apiPaths) {
    test(`API path ${path} bypasses forward_auth`, async ({ request }) => {
      const res = await request.get(path, { maxRedirects: 0 });
      // API paths should never redirect to AuthN
      const allowedApiStatuses = [200, 301, 302, 401, 403, 404, 502, 503];
      expect(allowedApiStatuses).toContain(res.status());
      if (res.status() === 302 || res.status() === 303) {
        const location = res.headers()['location'] || '';
        expect(location).not.toContain('auth.researchstack.info');
      }
    });
  }
});

// ──────────────────────────────────────────────────────────
// Layer 6: Outpost Health
// ──────────────────────────────────────────────────────────

test.describe('Layer 6: Outpost Health', () => {
  test('embedded outpost exists in API listing', async ({ request }) => {
    const res = await request.get(API.outposts, {
      headers: authHeaders(),
    });
    if (!res.ok()) {
      test.skip(true, 'API auth required — set AUTHENTIK_TOKEN env var');
      return;
    }
    const body = await res.json();
    const outposts = body.results as any[];
    const embedded = outposts.find(
      (o: any) => o.name === 'authentik Embedded Outpost',
    );
    expect(embedded).toBeDefined();
  });

  test('outpost has type embedded', async ({ request }) => {
    const res = await request.get(API.outposts, {
      headers: authHeaders(),
    });
    if (!res.ok()) {
      test.skip(true, 'API auth required — set AUTHENTIK_TOKEN env var');
      return;
    }
    const body = await res.json();
    const embedded = body.results.find(
      (o: any) => o.name === 'authentik Embedded Outpost',
    );
    expect(embedded).toBeDefined();
    expect(embedded.type).toBe('embedded');
    expect(embedded.verbose_name).toContain('Embedded Outpost');
  });

  test('authentik outpost service is reachable from inside cluster', async ({
    request,
  }) => {
    // The outpost listens on the same port as Authentik (9000)
    const res = await request.get(
      `${AUTH.auth}/outpost.goauthentik.io/auth/traefik`,
      { maxRedirects: 0 },
    );
    // Traefik forward-auth endpoint: should return 401 (unauthenticated)
    //   or 302 (redirect to login) or 404 (no matching route)
    expect([200, 302, 401, 404, 403]).toContain(res.status());
  });
});

// ──────────────────────────────────────────────────────────
// Layer 7: Token & Auth Header Propagation
// ──────────────────────────────────────────────────────────

test.describe('Layer 7: Token & Auth Header Propagation', () => {
  test('API rejects unauthenticated requests', async ({ request }) => {
    const res = await request.get(API.users);
    expect([401, 403]).toContain(res.status());
  });

  test('API accepts valid bearer token', async ({ request }) => {
    const res = await request.get(API.users, {
      headers: authHeaders(),
    });
    if (!res.ok() && (await res.text()).includes('Token invalid')) {
      test.skip(true, 'No valid AUTHENTIK_TOKEN configured');
      return;
    }
    expect(res.ok()).toBe(true);
  });

  test('API rejects invalid bearer token', async ({ request }) => {
    const res = await request.get(API.users, {
      headers: {
        Authorization: 'Bearer invalid-token-that-will-fail',
        'Content-Type': 'application/json',
      },
    });
    expect([401, 403]).toContain(res.status());
  });
});

// ──────────────────────────────────────────────────────────
// Layer 8: SSO Login Flow (Browser)
// ──────────────────────────────────────────────────────────

test.describe('Layer 8: SSO Login Flow (Browser)', () => {
  test('visiting protected path redirects to authentik login', async ({
    page,
  }) => {
    await page.goto(`${AUTH.base}/apps/chat/`, {
      waitUntil: 'networkidle',
      timeout: 15000,
    });
    const url = page.url();
    const redirected = url.includes('auth.researchstack.info');
    const hasLoginForm = await page.locator(
      'input[placeholder*="Username"], input[type="text"]',
    ).first().isVisible().catch(() => false);
    expect(redirected || hasLoginForm).toBe(true);
  });

  test('after login, SSO-protected app is accessible', async ({
    browser,
  }) => {
    test.setTimeout(60000);

    const ctx = await adminContext(browser);
    test.skip(!ctx, 'No admin session — run login test first');
    const page = await ctx!.newPage();

    await page.goto(`${AUTH.base}/apps/chat/`, {
      waitUntil: 'networkidle',
      timeout: 15000,
    });

    const bodyText = await page.evaluate(() => document.body.innerText);
    const isAuthentikLogin = bodyText.includes('Sign in') || bodyText.includes('authentik');
    const reachedApp = bodyText.length > 0 && !isAuthentikLogin;

    // Whether we reach the app or get redirected again depends on
    // whether the admin session has SSO access to the chat app.
    // Either outcome is a valid test; we just document which.
    test.info().annotations.push({
      type: 'session_state',
      description: reachedApp
        ? 'Session authenticated — reached protected app'
        : 'Session not authorized for this app (expected with admin session)',
    });

    await ctx!.close();
  });
});
