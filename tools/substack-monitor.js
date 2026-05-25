#!/usr/bin/env node

const fs = require('fs').promises;
const path = require('path');
const { google } = require('googleapis');

const TOKEN_PATH = path.join(process.env.HOME, 'clawd/credentials/google-token.json');
const CREDENTIALS_PATH = path.join(process.env.HOME, 'clawd/credentials/google-oauth.json');
const SEEN_PATH = path.join(process.env.HOME, 'clawd/memory/substack-seen.json');

async function loadCredentials() {
  const content = await fs.readFile(CREDENTIALS_PATH);
  return JSON.parse(content);
}

async function authorize() {
  const credentials = await loadCredentials();
  const { client_secret, client_id, redirect_uris } = credentials.installed;
  const oAuth2Client = new google.auth.OAuth2(client_id, client_secret, redirect_uris[0]);
  
  const token = await fs.readFile(TOKEN_PATH);
  oAuth2Client.setCredentials(JSON.parse(token));
  return oAuth2Client;
}

async function getSeenIds() {
  try {
    const data = await fs.readFile(SEEN_PATH);
    return JSON.parse(data);
  } catch (err) {
    return {};
  }
}

async function saveSeenIds(seen) {
  await fs.writeFile(SEEN_PATH, JSON.stringify(seen, null, 2));
}

async function getNewSubstackPosts(auth) {
  const gmail = google.gmail({ version: 'v1', auth });
  
  // Look for Substack posts from last 24 hours
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  const afterDate = Math.floor(yesterday.getTime() / 1000);
  
  const res = await gmail.users.messages.list({
    userId: 'me',
    q: `from:substack.com after:${afterDate}`,
    maxResults: 50,
  });

  const messages = res.data.messages || [];
  const seen = await getSeenIds();
  const newPosts = [];

  for (const message of messages) {
    if (seen[message.id]) continue;

    const msg = await gmail.users.messages.get({
      userId: 'me',
      id: message.id,
      format: 'full',
    });

    const headers = msg.data.payload.headers;
    const from = headers.find(h => h.name === 'From')?.value || '';
    const subject = headers.find(h => h.name === 'Subject')?.value || '';
    
    // Filter: Only posts from actual authors (not notifications/likes/comments)
    // Substack author emails are: name@substack.com or name+newsletter@substack.com
    const isAuthorPost = from.includes('@substack.com') && 
                        !from.includes('no-reply@substack.com') &&
                        !from.includes('reaction@');
    
    if (!isAuthorPost) {
      seen[message.id] = true;
      continue;
    }

    // Extract article URL from email body
    let body = '';
    if (msg.data.payload.parts) {
      const htmlPart = msg.data.payload.parts.find(p => p.mimeType === 'text/html');
      if (htmlPart && htmlPart.body.data) {
        body = Buffer.from(htmlPart.body.data, 'base64').toString();
      }
    } else if (msg.data.payload.body.data) {
      body = Buffer.from(msg.data.payload.body.data, 'base64').toString();
    }

    // Extract Substack URL (pattern: https://NAME.substack.com/p/SLUG)
    const urlMatch = body.match(/https?:\/\/[^\/]+\.substack\.com\/p\/[^\s"<]+/);
    const url = urlMatch ? urlMatch[0] : null;

    if (url) {
      newPosts.push({
        id: message.id,
        from,
        subject,
        url,
      });
    }
    
    seen[message.id] = true;
  }

  await saveSeenIds(seen);
  return newPosts;
}

async function main() {
  try {
    const auth = await authorize();
    const posts = await getNewSubstackPosts(auth);
    console.log(JSON.stringify(posts, null, 2));
  } catch (error) {
    console.error('Error:', error.message);
    process.exit(1);
  }
}

main();
