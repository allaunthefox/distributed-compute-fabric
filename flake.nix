{
  description = "Unified NixOS k3s topology — Research Stack. Zero embedded IPs or secrets.";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.05";
    sops-nix = {
      url = "github:Mic92/sops-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, sops-nix }:
    let
      lib = nixpkgs.lib;
      system = "x86_64-linux";

      caddyPorkbun = import ./pkgs/caddy-porkbun.nix {
        pkgs = nixpkgs.legacyPackages.${system};
      };

      mkNode = { hostName, extraModules ? [ ], serverAddr ? null, domain ? null }:
        assert hostName != "";
        nixpkgs.lib.nixosSystem {
          inherit system;
          specialArgs = { inherit hostName serverAddr domain caddyPorkbun; };
          modules = [
            sops-nix.nixosModules.sops
            ./k3s-configuration.nix
          ] ++ extraModules;
        };
    in {
      nixosConfigurations = {
        # ── NixOS storage node (NixOS 26.05, 459GB NVMe, ord zone) ─────────
        # ACTUAL ROLE: k3s agent joining cupfox (100.110.163.82:6443)
        # HISTORICAL NOTE: was originally standalone k3s server, migrated to
        # agent when cupfox was promoted. The k3s-server.nix in this repo
        # reflects the current agent setup.
        k3s-server = mkNode {
          hostName = "nixos";
          domain = "researchstack.info";
          serverAddr = "https://100.110.163.82:6443"; # cupfox control-plane
          extraModules = [ ./k3s-server.nix ];
        };

        # ── Foxtop compute node ───────────────────────────────────────────
        # ACTUAL: qfox-1 (CachyOS, joined via join-agent.sh, NOT NixOS)
        # NixOS config kept for reference / future bare-metal install
        k3s-foxtop = mkNode {
          hostName = "qfox-1";
          serverAddr = "https://100.110.163.82:6443"; # cupfox, not nixos
          extraModules = [ ./roles/foxtop.nix ];
        };

        # ── Mirror node (DEAD) ────────────────────────────────────────────
        # 361395-1 was a netcup VPS that is no longer in the cluster.
        # neon-64gb (ARM64, 2TB) replaced it as netcup presence.
        # Kept as reference; do not deploy.
        # k3s-mirror = mkNode {
        #   hostName = "361395-1";
        #   serverAddr = "https://100.110.163.82:6443";
        #   extraModules = [ ./roles/mirror.nix ];
        # };

        # ── Edge TLS node (racknerd, 9GB VPS, us-va) ──────────────────────
        # Caddy TLS termination + Porkbun DNS-01 + subdomain redirects
        # Forwards AL traffic to internal router at nixos:80
        k3s-edge = mkNode {
          hostName = "microvm-racknerd";
          domain = "researchstack.info";
          serverAddr = "https://100.110.163.82:6443"; # cupfox
          extraModules = [ ./k3s-edge.nix ];
        };

        # ── GPU compute node (steamdeck, ROG Ally, 476GB NVMe, gpu zone) ──
        # Runs CUDA/ML workloads. Has NVIDIA GPU via device plugin.
        # NOTE: steamdeck NixOS version is 25.11, may need different nixpkgs
        k3s-core = mkNode {
          hostName = "nixos-steamdeck-1";
          serverAddr = "https://100.110.163.82:6443"; # cupfox
          extraModules = [ ./roles/core.nix ];
        };

        # ── Neon node (ARM64, 2TB NVMe, heavy compute) ─────────────────────
        # ARM64 server for Hermes LLM inference
        # Hosts GGUF models via hostPath, Garage for persistence/backup
        # Tailscale: 100.100.75.113, Public: 152.53.81.164
        k3s-neon = mkNode {
          hostName = "neon-64gb";
          serverAddr = "https://100.110.163.82:6443"; # cupfox control-plane
          extraModules = [ ./roles/neon.nix ];
        };

        # ── Judge node (VOTEK/Adversarial review) ─────────────────────────
        # TBD - not yet assigned hardware
        # k3s-judge = mkNode {
        #   hostName = "";
        #   serverAddr = "";
        #   extraModules = [ ./roles/judge.nix ];
        # };
      };

      packages.${system} = {
        nixos-anywhere = nixpkgs.legacyPackages.${system}.nixos-anywhere;
        caddy-porkbun = caddyPorkbun;
      };

      apps.${system}.install-edge = {
        type = "app";
        program = "${nixpkgs.legacyPackages.${system}.writeShellScript "install-edge" ''
          set -euo pipefail
          TARGET="''${1:-}"
          if [ -z "$TARGET" ]; then
            echo "Usage: nix run .#install-edge -- root@172.245.19.182"
            exit 1
          fi
          exec nix run github:nix-community/nixos-anywhere -- \
            --flake .#k3s-edge "$TARGET"
        ''}";
      };
    };
}
