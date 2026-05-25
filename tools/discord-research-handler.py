#!/home/nicknemo17/clawd/venv/bin/python
"""
Discord Deep Research Handler — role-gated, rate-limited Dexter queries.

Polls #research channel for `!research <query>` commands.
Only Shark role members get access (3 queries/week).

Schedule: every 2 min via cron
Cost on idle runs: $0.00 (just reads messages via clawdbot CLI)
Cost per query: ~$0.15-0.50 (Dexter agent + Financial Datasets API)
"""

import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
CLAWD = Path.home() / "clawd"
STATE_FILE = CLAWD / "memory/discord-research-state.json"
DEXTER_RUN = str(CLAWD / "tools/dexter-run.sh")
DEXTER_LOCK = CLAWD / "memory/.dexter-lock"
SUBSTACK_CSV = CLAWD / "memory/substack-subscribers.csv"

# Discord IDs — loaded from discord-channels.sh
def _load_discord_env():
    """Source discord-channels.sh and extract vars."""
    import shlex
    ch_path = Path.home() / "clawd/tools/discord-channels.sh"
    env = {}
    if ch_path.exists():
        for line in ch_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("export ") or (line and not line.startswith("#") and "=" in line):
                line = line.removeprefix("export ").strip()
                k, _, v = line.partition("=")
                v = v.strip().strip('"').strip("'")
                # skip lines with ${...} references
                if "${" not in v:
                    env[k] = v
    return env
_denv = _load_discord_env()
GUILD_ID = _denv.get("DISCORD_GUILD_ID", "")
RESEARCH_CH = _denv.get("DISCORD_RESEARCH", "")
SHARK_ROLE_ID = _denv.get("DISCORD_SHARK_ROLE", "")
ALLOWED_ROLES = {
    SHARK_ROLE_ID,   # Shark
}
QUERIES_PER_WEEK = 3


