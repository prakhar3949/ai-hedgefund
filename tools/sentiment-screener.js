#!/usr/bin/env node

/**
 * SENTIMENT SCREENER - Advanced multi-source financial sentiment analyzer
 * Combines Substack and Twitter data for real-time investment signals
 * Built for production hedge fund-grade analysis
 */

const fs = require('fs').promises;
const path = require('path');
const { execSync, spawn } = require('child_process');

// Paths
const CONFIG_PATH = path.join(__dirname, 'sentiment-screener-config.json');
const CACHE_PATH = path.join(process.env.HOME, 'clawd/memory/sentiment-screener-cache.json');
const DEDUPE_PATH = path.join(process.env.HOME, 'clawd/memory/sentiment-screener-seen.json');
const SUBSTACK_MONITOR = path.join(__dirname, 'substack-monitor.js');
const TWITTER_MONITOR = path.join(__dirname, 'twitter-monitor.sh');

// Global state
let config = null;
let cache = null;
let seenIds = new Set();

/**
 * Load configuration file
 */
async function loadConfig() {
  try {
    const data = await fs.readFile(CONFIG_PATH, 'utf8');
    config = JSON.parse(data);
    return config;
  } catch (err) {
    console.error('ERROR: Failed to load config:', err.message);
    process.exit(1);
  }
}

/**
 * Load cache (for performance optimization)
 */
async function loadCache() {
  try {
    const data = await fs.readFile(CACHE_PATH, 'utf8');
    const cached = JSON.parse(data);
    const now = Date.now();
    
    // Check if cache is still valid
    if (cached.timestamp && (now - cached.timestamp) < config.output.maxCacheAge * 1000) {
      return cached;
    }
    return null;
  } catch (err) {
    return null;
  }
}

/**
 * Save cache
 */
async function saveCache(data) {
  try {
    await fs.writeFile(CACHE_PATH, JSON.stringify({
      timestamp: Date.now(),
      data
    }, null, 2));
  } catch (err) {
    console.error('Warning: Failed to save cache:', err.message);
  }
}

/**
 * Load seen IDs for deduplication
 */
async function loadSeenIds() {
  try {
    const data = await fs.readFile(DEDUPE_PATH, 'utf8');
    const seen = JSON.parse(data);
    seenIds = new Set(seen.ids || []);
    
    // Prune old entries (keep last 1000)
    if (seenIds.size > 1000) {
      const arr = Array.from(seenIds);
      seenIds = new Set(arr.slice(-1000));
    }
  } catch (err) {
    seenIds = new Set();
  }
}

/**
 * Save seen IDs
 */
async function saveSeenIds() {
  try {
    await fs.writeFile(DEDUPE_PATH, JSON.stringify({
      ids: Array.from(seenIds),
      updated: new Date().toISOString()
    }, null, 2));
  } catch (err) {
    console.error('Warning: Failed to save seen IDs:', err.message);
  }
}

/**
 * Execute command with timeout
 */
function execWithTimeout(command, timeoutMs = 30000) {
  return new Promise((resolve, reject) => {
    let stdout = '';
    let stderr = '';
    
    const proc = spawn('bash', ['-c', command], {
      timeout: timeoutMs,
      maxBuffer: 10 * 1024 * 1024 // 10MB buffer
    });
    
    proc.stdout.on('data', (data) => {
      stdout += data.toString();
    });
    
    proc.stderr.on('data', (data) => {
      stderr += data.toString();
    });
    
    proc.on('close', (code) => {
      if (code === 0) {
        resolve(stdout);
      } else {
        reject(new Error(`Command failed: ${stderr}`));
      }
    });
    
    proc.on('error', (err) => {
      reject(err);
    });
    
    setTimeout(() => {
      proc.kill();
      reject(new Error('Command timeout'));
    }, timeoutMs);
  });
}

/**
 * Fetch Substack posts
 */
async function fetchSubstackPosts() {
  try {
    console.error('[Substack] Fetching new posts...');
    const output = await execWithTimeout(`node ${SUBSTACK_MONITOR}`, 20000);
    const posts = JSON.parse(output);
    console.error(`[Substack] Found ${posts.length} new posts`);
    return posts.map(post => ({
      source: 'substack',
      id: `substack:${post.id}`,
      author: post.from.split('@')[0].split('+')[0],
      title: post.subject,
      url: post.url,
      timestamp: Date.now(),
      rawData: post
    }));
  } catch (err) {
    console.error('[Substack] Error:', err.message);
    return [];
  }
}

