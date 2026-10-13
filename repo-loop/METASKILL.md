# repo-loop metaskill

How this skill is packaged and maintained. `SKILL.md` is the operating guide; this file is not.

## What it is

A single Markdown skill. No script, no runtime, no dependencies. The agent creates and reads the
task folders itself with ordinary file tools, so it works the same in Claude Code, Codex, or any
agent that can read files and run a shell.

## Install

Claude Code:
```bash
mkdir -p ~/.claude/skills/repo-loop
cp SKILL.md METASKILL.md ~/.claude/skills/repo-loop/
```

Codex (if used):
```bash
mkdir -p ~/.codex/skills/repo-loop
cp SKILL.md METASKILL.md ~/.codex/skills/repo-loop/
```

New sessions pick it up automatically. To make it the default way of working, add one line to the
personal instructions file (`~/.claude/CLAUDE.md` or `~/.codex/AGENTS.md`):

> For multi-step work, use the repo-loop skill and tell me the task folder path once.

## Layout it produces

```text
~/agent-work/
└── 2026-10-13-quarterly-report-6a251df5/
    ├── session.json        # thread id, role, receiver, workers
    ├── SESSION.md          # goal, decisions, done (with evidence), open
    ├── SCRATCHPAD.md       # resume here: paths, last result, next action
    ├── scratch/            # optional: experiments, logs
    ├── evidence/           # optional: outputs worth keeping
    └── workers/
        └── <worker-name>/RETURN.md
```

## Design rules (keep these when editing)

- Identity comes from the harness's own session id; never guessed, never borrowed.
- Locate before create; never choose a folder by recency.
- Notes live in the task folder; real output lives in the receiver.
- Workers write only in their own `workers/<name>/` folder; the coordinator integrates.
- Keep the skill short. If a rule needs a paragraph of justification, it probably belongs here,
  not in SKILL.md.

## Changing the root

`~/agent-work` is a convention. To use another location, edit the path in SKILL.md section 1 and
in this file; existing folders can simply be moved.

## Possible upgrades (not included)

- A small `repo-loop` CLI for locate/init/attach with locking, if several agents create folders at
  the same time and collisions become a problem.
- A history search tool (e.g. agent-analysis) for recalling past threads beyond the task folder.
