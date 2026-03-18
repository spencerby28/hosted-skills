---
name: chatgpt-export
description: Walk a user through exporting all their ChatGPT conversations using a Chrome extension, even from Team/Business accounts where OpenAI has disabled the built-in export.
---

# ChatGPT Conversation Exporter

## The Problem

OpenAI **does not allow** ChatGPT Team and Business account users to export their conversation data. The "Export data" button in Settings > Data Controls is completely missing for these accounts. OpenAI support's official recommendation is to manually copy-paste each conversation — which is absurd for anyone with more than a handful of chats.

This skill provides a lightweight Chrome extension that solves this by using the same authenticated connection your browser already has with ChatGPT to download all conversations and save them as a file.

## How It Works (Plain English)

When you use ChatGPT in your browser, your browser sends a special login token with every request. This extension watches for that token, then uses it to ask ChatGPT's servers for a list of all your conversations and their contents — the exact same way the ChatGPT website does when it shows your sidebar. It then packages everything into a single downloadable file (JSON or Markdown).

**Nothing is sent to any third-party server.** The extension talks directly to chatgpt.com using your existing login, then saves the file to your computer.

## Files

The extension consists of these files, all hosted at `https://skills.sb28.ai/chatgpt-export/`:

| File | Purpose |
|---|---|
| `manifest.json` | Chrome extension configuration |
| `background.js` | Token capture, API scraping, file export logic |
| `popup.html` | The extension's popup interface |
| `popup.js` | Popup button handlers and progress display |
| `popup.css` | Styling |
| `icon48.png` | Extension icon (small) |
| `icon128.png` | Extension icon (large) |

## Setup Instructions

Guide the user through these steps. They need Google Chrome and a ChatGPT account.

### Step 1: Download the Extension Files

Create a folder on the computer and download all the extension files into it:

```bash
mkdir -p ~/chatgpt-exporter
cd ~/chatgpt-exporter
curl -O https://skills.sb28.ai/chatgpt-export/manifest.json
curl -O https://skills.sb28.ai/chatgpt-export/background.js
curl -O https://skills.sb28.ai/chatgpt-export/popup.html
curl -O https://skills.sb28.ai/chatgpt-export/popup.js
curl -O https://skills.sb28.ai/chatgpt-export/popup.css
curl -O https://skills.sb28.ai/chatgpt-export/icon48.png
curl -O https://skills.sb28.ai/chatgpt-export/icon128.png
```

**For non-technical users:** If the user is not comfortable with the terminal, guide them to:
1. Create a new empty folder on their Desktop called `chatgpt-exporter`
2. Open each URL above in their browser (the file will display as text)
3. Right-click > "Save As" into that folder, keeping the exact filename
4. For the .png files, right-click the link > "Save link as"

Alternatively, if the files are available as a ZIP, they can download and unzip that instead.

### Step 2: Load the Extension in Chrome

1. Open Google Chrome
2. Type `chrome://extensions` in the address bar and press Enter
3. Find the **"Developer mode"** toggle in the top-right corner and turn it **ON** (it should turn blue)
4. Click the **"Load unpacked"** button that appears
5. Navigate to the `chatgpt-exporter` folder they created and select it
6. They should see **"ChatGPT Conversation Exporter"** appear in the extensions list

### Step 3: Pin the Extension (Recommended)

1. Click the **puzzle piece icon** in Chrome's toolbar (top-right area)
2. Find **"ChatGPT Conversation Exporter"** in the dropdown
3. Click the **pin icon** next to it so the green icon stays visible in the toolbar

## Usage Instructions

### Capturing the Session

