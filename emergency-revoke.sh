#!/bin/bash
# Emergency revocation script
# Run this if you need to immediately revoke ClawdBot access

echo "🚨 EMERGENCY REVOCATION"
echo "======================="
echo ""
echo "This will:"
echo "- Delete all stored credentials"
echo "- Remove passwordless sudo"
echo "- Preserve your data and scripts"
echo ""
read -p "Are you sure? (type YES to confirm): " confirm

if [ "$confirm" != "YES" ]; then
    echo "Cancelled."
    exit 1
fi

echo ""
echo "Revoking access..."

# Remove credentials
rm -rf ~/clawd/credentials/*
echo "✅ Credentials deleted"

# Remove passwordless sudo
sudo rm -f /etc/sudoers.d/$USER
echo "✅ Sudo access removed"

# Stop any running monitoring processes
pkill -f "gmail-monitor"
pkill -f "substack-monitor"
pkill -f "stock-monitor"
echo "✅ Monitoring processes stopped"

echo ""
echo "✅ Access revoked successfully"
echo ""
echo "Your data and scripts are preserved in ~/clawd/"
echo "To restore access, re-authenticate with ClawdBot."
