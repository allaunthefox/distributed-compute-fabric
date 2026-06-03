{ config, pkgs, lib, hostName, serverAddr, domain, ... }:

{
  ##########################################################################
  # k3s-server.nix — NixOS storage + k3s AGENT node
  #
  # cupfox (100.110.163.82) remains the SOLE control-plane server.
  # nixos-laptop joins as AGENT, runs host Caddy that forwards to cupfox.
  # Traefik runs on cupfox (not disabled), handles all Ingress routing.
  #
  # Architecture:
  #   cupfox (Debian, 100.110.163.82) — CONTROL PLANE (sole server, runs Traefik)
  #   nixos (NixOS, 100.102.173.61) — AGENT node, host Caddy forwarder
  #   qfox-1 (CachyOS, agent) — foxtop compute, runs VCN/LUPINE daemons
  #   steamdeck (NixOS, agent) — GPU node
  #   racknerd (Debian, edge) — Caddy TLS termination
  #
  # All nodes share the SAME k3s cluster via embedded etcd on cupfox (SQLite).
  # No etcd cluster = no thundering herd problem.
  #
  # Traffic flow:
  #   edge Caddy (racknerd:443) → host Caddy (nixos:80) → Traefik (cupfox:80) → Services
  #   (Services may run on cupfox, nixos, qfox-1, steamdeck, etc.)
  #
  # Ray integration:
  #   Ray cluster runs in ray-system namespace (deployed separately via KubeRay)
  #   Ray dashboard exposed via IngressRoute at /server/ray
  #
  # VCN/LUPINE integration:
  #   Runs as separate daemons on GPU nodes (qfox-1, steamdeck)
  #   Not managed by k3s — uses LD_PRELOAD shim + IPC socket
  ##########################################################################

  sops.secrets.k3s-token = {
    sopsFile = ./secrets/k3s-token.age;
    format = "yaml";
  };

  systemd.services.k3s.serviceConfig.EnvironmentFile = [
    config.sops.secrets.k3s-token.path
  ];

  # ── k3s as AGENT joining CUPFOX control plane ────────────────────────────
  # cupfox is the sole server. This node joins as agent.
  # No etcd on this node — cupfox uses embedded SQLite (single-server mode).
  services.k3s = {
    enable = true;
    role = "agent";  # AGENT (not server) — cupfox is the only server
    serverAddr = serverAddr or "https://100.110.163.82:6443";  # cupfox control-plane
    tokenFile = config.sops.secrets.k3s-token.path;
    extraFlags = toString [
      "--node-ip=100.102.173.61"
      "--node-external-ip=100.102.173.61"
      "--flannel-iface=tailscale0"
      "--node-label=topology.researchstack.info/role=storage"
      "--node-label=topology.researchstack.io/gpu=false"
      "--node-label=topology.researchstack.io/storage-tier=nvme-ssd"
    ];
  };

  # ── Host Caddy — Forwarder to Traefik on cupfox ─────────────────────────
  # Caddy listens on :80 (HTTP only, no TLS — TLS is at edge).
  # All requests forward to Traefik on cupfox (100.110.163.82:80) over Tailscale.
  # Traefik on cupfox handles path-based routing + forward_auth.
  services.caddy = {
    enable = true;
    package = pkgs.caddy;
    
    user = "root";
    group = "root";
    
    extraConfig = ''
      # Default global settings
      {
        admin 127.0.0.1:2019
        log {
          output stdout
          format single_field common_log
        }
      }
      
      # Primary domain — forward everything to Traefik on cupfox
      researchstack.info {
        # Traefik runs on cupfox:80 (k3s server with Traefik enabled)
        reverse_proxy 100.110.163.82:80 {
          header_up Host {host}
          header_up X-Real-IP {remote}
          header_up X-Forwarded-For {remote}
          header_up X-Forwarded-Proto {scheme}
          header_up X-Forwarded-Host {host}
        }
      }
      
      # Auth subdomain — stable OIDC issuer
      auth.researchstack.info {
        reverse_proxy 100.110.163.82:80 {
          header_up Host auth.researchstack.info
          header_up X-Real-IP {remote}
          header_up X-Forwarded-For {remote}
          header_up X-Forwarded-Proto {scheme}
          header_up X-Forwarded-Host auth.researchstack.info
        }
      }
      
      # Mail subdomains — forward to Traefik (future mail Ingress)
      mail.${domain}, webmail.${domain} {
        reverse_proxy 100.110.163.82:80 {
          header_up Host {host}
          header_up X-Real-IP {remote}
          header_up X-Forwarded-For {remote}
          header_up X-Forwarded-Proto {scheme}
          header_up X-Forwarded-Host {host}
        }
      }
      
      # Legacy subdomain redirects (for migration compatibility)
      status.${domain} {
        redir https://${domain}/server/status{uri} 301
      }
      
      dash.${domain}, home.${domain} {
        redir https://${domain}/ 301
      }
      
      media.${domain} {
        redir https://${domain}/apps/jellyfin{uri} 301
      }
      
      books.${domain} {
        redir https://${domain}/apps/books{uri} 301
      }
      
      music.${domain} {
        redir https://${domain}/apps/music{uri} 301
      }
      
      vault.${domain} {
        redir https://${domain}/server/vault{uri} 301
      }
      
      pulse.${domain} {
        redir https://${domain}/api/registry{uri} 301
      }
      
      apps.${domain} {
        redir https://${domain}/apps{uri} 301
      }
      
      chat.${domain} {
        redir https://${domain}/apps/chat{uri} 301
      }
      
      budget.${domain} {
        redir https://${domain}/apps/budget{uri} 301
      }
      
      www.${domain} {
        redir https://${domain}{uri} 301
      }
      
      # Ray subdomain (if needed for direct access)
      ray.${domain} {
        redir https://${domain}/server/ray{uri} 301
      }
      
      # Wildcard fallback
      *.${domain} {
        redir https://${domain}{uri} 301
      }
    '';
  };

  # ── Firewall — allow Caddy and k3s agent ports ───────────────────────────
  networking.firewall.allowedTCPPorts = [
    80      # host Caddy HTTP
  ];

  # ── Deploy manifests via systemd oneshot ─────────────────────────────────
  systemd.services.deploy-k3s-services = {
    description = "Deploy k3s services via kubectl apply";
    wantedBy = [ "multi-user.target" ];
    after = [ "k3s.service" ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = false;
    };
    script = ''
      set -euo pipefail
      
      KUBECONFIG=/etc/rancher/k3s/k3s.yaml
      KCTL=${pkgs.kubectl}/bin/kubectl
      MANIFEST_DIR=/etc/nixos/k3s-flake/manifests
      
      echo "Deploying manifests from $$MANIFEST_DIR..."
      $KCTL --kubeconfig=$$KUBECONFIG apply -k $$MANIFEST_DIR
      
      echo "Manifests deployed successfully"
    '';
  };

  services.tailscale.enable = true;
}
