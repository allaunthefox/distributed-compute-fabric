{ config, pkgs, lib, hostName, serverAddr, domain, ... }:

{
  services.k3s = {
    enable = true;
    role = "agent";
    serverAddr = serverAddr;
    nodeLabels = {
      "topology.researchstack.io/role" = "neon";
      "topology.researchstack.io/gpu" = "true";
      "topology.researchstack.io/storage-tier" = "nvme-ssd";
      "topology.researchstack.io/compute-class" = "heavy";
      "node.kubernetes.io/workload" = "heavy-stateful";
      "kubernetes.io/arch" = "arm64";
    };
    extraFlags = [
      "--node-ip=100.100.75.113"
    ];
  };
}
