#!/home/nicknemo17/clawd/venv/bin/python
"""
Send email via Gmail SMTP.

Usage:
  send-email.py --to "recipient@email.com" --subject "Subject" --body "Message body"
  send-email.py --to "recipient@email.com" --subject "Subject" --file /path/to/file.md
  echo "body" | send-email.py --to "recipient@email.com" --subject "Subject" --stdin

Credentials: ~/.clawdbot/credentials/gmail.json
"""

import argparse
import json
import smtplib
import sys
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path


def load_creds() -> dict:
    creds_file = Path.home() / ".clawdbot/credentials/gmail.json"
    with open(creds_file) as f:
        return json.load(f)


def send_email(to: str, subject: str, body: str, html: bool = False):
    creds = load_creds()
    sender = creds["email"]

    msg = MIMEMultipart("alternative")
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject

    content_type = "html" if html else "plain"
    msg.attach(MIMEText(body, content_type))

    with smtplib.SMTP(creds["smtp_host"], creds["smtp_port"]) as server:
        server.starttls()
        server.login(sender, creds["app_password"])
        server.send_message(msg)

    print(f"Sent to {to}: {subject}")


def main():
    parser = argparse.ArgumentParser(description="Send email via Gmail")
    parser.add_argument("--to", required=True, help="Recipient email")
    parser.add_argument("--subject", "-s", required=True, help="Subject line")
    parser.add_argument("--body", "-b", help="Message body text")
    parser.add_argument("--file", "-f", help="Read body from file")
    parser.add_argument("--stdin", action="store_true", help="Read body from stdin")
    parser.add_argument("--html", action="store_true", help="Send as HTML")
    args = parser.parse_args()

    if args.file:
        body = Path(args.file).read_text()
    elif args.stdin:
        body = sys.stdin.read()
    elif args.body:
        body = args.body
    else:
        print("Error: provide --body, --file, or --stdin")
        sys.exit(1)

    send_email(args.to, args.subject, body, html=args.html)


if __name__ == "__main__":
    main()
