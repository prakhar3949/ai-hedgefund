#!/usr/bin/env node

const { google } = require('googleapis');
const fs = require('fs');
const path = require('path');

const CREDENTIALS_PATH = path.join(process.env.HOME, 'clawd/credentials/google-oauth.json');
const TOKEN_PATH = path.join(process.env.HOME, 'clawd/credentials/google-token.json');

async function sendEmail(to, subject, body) {
  const credentials = JSON.parse(fs.readFileSync(CREDENTIALS_PATH));
  const token = JSON.parse(fs.readFileSync(TOKEN_PATH));
  
  const { client_secret, client_id, redirect_uris } = credentials.installed;
  const oAuth2Client = new google.auth.OAuth2(client_id, client_secret, redirect_uris[0]);
  oAuth2Client.setCredentials(token);

  const gmail = google.gmail({ version: 'v1', auth: oAuth2Client });
  
  const messageParts = [
    `To: ${to}`,
    `Subject: ${subject}`,
    '',
    body
  ];
  const message = messageParts.join('\n');
  const encodedMessage = Buffer.from(message).toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');

  const res = await gmail.users.messages.send({
    userId: 'me',
    requestBody: {
      raw: encodedMessage,
    },
  });
  
  console.log('Email sent:', res.data.id);
}

const to = process.argv[2];
const subject = process.argv[3];
const body = process.argv.slice(4).join(' ');

if (!to || !subject || !body) {
  console.error('Usage: gmail-send.js <to> <subject> <body>');
  process.exit(1);
}

sendEmail(to, subject, body).catch(console.error);
