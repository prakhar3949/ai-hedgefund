#!/usr/bin/env node

const fs = require('fs').promises;
const path = require('path');
const { google } = require('googleapis');

const CREDENTIALS_PATH = path.join(process.env.HOME, 'clawd/credentials/google-oauth.json');

// Configure your Gmail accounts here. Each needs a Google OAuth token file.
// See credentials.example/ for setup instructions.
const ACCOUNTS_PATH = path.join(process.env.HOME, 'clawd/credentials/gmail-accounts.json');
let ACCOUNTS;
try {
  ACCOUNTS = JSON.parse(require('fs').readFileSync(ACCOUNTS_PATH, 'utf8'));
  // Expand ~ in tokenPath
  for (const key of Object.keys(ACCOUNTS)) {
    if (ACCOUNTS[key].tokenPath) {
      ACCOUNTS[key].tokenPath = ACCOUNTS[key].tokenPath.replace(/^~/, process.env.HOME);
    }
  }
} catch {
  console.error(`Missing ${ACCOUNTS_PATH} — copy from credentials.example/gmail-accounts.json.example`);
  process.exit(1);
}

async function authorize(accountKey) {
  const account = ACCOUNTS[accountKey];
  if (!account) {
    throw new Error(`Unknown account: ${accountKey}`);
  }

  const credentials = JSON.parse(await fs.readFile(CREDENTIALS_PATH));
  const { client_secret, client_id, redirect_uris } = credentials.installed;
  const oAuth2Client = new google.auth.OAuth2(client_id, client_secret, redirect_uris[0]);
  
  const token = await fs.readFile(account.tokenPath);
  oAuth2Client.setCredentials(JSON.parse(token));
  return oAuth2Client;
}

async function listUnreadEmails(auth, accountEmail) {
  const gmail = google.gmail({ version: 'v1', auth });
  
  const res = await gmail.users.messages.list({
    userId: 'me',
    q: 'is:unread',
    maxResults: 10,
  });

  const messages = res.data.messages || [];
  
  if (messages.length === 0) {
    return [];
  }

  const emails = [];
  for (const message of messages) {
    const msg = await gmail.users.messages.get({
      userId: 'me',
      id: message.id,
      format: 'metadata',
      metadataHeaders: ['From', 'Subject', 'Date'],
    });

    const headers = msg.data.payload.headers;
    const from = headers.find(h => h.name === 'From')?.value || '';
    const subject = headers.find(h => h.name === 'Subject')?.value || '';
    const date = headers.find(h => h.name === 'Date')?.value || '';

    emails.push({ 
      account: accountEmail,
      id: message.id, 
      from, 
      subject, 
      date 
    });
  }

  return emails;
}

async function getTodayCalendar(auth, accountEmail) {
  const calendar = google.calendar({ version: 'v3', auth });
  
  const now = new Date();
  const endOfDay = new Date(now);
  endOfDay.setHours(23, 59, 59, 999);

  const res = await calendar.events.list({
    calendarId: 'primary',
    timeMin: now.toISOString(),
    timeMax: endOfDay.toISOString(),
    singleEvents: true,
    orderBy: 'startTime',
  });

  const events = res.data.items || [];
  return events.map(event => ({
    account: accountEmail,
    summary: event.summary,
    start: event.start.dateTime || event.start.date,
    end: event.end.dateTime || event.end.date,
  }));
}

async function main() {
  const action = process.argv[2];
  const accountKey = process.argv[3];

  if (!action || !['inbox', 'calendar', 'all'].includes(action)) {
    console.log('Usage: gmail-multi-account.js [inbox|calendar|all] [account-key|all]');
    console.log('Accounts:', Object.keys(ACCOUNTS).join(', '));
    process.exit(1);
  }

  try {
    const accounts = accountKey === 'all' || !accountKey 
      ? Object.keys(ACCOUNTS) 
      : [accountKey];

    const results = {};

    for (const acc of accounts) {
      const auth = await authorize(acc);
      const accountEmail = ACCOUNTS[acc].email;

      if (action === 'inbox' || action === 'all') {
        const emails = await listUnreadEmails(auth, accountEmail);
        if (!results.inbox) results.inbox = [];
        results.inbox.push(...emails);
      }

      if (action === 'calendar' || action === 'all') {
        const events = await getTodayCalendar(auth, accountEmail);
        if (!results.calendar) results.calendar = [];
        results.calendar.push(...events);
      }
    }

    console.log(JSON.stringify(results, null, 2));
  } catch (error) {
    console.error('Error:', error.message);
    process.exit(1);
  }
}

main();
