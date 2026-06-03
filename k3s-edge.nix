{ config, pkgs, lib, hostName, serverAddr, domain ? "researchstack.info", caddyPorkbun ? pkgs.caddy, ... }:

let
  mailDomain = domain;
  # Internal router target (k3s-server / nixos-laptop over Tailscale)
  internalRouter = "100.102.173.61:80";
  sendAlert = pkgs.writeShellScriptBin "send-alert" ''
    set -euo pipefail
    subject="''${1:-Alert}"
    body="''${2:-No details}"
    to="''${ALERT_TO:-allaun@${mailDomain}}"
    from="''${ALERT_FROM:-allaun@${mailDomain}}"

    if [ ! -s /etc/msmtp/protonmail-password ]; then
      echo "missing /etc/msmtp/protonmail-password" >&2
      exit 1
    fi

    printf 'From: %s\nTo: %s\nSubject: %s\n\n%s\n' "$from" "$to" "$subject" "$body" \
      | ${pkgs.msmtp}/bin/msmtp -a default -- "$to"
  '';
in
{
  imports = [
    ./roles/edge.nix
  ];

  # Disk layout — matches current microvm-racknerd partition table
  boot.loader.grub.devices = lib.mkDefault [ "/dev/vda" ];
  boot.loader.grub.enable = true;
  fileSystems."/" = lib.mkDefault {
    device = "/dev/vda1";
    fsType = "ext4";
  };
  swapDevices = lib.mkDefault [ { device = "/dev/vda2"; } ];

  networking.hostName = lib.mkDefault hostName;
  networking.domain = lib.mkDefault mailDomain;

  # ── Postfix (mail stays on edge — non-HTTP protocol) ─────────────────────
  services.postfix = {
    enable = true;
    hostname = "mail.${mailDomain}";
    domain = mailDomain;
    origin = mailDomain;
    destination = [ mailDomain ];
    networks = [ "127.0.0.0/8" ];

    extraConfig = ''
      mailbox_command = ${pkgs.dovecot}/libexec/dovecot/deliver
      home_mailbox = Maildir/
    '';
  };

  # ── Dovecot ───────────────────────────────────────────────────────────────
  services.dovecot2 = {
    enable = true;
    enableImap = true;
    enablePop3 = false;

    extraConfig = ''
      ssl = yes
      ssl_prefer_server_ciphers = yes
      ssl_min_protocol = TLSv1.2
      mail_location = maildir:/var/mail/%n
      auth_mechanisms = plain login
      passdb {
        driver = passwd-file
        args = /etc/dovecot/users
      }
      userdb {
        driver = static
        args = uid=5000 gid=5000 home=/var/mail/%n
      }
    '';
  };

  users.users.postmaster = {
    isSystemUser = true;
    uid = 5000;
    group = "postmaster";
    home = "/var/mail/postmaster";
    createHome = true;
  };
  users.groups.postmaster = {
    gid = 5000;
    members = [ "postmaster" ];
  };

  # ── msmtp alert relay ────────────────────────────────────────────────────
  environment.etc."msmtprc".text = ''
    defaults
    auth           login
    tls            on
    tls_starttls   on
    tls_certcheck  off

    account        protonmail
    host           127.0.0.1
    port           1025
    from           allaun@${mailDomain}
    user           allaun@${mailDomain}
    passwordeval   cat /etc/msmtp/protonmail-password

    account default: protonmail
  '';
  environment.etc."msmtprc".mode = "0600";

  systemd.tmpfiles.rules = [
    "d /etc/msmtp 0700 root root -"
  ];

  environment.etc."profile.d/research-stack-alerts.sh".text = ''
    export ALERT_FROM=''${ALERT_FROM:-allaun@${mailDomain}}
    export ALERT_TO=''${ALERT_TO:-allaun@${mailDomain}}
  '';

  environment.systemPackages = with pkgs; [
    msmtp
    sendAlert
    socat
  ];

  # ── Caddy — Public TLS edge ──────────────────────────────────────────────
  # This is a "dumb TLS edge": terminates TLS for researchstack.info +
  # *.researchstack.info via Porkbun DNS-01 challenge, then forwards ALL
  # HTTP traffic to the internal Caddy router over Tailscale.
  #
  # Exceptions:
  #   - auth.researchstack.info → forwarded with Host preserved (OIDC issuer)
  #   - mail/webmail subdomains → forwarded to internal router
  #
  # No path routing logic lives here. Traefik (k3s built-in) handles all
  # path-based routing inside the cluster via Ingress resources.
  systemd.services.caddy.serviceConfig.EnvironmentFile = [ "/etc/caddy/porkbun.env" ];

  sops.secrets.porkbun-env = {
    sopsFile = ./secrets/porkbun-env.age;
    format = "yaml";
    path = "/etc/caddy/porkbun.env";
  };

  services.caddy = {
    enable = true;
    package = caddyPorkbun;
    extraConfig = ''
      (porkbun_tls) {
        tls {
          ca https://acme-v02.api.letsencrypt.org/directory
          dns porkbun {
            api_key {$PORKBUN_API_KEY}
            api_secret_key {$PORKBUN_SECRET_KEY}
          }
        }
      }

      # Primary domain — forward everything to Traefik on k3s-server
      researchstack.info {
        import porkbun_tls
        reverse_proxy ${internalRouter} {
          header_up Host {host}
          header_up X-Real-IP {remote}
          header_up X-Forwarded-For {remote}
          header_up X-Forwarded-Proto {scheme}
          header_up X-Forwarded-Host {host}
        }
      }

      # Auth subdomain — stable OIDC issuer (preserved, not redirected)
      auth.${domain} {
        import porkbun_tls
        reverse_proxy ${internalRouter} {
          header_up Host auth.${domain}
          header_up X-Real-IP {remote}
          header_up X-Forwarded-For {remote}
          header_up X-Forwarded-Proto {scheme}
          header_up X-Forwarded-Host auth.${domain}
        }
      }

      # Mail subdomains — forward to Traefik (mail Ingress pending)
      mail.${domain}, webmail.${domain} {
        import porkbun_tls
        reverse_proxy ${internalRouter} {
          header_up Host {host}
          header_up X-Real-IP {remote}
          header_up X-Forwarded-For {remote}
          header_up X-Forwarded-Proto {scheme}
          header_up X-Forwarded-Host {host}
        }
      }

      # Legacy subdomain catch-all — 301 to canonical paths
      # These exist for bookmark/client compat during migration.
      status.${domain} {
        import porkbun_tls
        redir https://${domain}/server/status{uri} 301
      }

      dash.${domain}, home.${domain} {
        import porkbun_tls
        redir https://${domain}/ 301
      }

      media.${domain} {
        import porkbun_tls
        redir https://${domain}/apps/jellyfin{uri} 301
      }

      books.${domain} {
        import porkbun_tls
        redir https://${domain}/apps/books{uri} 301
      }

      music.${domain} {
        import porkbun_tls
        redir https://${domain}/apps/music{uri} 301
      }

      vault.${domain} {
        import porkbun_tls
        redir https://${domain}/server/vault{uri} 301
      }

      pulse.${domain} {
        import porkbun_tls
        redir https://${domain}/api/registry{uri} 301
      }

      apps.${domain} {
        import porkbun_tls
        redir https://${domain}/apps{uri} 301
      }

      chat.${domain} {
        import porkbun_tls
        redir https://${domain}/apps/chat{uri} 301
      }

      budget.${domain} {
        import porkbun_tls
        redir https://${domain}/apps/budget{uri} 301
      }

      www.${domain} {
        import porkbun_tls
        redir https://${domain}{uri} 301
      }

      # Wildcard fallback — anything else gets a redirect to root
      *.${domain} {
        import porkbun_tls
        redir https://${domain}{uri} 301
      }
    '';
  };

  # ── Firewall ──────────────────────────────────────────────────────────────
  networking.firewall.allowedTCPPorts = [
    25 143 465 587 993   # Mail protocols (Postfix + Dovecot)
  ];

}
