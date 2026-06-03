# Caddy with Porkbun DNS-01 plugin for wildcard TLS on researchstack.info
# Static binary for portability across NixOS and non-NixOS hosts.
{ pkgs }:

pkgs.pkgsStatic.caddy.withPlugins {
  plugins = [ "github.com/caddy-dns/porkbun@v0.3.1" ];
  hash = "sha256-X11vSQRbBg25I1eSKF2O5QBRS7zGOtdGhLISiwrHclw=";
}
