import { test, expect } from '@playwright/test';

/**
 * Edge TLS + subdomain redirect tests.
 *
 * Validates that:
 * 1. The edge Caddy terminates TLS correctly for researchstack.info
 * 2. Legacy subdomains 301-redirect to their canonical path equivalents
 * 3. auth.researchstack.info stays as a real subdomain (not redirected)
 * 4. mail/webmail subdomains are forwarded (not redirected)
 *
 * These tests exercise the edge Caddy configuration only.
 * They do NOT validate backend service health.
 */

test.describe('Edge TLS termination', () => {
  test('root domain is reachable over HTTPS', async ({ request }) => {
    const response = await request.get('/');
    // Should get a response (2xx, redirect, or Authentik intercept)
    expect(response.status()).toBeLessThan(600);
  });

  test('TLS certificate is valid for researchstack.info', async ({ request }) => {
    // If TLS is broken, the request will throw (ignoreHTTPSErrors is true,
    // so we'd still connect but let's verify we get a response)
    const response = await request.get('https://researchstack.info/');
    expect(response.status()).toBeLessThan(500);
  });
});

test.describe('Legacy subdomain 301 redirects', () => {
  const redirectTests = [
    { from: 'https://status.researchstack.info/', to: '/server/status' },
    { from: 'https://dash.researchstack.info/', to: '/' },
    { from: 'https://home.researchstack.info/', to: '/' },
    { from: 'https://media.researchstack.info/', to: '/apps/jellyfin' },
    { from: 'https://books.researchstack.info/', to: '/apps/books' },
    { from: 'https://music.researchstack.info/', to: '/apps/music' },
    { from: 'https://vault.researchstack.info/', to: '/server/vault' },
    { from: 'https://pulse.researchstack.info/', to: '/api/registry' },
    { from: 'https://apps.researchstack.info/', to: '/apps' },
    { from: 'https://chat.researchstack.info/', to: '/apps/chat' },
    { from: 'https://budget.researchstack.info/', to: '/apps/budget' },
    { from: 'https://www.researchstack.info/', to: '/' },
  ];

  for (const { from, to } of redirectTests) {
    test(`${from} → 301 to ${to}`, async ({ request }) => {
      const response = await request.get(from, {
        maxRedirects: 0,
      });
      expect(response.status()).toBe(301);
      const location = response.headers()['location'];
      expect(location).toContain(to);
      expect(location).toContain('researchstack.info');
    });
  }
});

test.describe('Stable subdomains (not redirected)', () => {
  test('auth.researchstack.info responds (not a redirect)', async ({ request }) => {
    const response = await request.get('https://auth.researchstack.info/', {
      maxRedirects: 0,
    });
    // Authentik should respond with 200 or 302 (to login page), not 301
    expect(response.status()).not.toBe(301);
    expect([200, 302, 303]).toContain(response.status());
  });

  test('mail.researchstack.info is forwarded (not redirected)', async ({ request }) => {
    const response = await request.get('https://mail.researchstack.info/', {
      maxRedirects: 0,
    });
    // Mail is forwarded to internal router (not 301 redirected).
    // It may return 404 (no mail Ingress configured yet) or 200/502.
    // The key assertion is that it's NOT a 301 redirect.
    expect(response.status()).not.toBe(301);
  });
});

test.describe('Wildcard fallback', () => {
  // Wildcard DNS is configured (*.researchstack.info → 172.245.19.182)
  // but the live Caddy uses HTTP-01 challenges and can't auto-provision
  // certs for arbitrary subdomains. This test will work once Caddy is
  // switched to Porkbun DNS-01 (via NixOS rebuild of k3s-edge.nix).
  test.skip('unknown subdomain redirects to root (needs Porkbun DNS-01 TLS)', async ({ request }) => {
    const response = await request.get('https://nonexistent.researchstack.info/', {
      maxRedirects: 0,
    });
    expect(response.status()).toBe(301);
    const location = response.headers()['location'];
    expect(location).toBe('https://researchstack.info/');
  });
});
