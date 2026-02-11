# X Lists Skill

Export X (Twitter) list members to JSON via browser automation.

## Assets

Download these files to use this skill:

| File | Description |
|------|-------------|
| [export_list.js](https://skills.sb28.ai/x-lists/export_list.js) | Main export script (Node.js) |
| [package.json](https://skills.sb28.ai/x-lists/package.json) | Dependencies |

```bash
# Quick setup
mkdir x-lists && cd x-lists
curl -O https://skills.sb28.ai/x-lists/export_list.js
curl -O https://skills.sb28.ai/x-lists/package.json
npm install
```

## Prerequisites

### 1. Chrome with Remote Debugging

Close all Chrome windows, then start with debug port:

```bash
# macOS Chrome
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222

# macOS Arc
/Applications/Arc.app/Contents/MacOS/Arc --remote-debugging-port=9222

# Windows Chrome
chrome.exe --remote-debugging-port=9222

# Linux Chrome
google-chrome --remote-debugging-port=9222
```

### 2. Log into X

Open x.com in the debug browser and log in.

### 3. Verify Connection

```bash
curl -s "http://localhost:9222/json/version"
```

## Usage

### Check Connection
```bash
node export_list.js --check
```

### Discover Your Lists
```bash
node export_list.js --discover
```

Output:
```
Found 5 lists:

  🌐 My Public List
     ID: 1234567890
     Members: 45

  🔒 My Private List
     ID: 0987654321
     Members: 12
```

### Export List Members

```bash
# By ID
node export_list.js --list-id 1234567890 -o members.json

# By name (partial match)
node export_list.js --list-name "Gauntlet" -o gauntlet.json

# Quiet mode (no progress)
node export_list.js --list-id 1234567890 -o members.json -q
```

### Custom CDP URL

If browser is on a different port or remote machine:
```bash
node export_list.js --cdp-url http://192.168.1.100:9222 --discover
```

## Output Format

```json
{
  "list": {
    "id": "1876334018150678826",
    "name": "My List",
    "description": "List description",
    "memberCount": 115,
    "subscriberCount": 302,
    "mode": "Private",
    "createdAt": 1736187865000
  },
  "exportedAt": "2026-02-10T20:00:00Z",
  "memberCount": 115,
  "members": [
    {
      "id": "12345",
      "handle": "username",
      "name": "Display Name",
      "description": "Bio text...",
      "followersCount": 1000,
      "followingCount": 500,
      "verified": true,
      "profileImageUrl": "https://pbs.twimg.com/...",
      "createdAt": "Thu Jan 01 00:00:00 +0000 2020",
      "location": "Austin, TX",
      "url": "https://example.com"
    }
  ]
}
```

## Troubleshooting

**"Cannot connect to browser"**
- Ensure Chrome is running with `--remote-debugging-port=9222`
- Close ALL Chrome windows before starting with debug flag
- Check firewall isn't blocking localhost:9222
- Verify with: `curl http://localhost:9222/json/version`

**"Not logged into X"**
- Open x.com in the debug browser and log in
- Refresh the page to ensure session is active

**"List not found"**
- Verify the list ID is correct
- Check if you have access (private lists need ownership)
- Run `--discover` to see available lists

## How It Works

1. Connects to your browser via Chrome DevTools Protocol (CDP)
2. Extracts auth cookies from your logged-in X session
3. Calls X's internal GraphQL API for list data
4. Handles pagination automatically
5. Outputs clean JSON with full member metadata
