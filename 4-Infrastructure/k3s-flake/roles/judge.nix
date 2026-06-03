{ config, pkgs, lib, hostName, serverAddr, domain, ... }:

{
  services.k3s = {
    enable = true;
    role = "agent";
    serverAddr = serverAddr;
    nodeLabels = { "topology.researchstack.io/role" = "judge"; };
  };
}
