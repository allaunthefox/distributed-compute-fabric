{ config, pkgs, lib, hostName, serverAddr, domain, ... }:

{
  services.k3s = {
    enable = true;
    role = "agent";
    serverAddr = serverAddr;
    nodeLabels = {
      "topology.researchstack.io/role" = "mirror";
      "topology.researchstack.io/gpu" = "false";
      "topology.researchstack.io/storage-tier" = "vps-ssd";
      "topology.researchstack.io/compute-class" = "mirror";
    };
    extraFlags = [
      "--node-ip=100.110.163.82"
    ];
  };
}