/**
 * Fetch Twitter home timeline
 */
async function fetchTwitterHome() {
  try {
    console.error('[Twitter] Fetching home timeline...');
    const maxTweets = config.twitter.maxHomeTimeline;
    const output = await execWithTimeout(`${TWITTER_MONITOR} home -n ${maxTweets}`, 25000);
    
    // Parse bird CLI output (JSON lines)
    const lines = output.trim().split('\n').filter(l => l.trim());
    const tweets = [];
    
    for (const line of lines) {
      try {
        const tweet = JSON.parse(line);
        tweets.push({
          source: 'twitter',
          type: 'home',
          id: `twitter:${tweet.id || tweet.rest_id || Date.now()}`,
          author: tweet.author?.username || tweet.legacy?.screen_name || 'unknown',
          text: tweet.text || tweet.legacy?.full_text || '',
          timestamp: Date.now(),
          rawData: tweet
        });
      } catch (parseErr) {
        // Skip malformed JSON
        continue;
      }
    }
    
    console.error(`[Twitter] Found ${tweets.length} tweets from home timeline`);
    return tweets;
  } catch (err) {
    console.error('[Twitter Home] Error:', err.message);
    return [];
  }
}

/**
 * Fetch Twitter search results
 */
async function fetchTwitterSearch() {
  try {
    const allTweets = [];
    const queries = config.twitter.searchQueries;
    const maxPerQuery = config.twitter.maxTweetsPerQuery;
    
    for (const query of queries) {
      try {
        console.error(`[Twitter Search] Query: "${query}"`);
        const output = await execWithTimeout(
          `${TWITTER_MONITOR} search "${query}" -n ${maxPerQuery}`,
          25000
        );
        
        const lines = output.trim().split('\n').filter(l => l.trim());
        
        for (const line of lines) {
          try {
            const tweet = JSON.parse(line);
            allTweets.push({
              source: 'twitter',
              type: 'search',
              query: query,
              id: `twitter:${tweet.id || tweet.rest_id || Date.now()}`,
              author: tweet.author?.username || tweet.legacy?.screen_name || 'unknown',
              text: tweet.text || tweet.legacy?.full_text || '',
              timestamp: Date.now(),
              rawData: tweet
            });
          } catch (parseErr) {
            continue;
          }
        }
      } catch (searchErr) {
        console.error(`[Twitter Search] Query "${query}" failed:`, searchErr.message);
        continue;
      }
    }
    
    console.error(`[Twitter Search] Found ${allTweets.length} total tweets from ${queries.length} queries`);
    return allTweets;
  } catch (err) {
    console.error('[Twitter Search] Error:', err.message);
    return [];
  }
}

/**
 * Extract stock/asset mentions from text
 */
function extractMentions(text) {
  const mentions = {
    stocks: [],
    crypto: [],
    sectors: [],
    macro: []
  };
  
  const upperText = text.toUpperCase();
  
  // Check stocks (exact ticker match with word boundaries)
  const allStocks = [
    ...config.watchlist.stocks.holdings,
    ...config.watchlist.stocks.priority,
    ...config.watchlist.stocks.watchlist
  ];
  
  for (const ticker of allStocks) {
    const regex = new RegExp(`\\b\\$?${ticker}\\b`, 'i');
    if (regex.test(text)) {
      mentions.stocks.push(ticker);
    }
  }
  
  // Check crypto
  for (const crypto of config.watchlist.crypto) {
    const regex = new RegExp(`\\b\\$?${crypto}\\b`, 'i');
    if (regex.test(text)) {
      mentions.crypto.push(crypto);
    }
  }
  
  // Check sectors
  for (const sector of config.watchlist.sectors) {
    if (upperText.includes(sector.toUpperCase())) {
      mentions.sectors.push(sector);
    }
  }
  
  // Check macro
  for (const macro of config.watchlist.macro) {
    if (upperText.includes(macro.toUpperCase())) {
      mentions.macro.push(macro);
    }
  }
  
  return mentions;
}

/**
 * Analyze sentiment of text
 */
