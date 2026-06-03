{ config, pkgs, lib, hostName, serverAddr, domain, ... }:

{
  services.k3s = {
    enable = true;
    role = "agent";
    serverAddr = serverAddr;
    nodeLabels = {
      "topology.researchstack.io/role" = "core";
      "topology.researchstack.io/gpu" = "true";
      "topology.researchstack.io/storage-tier" = "nvme-ssd";
      "topology.researchstack.io/compute-class" = "core";
    };
    extraFlags = [
      "--node-ip=100.85.244.73"
    ];
  };
}
