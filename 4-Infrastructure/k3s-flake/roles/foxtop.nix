{ config, pkgs, lib, hostName, serverAddr, domain, ... }:

{
  services.k3s = {
    enable = true;
    role = "agent";
    serverAddr = serverAddr;
    nodeLabels = {
      "topology.researchstack.io/role" = "foxtop";
      "topology.researchstack.io/gpu" = "true";
      "topology.researchstack.io/storage-tier" = "nvme-ssd";
      "topology.researchstack.io/compute-class" = "primary";
    };
    extraFlags = [
      "--node-ip=100.88.57.96"
    ];
  };
}
