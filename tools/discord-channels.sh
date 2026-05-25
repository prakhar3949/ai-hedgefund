#!/bin/bash
# Discord Channel IDs — single source of truth for all scripts
# Source this file: source ~/clawd/tools/discord-channels.sh

DISCORD_MARKET_DASHBOARD="1468334675041976422"   # was #levels-technicals → hourly market snapshots
DISCORD_TRADE_ALERTS="1468334594314211423"        # breaking news, crash alerts, thesis triggers
DISCORD_SEC_FILINGS="1469449368603066635"         # EDGAR filings + deep analysis
DISCORD_TWEET_FEED="1468334902557802598"          # priority Twitter posts
DISCORD_SUBSTACK_FEED="1468334855946375431"       # Substack articles
DISCORD_CRYPTO="1468424649531457619"              # crypto prices + alerts
DISCORD_RESEARCH="1468773228791992494"            # morning briefing, portfolio, thesis, Dexter research
DISCORD_ECONOMETRICS="1469851672577704211"        # recency-weighted correlations, factor exposure, econometric models

# Server-level IDs
DISCORD_GUILD_ID="1468333686884663329"
DISCORD_SHARK_ROLE="1468373642801840423"
DISCORD_BARRACUDA_ROLE="1468404947463704709"

# WhatsApp / Telegram targets (keep out of git history — loaded at runtime)
WHATSAPP_TARGET="${WHATSAPP_TARGET:-$(cat ~/.clawdbot/credentials/whatsapp-target 2>/dev/null || echo '')}"
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-$(cat ~/.clawdbot/credentials/telegram-chat-id 2>/dev/null || echo '')}"

# Helper function for sending Discord messages
send_discord() {
    local channel_id="$1"
    local message="$2"

    # Truncate to Discord limit
    if [ ${#message} -gt 1950 ]; then
        message="${message:0:1947}..."
    fi

    clawdbot message send --channel discord --target "channel:${channel_id}" --message "$message" 2>/dev/null
}
