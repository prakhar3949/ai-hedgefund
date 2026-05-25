#!/bin/bash
# Firewall Security Setup for Clawdbot

echo "Setting up firewall rules..."

# Block rpcbind (port 111) from external access
sudo nft add rule ip filter INPUT tcp dport 111 ip saddr != 127.0.0.1 drop 2>/dev/null
sudo nft add rule ip filter INPUT udp dport 111 ip saddr != 127.0.0.1 drop 2>/dev/null

# Allow clawdbot gateway only from local network and Tailscale
# Port 18789 - only allow from 192.168.0.0/24 and 100.64.0.0/10 (Tailscale)
sudo nft add rule ip filter INPUT tcp dport 18789 ip saddr 192.168.0.0/24 accept 2>/dev/null
sudo nft add rule ip filter INPUT tcp dport 18789 ip saddr 100.64.0.0/10 accept 2>/dev/null
sudo nft add rule ip filter INPUT tcp dport 18789 drop 2>/dev/null

echo "Firewall rules applied."
echo "Clawdbot gateway (18789) now only accessible from:"
echo "  - Local network (192.168.0.x)"
echo "  - Tailscale (100.64.x.x)"
