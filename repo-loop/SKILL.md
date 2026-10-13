---
name: repo-loop
description: Keep one durable task folder per agent thread so multi-step work survives interruptions, handoffs and context loss, and so delegated workers report back into the same place. Use when a task needs several steps, investigation, workers, or will span sessions. Skip one-shot questions and trivial edits.
---

# repo-loop (minimal)

One thread = one task folder. The folder holds the intent, decisions, progress and next step,
so this thread (or a later one) can pick up exactly where it left off. No install, no script:
just a folder convention and a small set of files.

## 1. Find or create the task folder

Task root: `~/agent-work/` (create if missing).

Thread id: use the harness's own session id. Never make one up.
- Claude Code: `$CLAUDE_CODE_SESSION_ID`
- Codex: `$CODEX_THREAD_ID`
- Otherwise: ask the user, or say no id is available and keep notes in the conversation.

Locate first, every time:

```bash
grep -l "<thread-id>" ~/agent-work/*/session.json 2>/dev/null
```

- **Found** → that is your folder. Read `SESSION.md` then `SCRATCHPAD.md` before doing anything.
- **Not found** → create `~/agent-work/<yyyy-mm-dd>-<short-task-slug>-<first 8 chars of id>/`
  containing the files below. Tell the user the folder path once.

Never pick a folder just because it is the most recent one.

## 2. The files

`session.json`
```json
{ "thread": "<harness>:<thread-id>", "role": "coordinator", "title": "<task>",
  "receiver": "/absolute/path/where/the/real/output/lives", "created": "<timestamp>",
  "workers": [] }
```

`SESSION.md` — the contract:
- **Goal** — what the user wants, in their words where it matters.
- **Receiver** — where the real output goes (a repo, a documents folder, a draft…). The task
  folder is for notes; finished work belongs in the receiver.
- **Decisions** — what was decided or corrected, by whom, and what it affects.
- **Done** — results with evidence (file paths, test output, links).
- **Open** — what remains, and any question waiting on the user.

`SCRATCHPAD.md` — the quick resume surface: exact paths, running processes, last result, next action.

Optional: `scratch/` for experiments and logs, `evidence/` for outputs worth keeping.

Keep notes short and current. No secrets.

## 3. Work

- Do the next useful step. Verify before claiming it is done.
- Update `SCRATCHPAD.md` when the next action or a key path changes.
- Update `SESSION.md` when a decision, correction or result lands. When the user corrects you,
  mark the old conclusion as superseded instead of deleting it.
- Ask the user only for taste, consequential choices, or anything outward-facing
  (sending, publishing, deleting, spending).

## 4. Workers (only if the harness and user allow subagents)

Give each worker in its brief:
1. the overall goal and its own bounded piece,
2. the exact receiver it may change (if any),
3. the absolute task folder path,
4. what proof to return.

The worker writes only inside `<task folder>/workers/<worker-name>/`, and returns one
`RETURN.md` there: what it found or changed, evidence, uncertainty, and what the coordinator
should do next. (Claude Code blocks subagents from writing files named REPORT*, SUMMARY*,
FINDINGS* or ANALYSIS*, so use RETURN.md.)

The coordinator records the worker in `session.json` → `workers`, reads its `RETURN.md`,
checks the evidence, and updates `SESSION.md`. A worker finishing does not finish the task.

## 5. Handoff and finish

- Before stopping after real work: refresh `SCRATCHPAD.md` (next action) and `SESSION.md` (open items).
- New thread taking over: add `"successor": "<harness>:<new-id>"` to `session.json`, then
  read the notes and continue. Only on an explicit handoff from the user or previous thread.
- Status lines in `SESSION.md`: active / waiting (on what) / paused / complete / cancelled.
  "Complete" means the goal is met with evidence at the receiver. Record only what actually
  happened (changed locally, committed, sent…).

## Install this skill

If you were pointed at this page and the skill is not installed yet, install it for the user:

```bash
mkdir -p ~/.claude/skills/repo-loop
curl -fsSL https://skills.sb28.ai/repo-loop/SKILL.md -o ~/.claude/skills/repo-loop/SKILL.md
curl -fsSL https://skills.sb28.ai/repo-loop/METASKILL.md -o ~/.claude/skills/repo-loop/METASKILL.md
```

For Codex use `~/.codex/skills/repo-loop` instead. New sessions pick it up automatically.
