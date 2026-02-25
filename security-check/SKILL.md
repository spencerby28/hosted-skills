---
name: security-check
description: OpenClaw security audit for everyone. Checks your setup, explains what it finds in plain language, and walks you through fixes. Use when someone asks to check their OpenClaw security, audit their setup, or wants help understanding security warnings.
---

# OpenClaw Security Check

Run a security audit and explain findings clearly. No jargon, no condescension.

## Philosophy

Non-technical ≠ stupid. Users don't need analogies about doors and locks. They need:
- Clear explanation of what something IS (one sentence)
- Whether it's a real problem or just a warning
- What to do about it, if anything

## Step 1: Run the Audit

Ask permission once, then run everything:

```bash
# System info
uname -a
cat /etc/os-release 2>/dev/null | head -5

# What's listening for connections
ss -ltnp 2>/dev/null || netstat -tlnp 2>/dev/null

# OpenClaw's own security check
openclaw security audit --deep

# OpenClaw version
openclaw update status

# Network setup (if using Tailscale)
tailscale status 2>&1
```

## Step 2: Categorize Findings

Sort everything into three buckets:

### 🔴 Fix This
Real security issues. Criteria:
- Something is exposed to the public internet that shouldn't be
- Authentication is disabled or weak on a public-facing service
- Known vulnerable software version

### 🟡 Worth Knowing
Not urgent, but good to understand:
- Services bound to all interfaces (but only reachable on private network)
- OpenClaw config warnings that affect functionality
- Outdated software with updates available

### ✅ You're Good
Things that are fine. Include these so users know you checked.

## Step 3: Present Findings

Use this format for each finding:

```
**[Finding Name]**
What it is: [One sentence explanation]
Risk: [Real risk in their specific situation]
Action: [What to do, or "None needed"]
```

Example (good):
```
**SSH allows password login**
What it is: Remote login accepts passwords, not just key files.
Risk: Low — only reachable from your private Tailscale network, not the internet.
Action: None needed unless you want extra security.
```

Example (bad — don't do this):
```
**Your front door accepts any key!**
Think of SSH like the front door to your house. Right now, anyone 
who guesses your password can walk right in! That's like having a 
lock that opens if someone tries enough keys...
```

## Step 4: Context Matters

Before calling something a problem, check:

1. **Is it actually exposed?** A service on `0.0.0.0` sounds bad, but if there's no route from the internet, it's fine.

2. **What's the network setup?** Tailscale-only? Behind NAT? Public VPS? This changes everything.

3. **What's their threat model?** Home user vs running a business vs handling sensitive data.

Ask if unclear:
- "Is this machine directly on the internet, or behind a home router / Tailscale?"
- "Do other people have access to your network?"

## Step 5: Offer Fixes

After presenting findings, offer options:

```
What would you like to do?

1. Fix the important stuff (I'll walk you through each step)
2. Just show me the commands (you run them later)
3. Leave it (explain why that's okay if it is)
```

For each fix:
- Show the exact command
- Explain what it does in one sentence
- Wait for approval before running
- Verify it worked after

## Common Findings Reference

### OpenClaw Warnings

| Warning | What it means | When to care |
|---------|--------------|--------------|
| `hooks.defaultSessionKey` unset | Webhook requests create random sessions | Only if using webhooks |
| `trustedProxies` missing | Reverse proxy headers ignored | Only if behind nginx/caddy |
| Weak model tier | Smaller models are easier to trick | If bot handles untrusted input |

### Network Exposure

| Binding | Meaning | Risk |
|---------|---------|------|
| `127.0.0.1:PORT` | Only this machine | None |
| `0.0.0.0:PORT` | All network interfaces | Depends on network |
| `TAILSCALE_IP:PORT` | Only your Tailscale network | Low (trusted devices) |

### SSH Settings

| Setting | Secure | Less Secure |
|---------|--------|-------------|
| PasswordAuthentication | no | yes |
| PermitRootLogin | no | yes |
| Port | non-standard | 22 |

## What NOT to Do

- Don't use analogies (doors, locks, filing cabinets)
- Don't explain TCP/IP basics
- Don't list 50 theoretical attacks
- Don't scare people about things that aren't real risks for them
- Don't assume Tailscale network = untrusted

## Example Output

```
## Security Check Results

### 🔴 Fix This
None found.

### 🟡 Worth Knowing

**OpenClaw update available**
What it is: Newer version (2026.2.24) is out.
Risk: None immediate, but updates include security fixes.
Action: Run `openclaw update` when convenient.

**Telegram responds to all group messages**
What it is: Bot replies even when not @mentioned.
Risk: Could get noisy or spammed in busy groups.
Action: Enable `requireMention` in config if this bothers you.

### ✅ You're Good

- OpenClaw dashboard only accessible from this machine ✓
- No services exposed to public internet ✓
- Tailscale not sharing anything publicly ✓
- SSH root login disabled ✓
```
