{ config, pkgs, lib, hostName, serverAddr, domain, ... }:

{
  services.k3s = {
    enable = true;
    role = "agent";
    serverAddr = serverAddr;
    tokenFile = config.sops.secrets.k3s-token.path;
    extraFlags = [
      "--node-ip=100.101.247.127"
      "--node-label=topology.researchstack.io/role=edge"
      "--node-label=topology.researchstack.io/gpu=false"
      "--node-label=topology.researchstack.io/storage-tier=vps-ssd"
      "--node-label=topology.researchstack.io/compute-class=edge"
      "--node-taint=pulse-only=true:NoSchedule"
    ];
  };
}
