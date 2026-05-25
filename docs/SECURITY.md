# Clawdbot & MarketBot Security Guide

*Last Updated: February 2026*

---

## Current Security Status

### Credentials Protection
| Item | Status | Location |
|------|--------|----------|
| API Keys | ✅ 600 permissions | ~/clawd/credentials/ |
| OAuth Tokens | ✅ 600 permissions | ~/clawd/credentials/ |
| Clawdbot Config | ✅ 600 permissions | ~/.clawdbot/clawdbot.json |
| Credentials Dir | ✅ 700 permissions | ~/clawd/credentials/ |

### Network Security
| Service | Port | Exposure | Status |
|---------|------|----------|--------|
| Clawdbot Gateway | 18789 | LAN + Tailscale only | ✅ Firewall protected |
| Browser Control | 18791 | localhost only | ✅ Safe |
| Canvas | 18792 | localhost only | ✅ Safe |
| SSH | 22 | All interfaces | ⚠️ Password protect |
| RPC (rpcbind) | 111 | Blocked | ✅ Firewall blocked |

### Bot Security
| Setting | Value | Risk Level |
|---------|-------|------------|
| Discord groupPolicy | allowlist | ✅ Low |
| WhatsApp groupPolicy | allowlist | ✅ Low |
| WhatsApp dmPolicy | pairing | ✅ Low |
| Gateway auth | token-based | ✅ Low |
| MarketBot requireMention | false (marketbot only) | ⚠️ Medium |

---

## Firewall Rules Active

```bash
# Clawdbot gateway - LAN + Tailscale only
Port 18789: 192.168.0.0/24, 100.64.0.0/10 ALLOW
Port 18789: * DROP

# RPC blocked
Port 111: * DROP (except localhost)
```

---

## Discord Bot Hardening

### Current Permissions
The MarketBot should have ONLY these permissions:
- ✅ Read Messages/View Channels
- ✅ Send Messages
- ✅ Embed Links
- ✅ Read Message History
- ❌ Manage Channels (remove after setup)
- ❌ Manage Messages
- ❌ Kick/Ban Members
- ❌ Administrator

### Channel Allowlist (Active)
Only these channels are monitored:
- `1468334675041976422` - #levels-technicals (alerts only)
- `1468334594314211423` - #trade-alerts
- `1468334717366571265` - #market-discussion
- `1468773228791992494` - #marketbot (user questions)
- `1469043771198148678` - #welcome

### Recommended: Remove Manage Channels Permission
After initial setup, remove "Manage Channels" permission from MarketBot:
1. Discord Server Settings → Roles
2. Find MarketBot role
3. Disable "Manage Channels"

---

## WhatsApp Security

### Current Settings
- **DM Policy:** pairing (must pair device first)
- **Group Policy:** allowlist (explicit opt-in only)
- **Credentials:** Encrypted session stored locally

### Recommendations
1. ✅ Never share WhatsApp QR code
2. ✅ Credentials stored with 600 permissions
3. ✅ Session auto-expires if not used

---

## API Key Rotation Schedule

| Key | Rotation Frequency | Last Rotated |
|-----|-------------------|--------------|
| Discord Bot Token | Yearly or if exposed | - |
| Anthropic API Key | If exposed | - |
| OpenAI API Key | If exposed | - |
| Google OAuth | Auto-refresh | - |
| Twitter Credentials | If exposed | - |

### How to Rotate Discord Token
1. Go to Discord Developer Portal
2. Select your application
3. Bot → Reset Token
4. Update `~/.clawdbot/clawdbot.json`
5. Restart gateway: `systemctl --user restart clawdbot-gateway`

---

## Security Monitoring

### Watchdog (Active)
- **Frequency:** Every 2 minutes
- **Actions:** Auto-restart on disconnect, Discord alerts
- **Log:** `~/clawd/logs/whatsapp-watchdog.log`

### Logs to Monitor
```bash
# Check for suspicious activity
tail -f /tmp/clawdbot/clawdbot-$(date +%Y-%m-%d).log

# Check watchdog
tail -f ~/clawd/logs/whatsapp-watchdog.log

# Check system auth
sudo tail -f /var/log/auth.log
```

---

## Attack Surface Summary

### Exposed Services
1. **SSH (port 22)** - Protected by password/key
2. **Clawdbot Gateway (18789)** - LAN + Tailscale only
3. **Tailscale (mesh network)** - Encrypted, authenticated

### Not Exposed
- Browser control (localhost)
- Canvas server (localhost)
- Database/memory files (local filesystem)

---

## Security Checklist

### Daily
- [ ] Verify WhatsApp connected (`clawdbot channels status`)
- [ ] Check watchdog log for disconnect patterns

### Weekly
- [ ] Review `clawdbot security audit --deep`
- [ ] Check for failed SSH attempts: `sudo grep "Failed" /var/log/auth.log`
- [ ] Verify firewall rules active

### Monthly
- [ ] Update clawdbot: `npm update -g clawdbot`
- [ ] Update system: `sudo apt update && sudo apt upgrade`
- [ ] Review Discord bot permissions
- [ ] Check credential file permissions: `ls -la ~/clawd/credentials/`

### If Breach Suspected
1. **Immediately:**
   - Stop gateway: `systemctl --user stop clawdbot-gateway`
   - Revoke Discord token (Developer Portal)
   - Rotate all API keys
2. **Investigate:**
   - Check logs for unauthorized access
   - Review recent session activity
3. **Recover:**
   - Generate new credentials
   - Update config
   - Restart services

---

## Hardening Commands

### Run Security Audit
```bash
clawdbot security audit --deep
clawdbot doctor
```

### Fix Credential Permissions
```bash
chmod 700 ~/clawd/credentials/
chmod 600 ~/clawd/credentials/*
chmod 600 ~/.clawdbot/clawdbot.json
```

### Restart Firewall Rules
```bash
~/clawd/tools/firewall-setup.sh
```

### Verify Network Exposure
```bash
ss -tlnp | grep LISTEN
```

---

## Emergency Contacts

- **Clawdbot Issues:** Check logs, restart gateway
- **Discord Bot Compromised:** Revoke token at discord.com/developers
- **WhatsApp Compromised:** Re-pair device, revoke sessions

---

*Security is ongoing. Review this document monthly.*
