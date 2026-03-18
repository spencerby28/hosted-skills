/**
 * ChatGPT Conversation Exporter — Background Service Worker
 *
 * How it works:
 * 1. User clicks "Capture Session" while on chatgpt.com
 * 2. We intercept the next network request to grab auth headers
 * 3. User clicks "Export" — we call ChatGPT's internal API to list & fetch all conversations
 * 4. Conversations are packaged into a downloadable JSON or Markdown file
 */

let captureArmed = false;
let exportRunning = false;
let keepAliveInterval = null;

const DELAY_MS = 400;       // pause between API calls to avoid rate limits
const PAGE_SIZE = 28;        // conversations per page (ChatGPT default)
const MAX_RETRIES = 5;       // retry on 429 rate-limit responses

// ── Service Worker Keepalive ───────────────────────────────────────────────
// MV3 service workers get killed after ~30s idle or ~5min total.
// We ping chrome.storage during long exports to stay alive.

function startKeepAlive() {
  if (keepAliveInterval) return;
  keepAliveInterval = setInterval(() => {
    chrome.storage.local.get('keepAlive');
  }, 20000);
}

function stopKeepAlive() {
  if (keepAliveInterval) {
    clearInterval(keepAliveInterval);
    keepAliveInterval = null;
  }
}

// ── Token Capture ──────────────────────────────────────────────────────────

chrome.webRequest.onBeforeSendHeaders.addListener(
  (details) => {
    if (!captureArmed) return;
    if (!details.url.includes('chatgpt.com')) return;

    const headers = details.requestHeaders || [];
    const authHeader = headers.find((h) => h.name.toLowerCase() === 'authorization');
    if (!authHeader?.value) return;

    const headerMap = {};
    for (const header of headers) {
      const name = header.name.toLowerCase();
      if (name === 'authorization' || name.startsWith('oai-')) {
        headerMap[name] = header.value || '';
      }
    }

    chrome.storage.local.set({ capturedHeaders: headerMap });
    captureArmed = false;

    sendProgress('ready', 'Session captured! You can now export your conversations.');
  },
  { urls: ['https://chatgpt.com/backend-api/*'] },
  ['requestHeaders', 'extraHeaders']
);

// ── Message Handler ────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type === 'ARM_CAPTURE') {
    captureArmed = true;
    sendResponse({ ok: true });
    return;
  }

  if (message.type === 'GET_STATUS') {
    sendResponse({ exportRunning });
    return;
  }

  if (message.type === 'START_EXPORT') {
    if (exportRunning) {
      sendResponse({ error: 'Export already in progress.' });
      return;
    }
    exportRunning = true;
    startKeepAlive();
    runExport(message.format || 'json')
      .catch((err) => {
        sendProgress('error', err.message || 'Export failed');
      })
      .finally(() => {
        exportRunning = false;
        stopKeepAlive();
      });
    sendResponse({ ok: true });
    return;
  }
});

// ── Export Logic ────────────────────────────────────────────────────────────

async function runExport(format) {
  const stored = await chrome.storage.local.get('capturedHeaders');
  const headers = stored.capturedHeaders;

  if (!headers || !headers.authorization) {
    sendProgress('error', 'No session captured yet. Click "Capture Session" first, then reload ChatGPT.');
    return;
  }

  // Step 1: List all conversations
  sendProgress('listing', 'Finding your conversations...');
  const conversations = await listAllConversations(headers);

  if (conversations.length === 0) {
    sendProgress('error', 'No conversations found. Make sure you are logged into ChatGPT.');
    return;
  }

  sendProgress('fetching', `Found ${conversations.length} conversations. Downloading details...`);

  // Step 2: Fetch full details for each conversation
  const fullConversations = [];
  for (let i = 0; i < conversations.length; i++) {
    const conv = conversations[i];
    try {
      const detail = await fetchConversation(headers, conv.id);
      fullConversations.push({
        id: conv.id,
        title: conv.title || 'Untitled',
        create_time: conv.create_time,
        update_time: conv.update_time,
        conversation: detail
      });
    } catch (err) {
      // Skip failed conversations but keep going
      fullConversations.push({
        id: conv.id,
        title: conv.title || 'Untitled',
        create_time: conv.create_time,
        update_time: conv.update_time,
        error: err.message
      });
    }

    sendProgress('fetching', `Downloaded ${i + 1} of ${conversations.length}: "${conv.title || 'Untitled'}"`);
    await sleep(DELAY_MS);
  }

  // Step 3: Build the output file
  sendProgress('building', 'Building your export file...');

  let fileContent, fileName, mimeType;

  if (format === 'markdown') {
    fileContent = buildMarkdown(fullConversations);
    fileName = `chatgpt-export-${dateStamp()}.md`;
    mimeType = 'text/markdown';
  } else {
    fileContent = JSON.stringify({
      exported_at: new Date().toISOString(),
      conversation_count: fullConversations.length,
      conversations: fullConversations
    }, null, 2);
    fileName = `chatgpt-export-${dateStamp()}.json`;
    mimeType = 'application/json';
  }

  // Step 4: Trigger download via data URI
  // (URL.createObjectURL is not available in service workers)
  sendProgress('building', 'Preparing download...');
  const dataUrl = await toDataUrl(fileContent, mimeType);

  chrome.downloads.download({
    url: dataUrl,
    filename: fileName,
    saveAs: true
  }, () => {
    if (chrome.runtime.lastError) {
      sendProgress('error', `Download failed: ${chrome.runtime.lastError.message}`);
      return;
    }
    sendProgress('done', `Export complete! ${fullConversations.length} conversations saved to ${fileName}`);
    chrome.storage.local.set({
      lastExportAt: Date.now(),
      lastExportCount: fullConversations.length
    });
  });
}