function analyzeSentiment(text) {
  const upperText = text.toUpperCase();
  const sentiment = {
    bullish: 0,
    bearish: 0,
    neutral: 0,
    urgent: false,
    contrarian: false,
    signals: []
  };
  
  // Check bullish keywords
  for (const keyword of config.sentiment.bullishKeywords) {
    if (upperText.includes(keyword.toUpperCase())) {
      sentiment.bullish++;
      sentiment.signals.push(`bullish:${keyword}`);
    }
  }
  
  // Check bearish keywords
  for (const keyword of config.sentiment.bearishKeywords) {
    if (upperText.includes(keyword.toUpperCase())) {
      sentiment.bearish++;
      sentiment.signals.push(`bearish:${keyword}`);
    }
  }
  
  // Check urgent keywords
  for (const keyword of config.sentiment.urgentKeywords) {
    if (upperText.includes(keyword.toUpperCase())) {
      sentiment.urgent = true;
      sentiment.signals.push(`urgent:${keyword}`);
    }
  }
  
  // Check contrarian keywords
  for (const keyword of config.sentiment.contrarianKeywords) {
    if (upperText.includes(keyword.toUpperCase())) {
      sentiment.contrarian = true;
      sentiment.signals.push(`contrarian:${keyword}`);
    }
  }
  
  // Determine overall sentiment
  if (sentiment.bullish > sentiment.bearish) {
    sentiment.overall = 'bullish';
    sentiment.strength = sentiment.bullish;
  } else if (sentiment.bearish > sentiment.bullish) {
    sentiment.overall = 'bearish';
    sentiment.strength = sentiment.bearish;
  } else {
    sentiment.overall = 'neutral';
    sentiment.strength = 0;
  }
  
  return sentiment;
}

/**
 * Calculate priority score for an item
 */
function calculatePriority(item, mentions, sentiment) {
  let score = 0;
  const weights = config.scoring.weights;
  
  // Urgent keywords
  if (sentiment.urgent) {
    score += weights.urgentKeyword;
  }
  
  // Holdings mentions
  const holdingsMentioned = mentions.stocks.filter(ticker => 
    config.watchlist.stocks.holdings.includes(ticker)
  );
  score += holdingsMentioned.length * weights.holdingMention;
  
  // Priority mentions
  const priorityMentioned = mentions.stocks.filter(ticker => 
    config.watchlist.stocks.priority.includes(ticker)
  );
  score += priorityMentioned.length * weights.priorityMention;
  
  // Strong sentiment
  if (sentiment.strength >= 3) {
    score += weights.strongSentiment;
  }
  
  // Contrarian signal
  if (sentiment.contrarian) {
    score += weights.contrarianSignal;
  }
  
  // Volume indicators (multiple mentions, retweets, etc.)
  const totalMentions = mentions.stocks.length + mentions.crypto.length;
  if (totalMentions >= 3) {
    score += weights.volumeIndicator;
  }
  
  return Math.min(score, 100); // Cap at 100
}

/**
 * Categorize based on priority score
 */
function categorizePriority(score) {
  const thresholds = config.scoring.thresholds;
  
  if (score >= thresholds.urgent) return 'urgent';
  if (score >= thresholds.high) return 'high';
  if (score >= thresholds.medium) return 'medium';
  return 'low';
}

/**
 * Determine category based on mentions
 */
function determineCategory(mentions) {
  if (mentions.stocks.length > 0) return 'stocks';
  if (mentions.crypto.length > 0) return 'crypto';
  if (mentions.sectors.length > 0) return 'sectors';
  if (mentions.macro.length > 0) return 'macro';
  return 'general';
}

/**
 * Process and analyze all items
 */
function analyzeItems(items) {
  const analyzed = [];
  
  for (const item of items) {
    // Skip if already seen
    if (seenIds.has(item.id)) {
      continue;
    }
    
    // Extract content
    const content = item.text || item.title || '';
    if (!content) continue;
    
    // Extract mentions
    const mentions = extractMentions(content);
    
    // Skip if no relevant mentions
    const hasMentions = mentions.stocks.length > 0 || 
                       mentions.crypto.length > 0 || 
                       mentions.sectors.length > 0 || 
                       mentions.macro.length > 0;
    
    if (!hasMentions) {
      seenIds.add(item.id);
      continue;
    }
    
    // Analyze sentiment
    const sentiment = analyzeSentiment(content);
    
    // Calculate priority
    const priorityScore = calculatePriority(item, mentions, sentiment);
    const priority = categorizePriority(priorityScore);
    
    // Determine category
    const category = determineCategory(mentions);
    
    // Build analyzed item
    const analyzedItem = {
      id: item.id,
      source: item.source,
      type: item.type,
      author: item.author,
      content: content,
      url: item.url || null,
      timestamp: item.timestamp,
      mentions: mentions,
      sentiment: sentiment,
      priority: priority,
      priorityScore: priorityScore,
      category: category,
      query: item.query || null
    };
    
    // Include raw data if configured
    if (config.output.includeRawData) {
      analyzedItem.rawData = item.rawData;
    }
    
    analyzed.push(analyzedItem);
    seenIds.add(item.id);
  }
  
  // Sort by priority score (highest first)
  analyzed.sort((a, b) => b.priorityScore - a.priorityScore);
  
  return analyzed;
}

