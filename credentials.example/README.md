# Credentials Setup

Copy each `.example` file to `~/clawd/credentials/` (without the `.example` suffix) and fill in your values.

```bash
cp credentials.example/*.example credentials/
cd credentials/
for f in *.example; do mv "$f" "${f%.example}"; done
```

## Required Credentials

| File | Purpose | How to Get |
|------|---------|------------|
| `gmail.json` | Gmail IMAP/SMTP access | Google Account → Security → App Passwords |
| `gmail-accounts.json` | Multi-account Gmail (OAuth) | Run `tools/authorize-second-account.js` |
| `google-oauth.json` | Google API OAuth client | Google Cloud Console → APIs → Credentials |
| `google-token.json` | Google API refresh token | Auto-generated after first OAuth flow |
| `twitter-creds.sh` | Twitter/X scraping auth | Browser DevTools → Cookies on x.com |
| `telegram-jiivebot.json` | Telegram bot | @BotFather on Telegram |

## Clawdbot Credentials

These go in `~/.clawdbot/credentials/` and are managed by `clawdbot doctor`:

| File | Purpose |
|------|---------|
| `whatsapp-target` | Your WhatsApp phone number (E.164 format: `+1234567890`) |
| `telegram-chat-id` | Your Telegram chat ID (run `tools/edgar-monitor.py --get-telegram-id`) |
| `telegram-allowFrom.json` | Telegram user IDs allowed to interact with bot |

## API Keys

Set these as environment variables or store in `~/.clawdbot/credentials/api-keys/`:

| Key | Service | Free Tier |
|-----|---------|-----------|
| Anthropic API Key | Claude AI (Tier 2-3 reasoning) | Pay-per-use |
| Financial Datasets API Key | Stock fundamentals, estimates, insider trades | Free tier available |
| Brave API Key | Web search (optional) | Free tier available |

## Discord Setup

1. Create a bot at [discord.com/developers](https://discord.com/developers)
2. Enable Message Content Intent
3. Add to your server with: Send Messages, Read Messages, Read Message History, Manage Messages
4. Configure channel IDs in `tools/discord-channels.sh`

## Security

- All credential files should be `chmod 600`
- The `credentials/` directory should be `chmod 700`
- Never commit real credentials — this directory is gitignored