// ── Data URL Builder ──────────────────────────────────────────────────────
// Converts a string to a base64 data URL, safe for service workers.

async function toDataUrl(text, mimeType) {
  const encoder = new TextEncoder();
  const uint8 = encoder.encode(text);
  // Convert Uint8Array to base64 in chunks to avoid call stack limits
  const CHUNK = 32768;
  let binary = '';
  for (let i = 0; i < uint8.length; i += CHUNK) {
    binary += String.fromCharCode(...uint8.subarray(i, i + CHUNK));
  }
  const base64 = btoa(binary);
  return `data:${mimeType};base64,${base64}`;
}

// ── ChatGPT API Calls ─────────────────────────────────────────────────────

async function listAllConversations(headers) {
  const items = [];
  let offset = 0;

  while (true) {
    const url =
      `https://chatgpt.com/backend-api/conversations?offset=${offset}` +
      `&limit=${PAGE_SIZE}&order=updated&is_archived=false`;
    const data = await fetchJson(url, headers);
    const pageItems = Array.isArray(data.items) ? data.items : [];
    items.push(...pageItems);

    sendProgress('listing', `Found ${items.length} conversations so far...`);

    if (pageItems.length < PAGE_SIZE) break;
    offset += PAGE_SIZE;
    await sleep(DELAY_MS);
  }

  return items;
}

async function fetchConversation(headers, conversationId) {
  const url = `https://chatgpt.com/backend-api/conversation/${conversationId}`;
  return fetchJson(url, headers);
}

// ── Markdown Builder ───────────────────────────────────────────────────────

function buildMarkdown(conversations) {
  const lines = [
    `# ChatGPT Export`,
    ``,
    `Exported: ${new Date().toISOString()}`,
    `Total conversations: ${conversations.length}`,
    ``,
    `---`,
    ``
  ];

  for (const conv of conversations) {
    lines.push(`## ${conv.title}`);
    lines.push(`*Created: ${formatDate(conv.create_time)} | Updated: ${formatDate(conv.update_time)}*`);
    lines.push(``);

    if (conv.error) {
      lines.push(`> Failed to download: ${conv.error}`);
      lines.push(``);
      lines.push(`---`);
      lines.push(``);
      continue;
    }

    const messages = extractMessages(conv.conversation);
    for (const msg of messages) {
      const role = msg.role === 'user' ? 'You' : 'ChatGPT';
      lines.push(`**${role}:**`);
      lines.push(``);
      lines.push(msg.content);
      lines.push(``);
    }

    lines.push(`---`);
    lines.push(``);
  }

  return lines.join('\n');
}

function extractMessages(conversation) {
  if (!conversation || !conversation.mapping) return [];

  const messages = [];
  const mapping = conversation.mapping;
  const visited = new Set();

  // Find root node (no parent)
  let rootId = null;
  for (const [id, node] of Object.entries(mapping)) {
    if (!node.parent) {
      rootId = id;
      break;
    }
  }

  if (!rootId) return [];

  // Walk the tree following the last child (main conversation thread)
  function walk(nodeId) {
    if (!nodeId || visited.has(nodeId)) return;
    visited.add(nodeId);

    const node = mapping[nodeId];
    if (!node) return;

    const msg = node.message;
    if (msg && msg.content && msg.content.parts) {
      const role = msg.author?.role;
      if (role === 'user' || role === 'assistant') {
        const textParts = msg.content.parts.filter((p) => typeof p === 'string');
        const content = textParts.join('\n').trim();
        if (content) {
          messages.push({ role, content });
        }
      }
    }

    const children = node.children || [];
    if (children.length > 0) {
      walk(children[children.length - 1]);
    }
  }

  walk(rootId);
  return messages;
}

// ── Utilities ──────────────────────────────────────────────────────────────

async function fetchJson(url, headers) {
  const response = await fetchWithRetry(url, {
    method: 'GET',
    headers
  });

  if (!response.ok) {
    let snippet = '';
    try { snippet = (await response.text()).slice(0, 200); } catch {}
    throw new Error(`API error ${response.status}: ${snippet}`);
  }

  return response.json();
}

async function fetchWithRetry(url, options, attempt = 0) {
  let response;
  try {
    response = await fetch(url, options);
  } catch (err) {
    // Network error — retry if we haven't exhausted attempts
    if (attempt < MAX_RETRIES) {
      const delay = Math.min(8000, DELAY_MS * Math.pow(2, attempt));
      sendProgress('waiting', `Network error — retrying in ${Math.round(delay / 1000)}s...`);
      await sleep(delay);
      return fetchWithRetry(url, options, attempt + 1);
    }
    throw err;
  }

  if (response.ok) return response;

  if ((response.status === 429 || response.status >= 500) && attempt < MAX_RETRIES) {
    const delay = Math.min(8000, DELAY_MS * Math.pow(2, attempt));
    sendProgress('waiting', `${response.status === 429 ? 'Rate limited' : `Server error ${response.status}`} — waiting ${Math.round(delay / 1000)}s...`);
    await sleep(delay);
    return fetchWithRetry(url, options, attempt + 1);
  }

  return response;
}

function sendProgress(status, message) {
  chrome.runtime.sendMessage({ type: 'PROGRESS', status, message }).catch(() => {});
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function dateStamp() {
  return new Date().toISOString().slice(0, 10);
}

function formatDate(timestamp) {
  if (!timestamp) return 'unknown';
  return new Date(timestamp * 1000).toLocaleDateString('en-US', {
    year: 'numeric', month: 'short', day: 'numeric'
  });
}