1. Go to [chatgpt.com](https://chatgpt.com) and make sure they're logged in
2. Click the green extension icon in the toolbar — a popup appears
3. Click **"Capture Session"**
4. The status will say "Waiting for reload..."
5. Go back to the ChatGPT tab and **reload the page** (Ctrl+R on Windows, Cmd+R on Mac)
6. Click the extension icon again — it should say **"Session captured! Ready to export."**

### Exporting Conversations

1. Click the extension icon
2. Choose a format:
   - **"Export as JSON"** — structured data, good for importing into other tools or uploading to a Claude Project
   - **"Export as Markdown"** — readable text, good for reading, searching, or printing
3. The status bar shows progress as it downloads each conversation
4. When done, Chrome opens a "Save As" dialog — pick where to save the file
5. Done!

### Time Estimate

The extension downloads about 1 conversation per second (it deliberately goes slow to avoid rate limits). Rough estimates:
- 50 conversations: ~1 minute
- 200 conversations: ~4 minutes
- 500 conversations: ~9 minutes
- 1000+ conversations: ~17+ minutes

The user can keep using other Chrome tabs while it runs.

## Troubleshooting

### "No session captured yet"
The user needs to click "Capture Session" in the popup, then reload their ChatGPT tab. The extension needs to see one network request to grab the login token.

### "Rate limited — waiting..."
ChatGPT is throttling requests. This is normal and expected. The extension automatically waits and retries with exponential backoff. Just be patient.

### "API error 403"
The session has expired. The user should:
1. Close and reopen their ChatGPT tab
2. Make sure they can see their conversations (they're logged in)
3. Click "Capture Session" again
4. Reload the ChatGPT tab
5. Try exporting again

### "API error 401"
Same as 403 — session expired. Re-capture.

### Extension doesn't appear in Chrome
- Make sure Developer Mode is ON in chrome://extensions
- Make sure they selected the correct folder (the one containing manifest.json)
- Try clicking "Load unpacked" again

### Export file is very large
Normal for accounts with many conversations. JSON files are larger than Markdown. A 500-conversation account typically produces a 50-100MB JSON file.

### Some conversations show "Failed to download"
The extension skips conversations it can't fetch (deleted, corrupted, or access-restricted) and continues with the rest. The error is noted in the export file but doesn't stop the process.

## What to Do with the Export

### Upload to a Claude Project
The most powerful option. In Claude:
1. Create a new Project (or use an existing one)
2. Upload the JSON or Markdown file to the Project's knowledge base
3. Now the user can ask Claude questions about their entire ChatGPT history:
   - "What topics did I discuss most?"
   - "Find the conversation where I talked about X"
   - "Summarize my conversations about Y"
   - "What advice did ChatGPT give me about Z?"

### Read in Any Text Editor
The Markdown export can be opened in any text editor, Word, Google Docs, or Notes app. Use Ctrl+F / Cmd+F to search.

### Import into Other Tools
The JSON export follows a standard structure and can be parsed by any programming language or data tool.

## Privacy & Safety

- The extension ONLY communicates with chatgpt.com — no other servers
- No data is sent to any third party
- All processing happens locally in the browser
- The file is saved directly to the user's computer
- The extension requires "Developer mode" because it's not on the Chrome Web Store — it's a private tool
- The full source code is readable in the extension folder (5 small files)

## Technical Details

### Token Capture Mechanism
Uses Chrome's `webRequest.onBeforeSendHeaders` API to intercept requests to `chatgpt.com/backend-api/*`. Extracts the `Authorization` header and any `oai-*` headers. These are stored in `chrome.storage.local`.

### API Endpoints Used
- `GET /backend-api/conversations?offset={n}&limit=28&order=updated` — paginated conversation list
- `GET /backend-api/conversation/{id}` — full conversation detail with message tree

### Rate Limit Handling
- 400ms delay between requests
- Exponential backoff on 429 responses (doubling wait time, max 8 seconds)
- Up to 5 retries before failing

### Conversation Tree Parsing
ChatGPT stores conversations as a tree (mapping of node IDs). The Markdown exporter walks from the root node, following the last child at each branch to reconstruct the main conversation thread. Only `user` and `assistant` messages are included (system messages and tool calls are filtered out).
