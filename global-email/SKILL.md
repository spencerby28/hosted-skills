---
name: global-email
description: |
  Walk a user through setting up a local multi-account email bridge for AI assistants,
  with Gmail OAuth, iCloud Mail IMAP/SMTP, cross-account search/read, draft creation,
  and explicit-confirmation sending. Use when the user wants "all my emails" across
  multiple inboxes, wants Codex or Claude to access more than one Gmail account, or
  needs a portable setup for friends without sharing OAuth clients, tokens, or passwords.
---

# Global Email Bridge

This skill helps an AI assistant walk a user through a local "all my email accounts" setup.
It is intentionally local-first: credentials stay on the user's machine, the assistant reads
through a small Python CLI, and outbound email is only sent after explicit user confirmation.

## What This Provides

- Search and read across multiple Gmail accounts and iCloud Mail.
- Create Gmail or iCloud drafts.
- Send through Gmail API or iCloud SMTP after the user confirms recipients, subject, and body.
- A repeatable Google OAuth setup path each user can own for themselves.
- A bridge that other agents can call with simple JSON output.

## Files

Download the toolkit ZIP or fetch individual files from:

| File | Purpose |
|---|---|
| [`global-email-toolkit.zip`](https://skills.sb28.ai/global-email/global-email-toolkit.zip) | Prepackaged bridge files |
| [`global-email`](https://skills.sb28.ai/global-email/global-email) | Short launcher so users can run `global-email search ...` |
| [`mail_bridge.py`](https://skills.sb28.ai/global-email/mail_bridge.py) | Local CLI for Gmail/iCloud search, read, drafts, and send |
| [`requirements.txt`](https://skills.sb28.ai/global-email/requirements.txt) | Python Gmail API dependencies |
| [`accounts.example.json`](https://skills.sb28.ai/global-email/accounts.example.json) | Safe starter config with no secrets |

## Safety Rules For The Assistant

- Never ask the user to paste OAuth tokens, client secrets, app-specific passwords, or raw credential files into chat.
- Never print token JSON, app-specific passwords, or credential command output.
- Do not reuse someone else's Google OAuth client for friends. Each user should create their own Google Cloud project and Desktop OAuth client.
- Treat email as read-first. Create drafts only when asked. Send mail only after the user explicitly confirms the exact recipients, subject, and body.
- If a command returns email snippets, summarize only what is needed for the task.

## Setup Overview

The user needs:

- `uv` installed.
- Python 3.11 or newer. Python 3.13 works.
- A Google Cloud project for Gmail OAuth.
- An iCloud app-specific password if they want iCloud Mail.

Use this local directory:

```bash
mkdir -p ~/.codex/global-email/tokens
```

Download and unpack the toolkit:

```bash
cd ~/.codex/global-email
curl -L -o global-email-toolkit.zip https://skills.sb28.ai/global-email/global-email-toolkit.zip
python3 -m zipfile -e global-email-toolkit.zip .
chmod +x ~/.codex/global-email/global-email
mkdir -p ~/.local/bin
ln -sf ~/.codex/global-email/global-email ~/.local/bin/global-email
```

If `~/.local/bin` is not on `PATH`, add it to the shell profile or use `~/.local/bin/global-email ...`.

Create the `uv` virtual environment:

```bash
uv venv --python 3.13 ~/.codex/global-email/.venv
uv pip install --python ~/.codex/global-email/.venv/bin/python -r ~/.codex/global-email/requirements.txt
```

If Python 3.13 is not available, use the user's installed Python:

```bash
uv venv ~/.codex/global-email/.venv
uv pip install --python ~/.codex/global-email/.venv/bin/python -r ~/.codex/global-email/requirements.txt
```

Create the starting config:

```bash
cp ~/.codex/global-email/accounts.example.json ~/.codex/global-email/accounts.json
chmod 600 ~/.codex/global-email/accounts.json
```

## Google OAuth Setup

Each user should create their own Google OAuth Desktop client.

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Create or select a project.
3. Go to **APIs & Services > Library**.
4. Search for **Gmail API** and enable it.
5. Go to **Google Auth Platform > Overview**.
6. If the project is not configured, click **Get started**.
7. Fill the app name, support email, and developer contact email.
8. Choose **External** unless every user is inside the same Google Workspace organization.
9. On the final step, agree to the Google API Services User Data Policy and create the OAuth configuration.
10. Go to **Audience**. While publishing status is **Testing**, add every Gmail address that will run OAuth as a test user.
11. Go to **Clients > Create client**.
12. Choose **Desktop app**, name it, and create it.
13. Download the JSON and save it as:

```text
~/.codex/global-email/google-oauth-client.json
```

Lock it down:

```bash
chmod 600 ~/.codex/global-email/google-oauth-client.json
```

Create one token per Gmail account:

```bash
global-email setup-gmail \
  --client-secret ~/.codex/global-email/google-oauth-client.json \
  --token-path ~/.codex/global-email/tokens/gmail-primary.json \
  --scope-set compose

global-email setup-gmail \
  --client-secret ~/.codex/global-email/google-oauth-client.json \
  --token-path ~/.codex/global-email/tokens/gmail-secondary.json \
  --scope-set compose
```

Choose the intended Google account in each browser OAuth flow.

Scope guidance:

- `readonly`: search and read only.
- `compose`: search/read plus draft and send access. This is the practical default for assistant workflows.
- `modify`: broader Gmail modify scope for label/archive/message mutation. Avoid unless needed.

## iCloud Mail Setup

iCloud uses IMAP for read/drafts and SMTP for send. The user needs an Apple app-specific password.

1. Open Apple Account settings.
2. Go to **Sign-In and Security > App-Specific Passwords**.
3. Generate a password for this bridge.
4. Store it locally. Do not paste it into chat.

Portable WSL/Linux setup:

```bash
export ICLOUD_APP_PASSWORD='app-specific-password'
```

For a persistent shell, add that export to the user's private shell profile or use their preferred secret manager.

macOS Keychain setup:

```bash
security add-generic-password \
  -a primary-icloud-mail-address@icloud.com \
  -s global-email-icloud \
  -w 'app-specific-password'
```

Then use this config field instead of `password_env`:

```json
"password_command": "security find-generic-password -a primary-icloud-mail-address@icloud.com -s global-email-icloud -w"
```

iCloud settings:

- IMAP host: `imap.mail.me.com`
- IMAP port: `993`
- SMTP host: `smtp.mail.me.com`
- SMTP port: `587`
- SMTP security: STARTTLS
- Password: Apple app-specific password

For custom-domain iCloud addresses, the visible sender address may not be the login username. If authentication fails, try the primary iCloud Mail address or username shown in Apple Mail/iCloud settings, then keep the custom-domain address in the `email` or `--from` field.

## Account Config

Edit:

```text
~/.codex/global-email/accounts.json
```

Use `accounts.example.json` as the shape. For each Gmail account, set:

- `email`
- `client_secret_path`
- `token_path`

For iCloud, set:

- `email`: the visible mailbox or sender address
- `username`: the iCloud IMAP login username
- `smtp_username`: the SMTP login username, usually the primary iCloud Mail address
- `password_env` or `password_command`

## Validate Setup

Run:

```bash
global-email accounts
```

Every account should show `ready: true`.

Search the last day:

```bash
global-email search --days 1 --limit 10
```

Search one account:

```bash
global-email search \
  --account gmail-primary \
  --query "from:example.com" \
  --days 30 \
  --limit 10
```

Read one message using the `message_id` from search:

```bash
global-email read \
  --account gmail-primary \
  --message-id MESSAGE_ID
```

## Draft And Send

Create a draft:

```bash
global-email create-draft \
  --account gmail-primary \
  --to recipient@example.com \
  --subject "Subject" \
  --body "Draft body"
```

Send only after explicit confirmation:

```bash
global-email send \
  --account icloud \
  --to recipient@example.com \
  --subject "Subject" \
  --body "Body"
```

Before sending, restate:

- From account
- To/Cc/Bcc
- Subject
- Body

Then wait for a clear instruction like "send it".

## Operating Pattern For Agents

When the user asks for email help:

1. Run `accounts` first.
2. If the request is broad, default to all accounts, last 7 days, limit 25.
3. Use Gmail query syntax for Gmail accounts, and simple text/sender/subject filters for iCloud IMAP.
4. Read bodies only for messages needed to answer the user's task.
5. Group results by account and urgency.
6. Mention account-level errors instead of hiding them.
7. Never expose credential paths beyond what is needed to explain setup.

## Troubleshooting

### Google says the app has not completed verification

The OAuth app is in Testing mode and the signed-in Gmail address is not a test user. Add the exact Gmail address under **Google Auth Platform > Audience > Test users**, then rerun `setup-gmail`.

### Wrong Gmail account got connected

Delete that account's token file and rerun `setup-gmail`. Choose the correct account in the OAuth browser flow.

### Browser flow cannot open from SSH or WSL

Run `setup-gmail` in a terminal that can open a local browser. If needed, copy the printed OAuth URL into a browser on the same machine so the localhost callback can reach the running Python process.

### iCloud IMAP authentication fails

Check that the password is an app-specific password, not the Apple Account password. If the mailbox uses a custom domain, try the primary iCloud Mail username for `username` and keep the custom-domain address as the visible `email`.

### iCloud SMTP send fails

Use `smtp.mail.me.com` on port `587` with STARTTLS. Set `smtp_username` to the primary iCloud Mail address. Some aliases may require `--from` to match an address Apple allows for the account.

### The assistant can read but cannot draft or send Gmail

The token may have been created with `readonly`. Rerun `setup-gmail` with `--scope-set compose` and update that account's token.

## Extending To Other Providers

This bridge already supports generic IMAP read/search and SMTP send through the `imap` provider fields. For Fastmail, Proton Mail Bridge, Outlook IMAP, or other providers, add the provider's IMAP/SMTP host, ports, username, and password helper to `accounts.json`. Prefer provider-specific OAuth only when IMAP/SMTP is unavailable or insufficient.