/**
 * Detect multi-source confirmation
 */
function detectConfirmations(analyzed) {
  const tickerSources = {};
  
  // Group by ticker
  for (const item of analyzed) {
    for (const ticker of item.mentions.stocks) {
      if (!tickerSources[ticker]) {
        tickerSources[ticker] = new Set();
      }
      tickerSources[ticker].add(item.source);
    }
  }
  
  // Find confirmations (same ticker from multiple sources)
  const confirmations = [];
  for (const [ticker, sources] of Object.entries(tickerSources)) {
    if (sources.size > 1) {
      confirmations.push({
        ticker,
        sources: Array.from(sources),
        count: sources.size
      });
    }
  }
  
  // Boost priority for items with confirmations
  for (const item of analyzed) {
    for (const confirmation of confirmations) {
      if (item.mentions.stocks.includes(confirmation.ticker)) {
        item.priorityScore += config.scoring.weights.multiSourceConfirmation;
        item.priorityScore = Math.min(item.priorityScore, 100);
        item.priority = categorizePriority(item.priorityScore);
        item.confirmation = confirmation;
      }
    }
  }
  
  return confirmations;
}

/**
 * Generate human-readable summary
 */
function generateSummary(analyzed, confirmations) {
  const lines = [];
  
  lines.push('═══════════════════════════════════════════════════════');
  lines.push('  SENTIMENT SCREENER REPORT');
  lines.push(`  ${new Date().toLocaleString('en-US', { timeZone: 'America/Los_Angeles' })} PST`);
  lines.push('═══════════════════════════════════════════════════════');
  lines.push('');
  
  // Summary stats
  const urgent = analyzed.filter(i => i.priority === 'urgent').length;
  const high = analyzed.filter(i => i.priority === 'high').length;
  const medium = analyzed.filter(i => i.priority === 'medium').length;
  const low = analyzed.filter(i => i.priority === 'low').length;
  
  lines.push('📊 SUMMARY');
  lines.push(`   Total Signals: ${analyzed.length}`);
  lines.push(`   🚨 Urgent: ${urgent} | 🔴 High: ${high} | 🟡 Medium: ${medium} | ⚪ Low: ${low}`);
  lines.push('');
  
  // Multi-source confirmations
  if (confirmations.length > 0) {
    lines.push('🔍 MULTI-SOURCE CONFIRMATIONS');
    for (const conf of confirmations) {
      lines.push(`   ${conf.ticker}: ${conf.sources.join(' + ')}`);
    }
    lines.push('');
  }
  
  // Top signals by priority
  const topSignals = analyzed.slice(0, 20); // Top 20
  
  for (const priority of ['urgent', 'high', 'medium']) {
    const items = topSignals.filter(i => i.priority === priority);
    if (items.length === 0) continue;
    
    const emoji = priority === 'urgent' ? '🚨' : priority === 'high' ? '🔴' : '🟡';
    lines.push(`${emoji} ${priority.toUpperCase()} PRIORITY`);
    lines.push('───────────────────────────────────────────────────────');
    
    for (const item of items) {
      const tickers = [...item.mentions.stocks, ...item.mentions.crypto].join(', ');
      const sentiment = item.sentiment.overall === 'bullish' ? '📈' : 
                       item.sentiment.overall === 'bearish' ? '📉' : '➡️';
      
      lines.push('');
      lines.push(`${sentiment} [${item.priorityScore}] ${tickers || item.category.toUpperCase()}`);
      lines.push(`   Source: ${item.source} | Author: @${item.author}`);
      
      // Sentiment indicators
      const indicators = [];
      if (item.sentiment.bullish > 0) indicators.push(`+${item.sentiment.bullish} bullish`);
      if (item.sentiment.bearish > 0) indicators.push(`-${item.sentiment.bearish} bearish`);
      if (item.sentiment.urgent) indicators.push('⚠️ URGENT');
      if (item.sentiment.contrarian) indicators.push('🔄 CONTRARIAN');
      if (item.confirmation) indicators.push(`✓ ${item.confirmation.count} sources`);
      
      if (indicators.length > 0) {
        lines.push(`   Signals: ${indicators.join(', ')}`);
      }
      
      // Content preview (truncate)
      const preview = item.content.length > 150 ? 
                     item.content.substring(0, 150) + '...' : 
                     item.content;
      lines.push(`   "${preview}"`);
      
      if (item.url) {
        lines.push(`   🔗 ${item.url}`);
      }
    }
    
    lines.push('');
  }
  
  lines.push('═══════════════════════════════════════════════════════');
  
  return lines.join('\n');
}