def send_discord(channel_id: str, message: str):
    """Send message to Discord via clawdbot."""
    if len(message) > 1950:
        message = message[:1947] + "..."
    try:
        subprocess.Popen(
            ["clawdbot", "message", "send",
             "--channel", "discord",
             "--target", f"channel:{channel_id}",
             "--message", message],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def read_messages(limit: int = 10) -> list[dict]:
    """Read recent messages from #research."""
    try:
        result = subprocess.run(
            ["clawdbot", "message", "read",
             "--channel", "discord",
             "--target", f"channel:{RESEARCH_CH}",
             "--json", "--limit", str(limit)],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return []
        data = json.loads(result.stdout)
        return data.get("payload", {}).get("messages", [])
    except Exception:
        return []


def get_member_roles(user_id: str) -> set[str]:
    """Get Discord role IDs for a user."""
    try:
        result = subprocess.run(
            ["clawdbot", "message", "member", "info",
             "--channel", "discord",
             "--guild-id", GUILD_ID,
             "--user-id", user_id,
             "--json"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return set()
        data = json.loads(result.stdout)
        roles = data.get("payload", {}).get("member", {}).get("roles", [])
        return set(roles)
    except Exception:
        return set()


def load_state() -> dict:
    """Load handler state (processed IDs + quotas)."""
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {"processed_ids": [], "quotas": {}}


def save_state(state: dict):
    """Save handler state."""
    # Prune processed_ids to last 200
    state["processed_ids"] = state.get("processed_ids", [])[-200:]
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def current_week_start() -> str:
    """Get Monday of current week as YYYY-MM-DD."""
    now = datetime.now(ET)
    monday = now.date() - __import__("datetime").timedelta(days=now.weekday())
    return monday.isoformat()


def check_quota(state: dict, user_id: str) -> tuple[bool, int]:
    """Check if user is under weekly quota. Returns (allowed, current_count)."""
    week = current_week_start()
    quotas = state.get("quotas", {})
    user_quota = quotas.get(user_id, {})

    # Reset if new week
    if user_quota.get("week_start") != week:
        user_quota = {"count": 0, "week_start": week}
        quotas[user_id] = user_quota
        state["quotas"] = quotas

    count = user_quota.get("count", 0)
    return count < QUERIES_PER_WEEK, count


def increment_quota(state: dict, user_id: str):
    """Increment user's weekly query count."""
    week = current_week_start()
    quotas = state.setdefault("quotas", {})
    user_quota = quotas.setdefault(user_id, {"count": 0, "week_start": week})
    if user_quota.get("week_start") != week:
        user_quota["count"] = 0
        user_quota["week_start"] = week
    user_quota["count"] = user_quota.get("count", 0) + 1


def run_dexter_query(query: str) -> str:
    """Run Dexter agent query and return result."""
    env = os.environ.copy()
    env["PATH"] = f"{Path.home()}/.bun/bin:" + env.get("PATH", "")

    try:
        result = subprocess.run(
            [DEXTER_RUN, "query", query],
            capture_output=True, text=True, timeout=180, env=env,
        )
        output = result.stdout.strip()
        if not output:
            output = result.stderr.strip() or "No result returned."
        return output
    except subprocess.TimeoutExpired:
        return "Research timed out after 3 minutes. Try a more specific query."
    except Exception as e:
        return f"Research failed: {e}"


def is_paid_subscriber(email: str) -> bool:
    """Check if email is in Substack paid subscriber CSV."""
    import csv
    with open(SUBSTACK_CSV, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row_email = row.get("Email", "").strip().lower()
            if row_email == email:
                # Non-empty "Stripe plan" means paying subscriber
                stripe_plan = row.get("Stripe plan", "").strip()
                if stripe_plan:
                    return True
    return False


def _get_discord_token() -> str:
    """Load Discord bot token from clawdbot config."""
    cfg_path = Path.home() / ".clawdbot/clawdbot.json"
    with open(cfg_path) as f:
        cfg = json.load(f)
    return cfg["channels"]["discord"]["token"]


def assign_shark_role(user_id: str) -> bool:
    """Assign Shark role via Discord REST API (clawdbot CLI has role changes disabled)."""
    try:
        token = _get_discord_token()
        url = f"https://discord.com/api/v10/guilds/{GUILD_ID}/members/{user_id}/roles/{SHARK_ROLE_ID}"
        req = urllib.request.Request(url, method="PUT", headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
        }, data=b"")
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.status == 204
    except Exception as e:
        print(f"  Failed to assign Shark role: {e}")
        return False


def delete_message(channel_id: str, message_id: str):
    """Delete a Discord message to hide sensitive content (e.g. emails)."""
    try:
        result = subprocess.run(
            ["clawdbot", "message", "delete",
             "--channel", "discord",
             "--target", f"channel:{channel_id}",
             "--message-id", message_id],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            print(f"  Failed to delete message {message_id}: {result.stderr}")
    except Exception as e:
        print(f"  Failed to delete message {message_id}: {e}")


def handle_claim(msg: dict, state: dict):
    """Handle !claim shark <email> command."""
    author = msg.get("author", {})
    user_id = author.get("id", "")
    username = author.get("username", "unknown")
    content = msg.get("content", "").strip()

    parts = content.split(maxsplit=2)  # ["!claim", "shark", "email"]
    if len(parts) < 3:
        send_discord(RESEARCH_CH, f"@{username} Usage: `!claim shark your@email.com`")
        return

    email = parts[2].strip().lower()
    msg_id = msg.get("id", "")

    # Delete the claim message immediately to hide their email
    delete_message(RESEARCH_CH, msg_id)

    # Already has Shark?
    roles = get_member_roles(user_id)
    if SHARK_ROLE_ID in roles:
        send_discord(RESEARCH_CH, f"@{username} You already have the Shark role.")
        return

    # Check CSV
    if not SUBSTACK_CSV.exists():
        send_discord(RESEARCH_CH, f"@{username} Subscriber list not available. Contact admin.")
        return

    if is_paid_subscriber(email):
        if assign_shark_role(user_id):
            send_discord(RESEARCH_CH,
                f"@{username} Shark role assigned! You now have access to `!research` queries ({QUERIES_PER_WEEK}/week).")
            now_str = datetime.now(ET).isoformat()
            state.setdefault("claims", {})[user_id] = {"email": email, "claimed_at": now_str}
            save_state(state)
            print(f"  Shark role claimed by {username} ({email})")
        else:
            send_discord(RESEARCH_CH,
                f"@{username} Verified as paid subscriber but role assignment failed. Contact admin.")
            print(f"  Role assignment failed for {username} ({email})")
    else:
        send_discord(RESEARCH_CH,
            f"@{username} Email not found in paid subscribers. "
            f"Make sure you're using the email registered on Substack.")
        print(f"  Claim rejected for {username} ({email})")


def main():
    now_et = datetime.now(ET)
    state = load_state()
    processed = set(state.get("processed_ids", []))

    # 1. Read recent messages
    messages = read_messages(10)
    if not messages:
        return

    # 2. Find unprocessed commands (!claim shark or !research)
    commands = []
    for msg in messages:
        msg_id = msg.get("id", "")
        content = msg.get("content", "").strip()
        author = msg.get("author", {})

        # Skip bots
        if author.get("bot"):
            continue

        # Skip already processed
        if msg_id in processed:
            continue

        lower = content.lower()

        # Handle !claim shark (mark processed immediately)
        if lower.startswith("!claim shark") or lower.startswith("\\!claim shark"):
            state.setdefault("processed_ids", []).append(msg_id)
            save_state(state)
            processed.add(msg_id)
            handle_claim(msg, state)
            continue

        # Check for !research prefix (Discord may escape ! as \!)
        if lower.startswith("\\!research "):
            query = content[11:].strip()  # len("\\!research ") == 11
        elif lower.startswith("!research "):
            query = content[10:].strip()  # len("!research ") == 10
        else:
            continue
        if not query:
            continue

        commands.append({
            "msg_id": msg_id,
            "user_id": author.get("id", ""),
            "username": author.get("username", "unknown"),
            "query": query,
        })

    if not commands:
        return

    # 3. Process only the first (oldest) unhandled command per run
    # Messages come newest-first, so reverse to get oldest first
    commands.reverse()
    cmd = commands[0]

    msg_id = cmd["msg_id"]
    user_id = cmd["user_id"]
    username = cmd["username"]
    query = cmd["query"]

    print(f"{now_et.strftime('%Y-%m-%d %H:%M:%S')} Research request from {username}: {query[:80]}")

    # Mark as processed immediately (prevent re-processing on next run)
    state.setdefault("processed_ids", []).append(msg_id)
    save_state(state)

    # 4. Check role
    roles = get_member_roles(user_id)
    if not roles & ALLOWED_ROLES:
        send_discord(RESEARCH_CH,
                     f"@{username} Deep research is available for **Shark** members only.")
        print(f"  Rejected: no qualifying role")
        return

    # 5. Check quota
    allowed, count = check_quota(state, user_id)
    if not allowed:
        send_discord(RESEARCH_CH,
                     f"@{username} You've used {QUERIES_PER_WEEK}/{QUERIES_PER_WEEK} research queries this week. Resets Monday.")
        print(f"  Rejected: quota exceeded ({count}/{QUERIES_PER_WEEK})")
        return

    # 6. Check dexter lock
    if DEXTER_LOCK.is_dir():
        send_discord(RESEARCH_CH,
                     f"@{username} Research engine is busy with another query. Try again in a few minutes.")
        print(f"  Deferred: dexter locked")
        # Remove from processed so it retries next run
        state["processed_ids"] = [x for x in state["processed_ids"] if x != msg_id]
        save_state(state)
        return

    # 7. Post acknowledgment
    new_count = count + 1
    send_discord(RESEARCH_CH,
                 f"Researching: *{query[:200]}*... ({new_count}/{QUERIES_PER_WEEK} this week)")

    # 8. Run Dexter
    print(f"  Running Dexter query...")
    result = run_dexter_query(query)
    print(f"  Dexter returned {len(result)} chars")

    # 9. Post result
    header = f"**Deep Research** (requested by @{username})\n> {query[:200]}\n\n"
    footer = f"\n\n_{new_count}/{QUERIES_PER_WEEK} queries this week | Powered by Dexter + Financial Datasets_"

    max_result_len = 1950 - len(header) - len(footer)
    if len(result) > max_result_len:
        # Split into 2 messages
        send_discord(RESEARCH_CH, header + result[:1900])
        remainder = result[1900:]
        if len(remainder) > 1900:
            remainder = remainder[:1897] + "..."
        send_discord(RESEARCH_CH, remainder + footer)
    else:
        send_discord(RESEARCH_CH, header + result + footer)

    # 10. Update quota
    increment_quota(state, user_id)
    save_state(state)

    print(f"  Posted research result for {username} ({new_count}/{QUERIES_PER_WEEK} this week)")


if __name__ == "__main__":
    main()
