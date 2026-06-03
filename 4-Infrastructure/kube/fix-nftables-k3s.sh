#!/usr/bin/bash
# Ensure k3s pod-to-pod networking works alongside nftables
# nftables default policy is 'drop' on forward, which blocks flannel/cni0 traffic

nft add rule inet filter forward ct state established,related accept 2>/dev/null || true
nft add rule inet filter forward iifname "cni0" accept 2>/dev/null || true
nft add rule inet filter forward oifname "cni0" accept 2>/dev/null || true
nft add rule inet filter forward iifname "flannel*" accept 2>/dev/null || true
nft add rule inet filter forward oifname "flannel*" accept 2>/dev/null || true
