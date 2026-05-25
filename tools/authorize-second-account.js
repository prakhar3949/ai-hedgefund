#!/usr/bin/env node

const fs = require('fs').promises;
const path = require('path');
const { google } = require('googleapis');

const CREDENTIALS_PATH = path.join(process.env.HOME, 'clawd/credentials/google-oauth.json');
// Token path for the secondary Gmail account — filename set in gmail-accounts.json
const ACCOUNTS_PATH = path.join(process.env.HOME, 'clawd/credentials/gmail-accounts.json');
const accounts = JSON.parse(require('fs').readFileSync(ACCOUNTS_PATH, 'utf8'));
const secondaryKey = Object.keys(accounts).find(k => k !== Object.keys(accounts)[0]) || 'secondary';
const TOKEN_PATH = (accounts[secondaryKey] && accounts[secondaryKey].tokenPath)
  ? accounts[secondaryKey].tokenPath.replace(/^~/, process.env.HOME)
  : path.join(process.env.HOME, 'clawd/credentials/google-token-secondary.json');

async function main() {
  const code = process.argv[2];
  if (!code) {
    console.error('Usage: node authorize-second-account.js CODE');
    process.exit(1);
  }

  const credentials = JSON.parse(await fs.readFile(CREDENTIALS_PATH));
  const { client_secret, client_id, redirect_uris } = credentials.installed;
  const oAuth2Client = new google.auth.OAuth2(client_id, client_secret, redirect_uris[0]);

  try {
    const { tokens } = await oAuth2Client.getToken(code);
    await fs.writeFile(TOKEN_PATH, JSON.stringify(tokens, null, 2));
    console.log('✅ Second account authorized successfully');
    console.log('Token saved to:', TOKEN_PATH);
  } catch (err) {
    console.error('Authorization failed:', err.message);
    process.exit(1);
  }
}

main();
