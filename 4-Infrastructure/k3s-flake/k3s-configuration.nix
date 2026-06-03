{ config, pkgs, lib, hostName, serverAddr, domain, ... }:

{
  ##########################################################################
  # EDIT HERE — fill in hostName, serverAddr, and domain
  # hostName must be set for every node.
  # serverAddr is required for agent nodes. domain is required for the server.
  #
  # Bootstrap workflow:
  #   1. Pre-generate a k3s token: openssl rand -hex 32
  #   2. Encrypt it with age as secrets/k3s-token.age
  #      (format: K3S_TOKEN=<token>)
  #   3. Deploy the server first. If no K3S_TOKEN is set, k3s auto-generates.
  #   4. For agents, set the token from step 1.
  ##########################################################################

  sops.age.keyFile = "/var/lib/sops-nix/key.txt";

  sops.secrets.k3s-token = {
    sopsFile = ./secrets/k3s-token.age;
    format = "yaml";
  };

  systemd.services.k3s.serviceConfig.EnvironmentFile = [
    config.sops.secrets.k3s-token.path
  ];

  networking.hostName = lib.mkDefault hostName;
  networking.networkmanager.enable = true;
  networking.nameservers = [ "1.1.1.1" "8.8.8.8" ];

  time.timeZone = lib.mkDefault "UTC";

  nix.settings = {
    experimental-features = [ "nix-command" "flakes" ];
    auto-optimise-store = true;
  };
  nix.gc = {
    automatic = true;
    dates = "weekly";
    options = "--delete-older-than 7d";
  };

  services.tailscale.enable = true;

  networking.firewall = {
    enable = true;
    allowedTCPPorts = [ 22 80 443 6443 2379 2380 10250 10259 10257 30800 30801 30802 30803 30804 ];
    trustedInterfaces = [ "tailscale0" ];
    allowedUDPPorts = [ 51820 8472 ];
  };

  environment.systemPackages = with pkgs; [
    curl
    ffmpeg
    flac
    git
    htop
    jq
    k3s
    kubectl
    openssl
    ripgrep
    tailscale
    vim
    wget
  ];
}
