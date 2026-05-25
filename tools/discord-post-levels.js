#!/usr/bin/env node
/**
 * Post market levels to Discord #levels-technicals channel
 * Usage: node discord-post-levels.js [channel-id]
 */

const puppeteer = require('puppeteer-core');
const { exec } = require('child_process');
const util = require('util');
const execAsync = util.promisify(exec);

const CDP_ENDPOINT = process.env.CDP_ENDPOINT || 'ws://localhost:18792/devtools/browser/YOUR-UUID-HERE';

async function getMarketLevels() {
  const { stdout } = await execAsync('~/clawd/venv/bin/python ~/clawd/tools/crash-monitor.py');
  
  // Parse the output
  const lines = stdout.split('\n');
  let sp500, nasdaq, russell;
  
  for (const line of lines) {
    if (line.includes('SP500')) {
      const match = line.match(/\$([0-9,.]+)\s+\(([+-][0-9.]+)%/);
      if (match) sp500 = { price: match[1], change: match[2] };
    }
    if (line.includes('NASDAQ')) {
      const match = line.match(/\$([0-9,.]+)\s+\(([+-][0-9.]+)%/);
      if (match) nasdaq = { price: match[1], change: match[2] };
    }
    if (line.includes('RUSSELL')) {
      const match = line.match(/\$([0-9,.]+)\s+\(([+-][0-9.]+)%/);
      if (match) russell = { price: match[1], change: match[2] };
    }
  }
  
  const now = new Date();
  const estTime = now.toLocaleString('en-US', { 
    timeZone: 'America/New_York',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false
  });
  
  return {
    sp500,
    nasdaq,
    russell,
    time: estTime
  };
}

async function postToDiscord(channelId) {
  console.log('Connecting to browser...');
  const browser = await puppeteer.connect({
    browserWSEndpoint: CDP_ENDPOINT
  });
  
  const pages = await browser.pages();
  let discordPage = pages.find(p => p.url().includes('discord.com'));
  
  if (!discordPage) {
    console.log('No Discord tab found, creating one...');
    discordPage = await browser.newPage();
    await discordPage.goto(`https://discord.com/channels/${channelId}`);
    await discordPage.waitForTimeout(3000);
  } else if (channelId) {
    console.log(`Navigating to channel ${channelId}...`);
    await discordPage.goto(`https://discord.com/channels/${channelId}`);
    await discordPage.waitForTimeout(2000);
  }
  
  console.log('Getting market levels...');
  const levels = await getMarketLevels();
  
  const message = `**Current levels (${levels.time} EST):**

📊 **S&P 500:** ${levels.sp500.price} (${levels.sp500.change}%)
📊 **Nasdaq:** ${levels.nasdaq.price} (${levels.nasdaq.change}%)
📊 **Russell 2000:** ${levels.russell.price} (${levels.russell.change}%)`;
  
  console.log('Posting message...');
  console.log(message);
  
  // Find the message input
  const input = await discordPage.waitForSelector('div[role="textbox"]', { timeout: 10000 });
  await input.click();
  
  // Type the message
  await discordPage.keyboard.type(message);
  await discordPage.waitForTimeout(500);
  
  // Send it
  await discordPage.keyboard.press('Enter');
  
  console.log('✅ Posted successfully!');
  
  await browser.disconnect();
}

// Main execution
const channelId = process.argv[2];

if (!channelId) {
  console.log('Usage: node discord-post-levels.js <server-id>/<channel-id>');
  console.log('Example: node discord-post-levels.js 1468333686884663329/1234567890123456789');
  process.exit(1);
}

postToDiscord(channelId)
  .then(() => process.exit(0))
  .catch(err => {
    console.error('❌ Error:', err.message);
    process.exit(1);
  });
