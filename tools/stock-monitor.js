#!/usr/bin/env node

const fs = require('fs').promises;
const path = require('path');

const WATCHLIST_PATH = path.join(process.env.HOME, 'clawd/memory/watchlist.json');
const STATE_PATH = path.join(process.env.HOME, 'clawd/memory/stock-state.json');

// This is a placeholder - will need to integrate with a real API
// Options: Alpha Vantage, Yahoo Finance, Polygon.io, or scraping
async function getStockData(tickers) {
  // TODO: Implement actual API calls
  // For now, return structure that the monitoring system expects
  console.error('Stock API integration needed - placeholder only');
  return tickers.map(ticker => ({
    ticker,
    price: null,
    change: null,
    changePercent: null,
    error: 'API not yet configured'
  }));
}

async function loadWatchlist() {
  const data = await fs.readFile(WATCHLIST_PATH);
  const watchlist = JSON.parse(data);
  
  // Flatten all stocks into one array, mark priority
  const allStocks = [
    ...watchlist.stocks.priority.map(t => ({ ticker: t, priority: true })),
    ...watchlist.stocks.aiInfrastructure.map(t => ({ ticker: t, priority: false })),
    ...watchlist.stocks.megacapTech.map(t => ({ ticker: t, priority: false }))
  ];
  
  // Dedupe
  const seen = new Set();
  const unique = allStocks.filter(s => {
    if (seen.has(s.ticker)) return false;
    seen.add(s.ticker);
    return true;
  });
  
  return unique;
}

async function loadState() {
  try {
    const data = await fs.readFile(STATE_PATH);
    return JSON.parse(data);
  } catch (err) {
    return { lastPrices: {}, lastChecked: null };
  }
}

async function saveState(state) {
  await fs.writeFile(STATE_PATH, JSON.stringify(state, null, 2));
}

async function main() {
  const watchlist = await loadWatchlist();
  const state = await loadState();
  
  console.log(JSON.stringify({
    watchlist: watchlist.map(s => s.ticker),
    priorityStocks: watchlist.filter(s => s.priority).map(s => s.ticker),
    totalStocks: watchlist.length,
    note: 'Stock API integration required. Set up Alpha Vantage, Yahoo Finance, or Polygon.io API.'
  }, null, 2));
}

main().catch(err => {
  console.error('Error:', err.message);
  process.exit(1);
});