/**
 * Main execution
 */
async function main() {
  const startTime = Date.now();
  
  try {
    console.error('═══════════════════════════════════════════════════════');
    console.error('  SENTIMENT SCREENER');
    console.error('═══════════════════════════════════════════════════════\n');
    
    // Load config
    await loadConfig();
    console.error('[Config] Loaded successfully');
    
    // Load cache and seen IDs
    await loadSeenIds();
    console.error(`[Dedupe] Loaded ${seenIds.size} seen IDs`);
    
    // Fetch data from all sources (parallel execution)
    const allItems = [];
    
    if (config.execution.parallelExecution) {
      const [substackPosts, twitterHome, twitterSearch] = await Promise.allSettled([
        fetchSubstackPosts(),
        fetchTwitterHome(),
        fetchTwitterSearch()
      ]);
      
      if (substackPosts.status === 'fulfilled') allItems.push(...substackPosts.value);
      if (twitterHome.status === 'fulfilled') allItems.push(...twitterHome.value);
      if (twitterSearch.status === 'fulfilled') allItems.push(...twitterSearch.value);
    } else {
      allItems.push(...await fetchSubstackPosts());
      allItems.push(...await fetchTwitterHome());
      allItems.push(...await fetchTwitterSearch());
    }
    
    console.error(`\n[Aggregation] Collected ${allItems.length} total items`);
    
    // Analyze all items
    console.error('[Analysis] Processing sentiment and mentions...');
    const analyzed = analyzeItems(allItems);
    console.error(`[Analysis] ${analyzed.length} relevant signals after filtering`);
    
    // Detect multi-source confirmations
    const confirmations = detectConfirmations(analyzed);
    console.error(`[Confirmations] Found ${confirmations.length} multi-source signals`);
    
    // Save seen IDs
    await saveSeenIds();
    
    // Generate output
    const summary = generateSummary(analyzed, confirmations);
    
    // Output JSON to stdout
    const output = {
      timestamp: new Date().toISOString(),
      executionTime: Date.now() - startTime,
      summary: {
        total: analyzed.length,
        byPriority: {
          urgent: analyzed.filter(i => i.priority === 'urgent').length,
          high: analyzed.filter(i => i.priority === 'high').length,
          medium: analyzed.filter(i => i.priority === 'medium').length,
          low: analyzed.filter(i => i.priority === 'low').length
        },
        byCategory: {
          stocks: analyzed.filter(i => i.category === 'stocks').length,
          crypto: analyzed.filter(i => i.category === 'crypto').length,
          sectors: analyzed.filter(i => i.category === 'sectors').length,
          macro: analyzed.filter(i => i.category === 'macro').length,
          general: analyzed.filter(i => i.category === 'general').length
        },
        confirmations: confirmations
      },
      signals: analyzed,
      humanReadable: summary
    };
    
    console.log(JSON.stringify(output, null, 2));
    
    // Also write to stderr for logging
    console.error('\n' + summary);
    console.error(`\n[Complete] Execution time: ${output.executionTime}ms`);
    
  } catch (err) {
    console.error('\n[FATAL ERROR]', err.message);
    console.error(err.stack);
    process.exit(1);
  }
}

/**
 * Initialize config for module usage (testing)
 */
async function initConfig() {
  if (!config) {
    await loadConfig();
  }
  return config;
}

// Execute
if (require.main === module) {
  main();
} else {
  // Load config synchronously for module usage
  const fs = require('fs');
  try {
    const data = fs.readFileSync(CONFIG_PATH, 'utf8');
    config = JSON.parse(data);
  } catch (err) {
    console.error('Warning: Could not load config for module usage');
  }
}

module.exports = { analyzeItems, extractMentions, analyzeSentiment, calculatePriority, initConfig };
