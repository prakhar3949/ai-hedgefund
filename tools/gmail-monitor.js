#!/usr/bin/env node

const fs = require('fs').promises;
const path = require('path');
const { google } = require('googleapis');

const SCOPES = [
  'https://www.googleapis.com/auth/gmail.readonly',
  'https://www.googleapis.com/auth/gmail.modify',
  'https://www.googleapis.com/auth/gmail.labels',
  'https://www.googleapis.com/auth/calendar.readonly',
  'https://www.googleapis.com/auth/calendar.events'
];

const TOKEN_PATH = path.join(process.env.HOME, 'clawd/credentials/google-token.json');
const CREDENTIALS_PATH = path.join(process.env.HOME, 'clawd/credentials/google-oauth.json');

async function loadCredentials() {
  const content = await fs.readFile(CREDENTIALS_PATH);
  return JSON.parse(content);
}

async function authorize() {
  const credentials = await loadCredentials();
  const { client_secret, client_id, redirect_uris } = credentials.installed;
  const oAuth2Client = new google.auth.OAuth2(client_id, client_secret, redirect_uris[0]);

  try {
    const token = await fs.readFile(TOKEN_PATH);
    oAuth2Client.setCredentials(JSON.parse(token));
    return oAuth2Client;
  } catch (err) {
    return getNewToken(oAuth2Client);
  }
}

async function getNewToken(oAuth2Client) {
  const authUrl = oAuth2Client.generateAuthUrl({
    access_type: 'offline',
    scope: SCOPES,
  });

  console.log('\n📧 Gmail Authorization Required');
  console.log('=================================');
  console.log('\n1. Open this URL in your browser:');
  console.log('\n' + authUrl);
  console.log('\n2. Authorize the app');
  console.log('3. Copy the code from the URL (after ?code=)');
  console.log('\nPaste the authorization code here: ');

  const readline = require('readline');
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
  });

  return new Promise((resolve, reject) => {
    rl.question('', async (code) => {
      rl.close();
      try {
        const { tokens } = await oAuth2Client.getToken(code);
        oAuth2Client.setCredentials(tokens);
        await fs.writeFile(TOKEN_PATH, JSON.stringify(tokens));
        console.log('✅ Token stored successfully');
        resolve(oAuth2Client);
      } catch (err) {
        reject(err);
      }
    });
  });
}

async function listUnreadEmails(auth) {
  const gmail = google.gmail({ version: 'v1', auth });
  
  const res = await gmail.users.messages.list({
    userId: 'me',
    q: 'is:unread',
    maxResults: 10,
  });

  const messages = res.data.messages || [];
  
  if (messages.length === 0) {
    console.log('No unread emails');
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

    emails.push({ id: message.id, from, subject, date });
  }

  return emails;
}

async function getTodayCalendar(auth) {
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
    summary: event.summary,
    start: event.start.dateTime || event.start.date,
    end: event.end.dateTime || event.end.date,
  }));
}

async function main() {
  try {
    const auth = await authorize();
    
    if (process.argv[2] === 'inbox') {
      const emails = await listUnreadEmails(auth);
      console.log(JSON.stringify(emails, null, 2));
    } else if (process.argv[2] === 'calendar') {
      const events = await getTodayCalendar(auth);
      console.log(JSON.stringify(events, null, 2));
    } else {
      console.log('Usage: gmail-monitor.js [inbox|calendar]');
    }
  } catch (error) {
    console.error('Error:', error.message);
    process.exit(1);
  }
}

main();
