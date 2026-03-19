# SB28 Skills

A collection of reusable skills hosted at [skills.sb28.ai](https://skills.sb28.ai). Each skill is a self-contained guide that AI assistants (Claude, etc.) can read and follow to help users accomplish tasks.

## How It Works

Tell Claude:

> Follow the guide at https://skills.sb28.ai/{skill-name}/SKILL.md

Claude reads the instructions and walks you through it step by step.

## Skills

| Skill | Description |
|-------|-------------|
| [chatgpt-export](https://skills.sb28.ai/chatgpt-export) | Export all ChatGPT conversations — even from Team/Business accounts where OpenAI disabled export |
| [prd-interview](https://skills.sb28.ai/prd-interview) | Claude interviews you to build a professional Product Requirements Document for your app idea |
| [arch-audit](https://skills.sb28.ai/arch-audit) | Deep structural audit of any codebase — find split-brain behavior, schema drift, ownership gaps, and misaligned boundaries |
| [x-lists](https://skills.sb28.ai/x-lists) | Export X/Twitter list members to JSON with full profile data and engagement metrics |
| [cf-starter](https://skills.sb28.ai/cf-starter) | Email/password auth on the edge with Cloudflare Workers and D1 SQLite |
| [pdf-reader](https://skills.sb28.ai/pdf-reader) | Extract content and visual styling from PDFs using Marker + Vision |
| [security-check](https://skills.sb28.ai/security-check) | Non-technical security audit for OpenClaw setups |

## Skill Structure

Each skill is a directory containing:

```
skill-name/
├── meta.json    # Name, title, tagline (used for OG images and listing)
├── SKILL.md     # The guide — instructions an AI assistant reads and follows
└── [files]      # Optional: scripts, configs, extensions, ZIPs
```

## Adding a Skill

1. Create a directory with `meta.json` and `SKILL.md`
2. Push to this repo
3. Add the skill name to the `SKILLS` array in the [worker](https://github.com/spencerby28/skills-site)
4. Deploy the worker

Files are served at `https://skills.sb28.ai/{skill-name}/{filename}`. Browser requests get an HTML-rendered page; CLI/LLM requests get raw markdown.
