---
name: cc-worktree-workaround
description: |
  Fix Claude Code worktree agents that start from main instead of the current feature branch.
  Use when: (1) worktree agent needs to work on code from the current branch, not main,
  (2) agent spawned with isolation:"worktree" is missing recent commits or has wrong code,
  (3) git checkout of current branch fails with "already used by worktree" error,
  (4) parallel worktree agents need feature branch code as their starting point.
---

# Claude Code Worktree Workaround

## The Problem

When you spawn a Claude Code agent with `isolation: "worktree"`, the worktree is always
created from **main's HEAD**, not from the current branch. If you're on a feature branch,
the agent works on stale code and is missing all your branch's changes.

There is no `branch` or `base_ref` parameter in the Agent tool to control this.

## Why `git checkout` Doesn't Work

The obvious fix — telling the agent to `git checkout <your-branch>` — fails:

```
fatal: 'feature/my-branch' is already used by worktree at '/path/to/repo'
```

Git enforces that a branch can only be checked out in **one worktree at a time**.
Since the main repo already has your branch checked out, the worktree agent cannot
check it out.

## How It Works

Use `git merge origin/<branch> --no-edit` in the agent prompt to fast-forward the
worktree to the current branch's HEAD.

### The Prompt Pattern

Prepend this to any worktree agent prompt:

```
BEFORE DOING ANYTHING ELSE: Run `git merge origin/<current-branch> --no-edit` to get the latest code.
```

### Full Agent Tool Call Example

```javascript
Agent({
  description: "Run tests on feature branch",
  prompt: `BEFORE DOING ANYTHING ELSE: Run \`git merge origin/feature/my-work --no-edit\` to get the latest code.\n\nThen: cd app && bun run test`,
  isolation: "worktree"
})
```

### If Branch Isn't Pushed to Remote

The `origin/<branch>` ref requires the branch to be pushed. If it hasn't been pushed yet,
use the commit SHA directly:

```
git merge abc123def --no-edit
```

## Merging Worktree Changes Back

After the agent completes and makes commits, merge its branch back into your current branch:

```bash
# From the main repo (on your feature branch):
git merge worktree-agent-<hash> --no-edit
```

This works because:
- The worktree branch (`worktree-agent-<hash>`) is visible from the main repo
- Since you merged your branch INTO the worktree first, merging back is a fast-forward
- The `worktreeBranch` name is returned in the agent result when changes are made

### Full Round-Trip

```
1. You're on `feature/my-work` at commit abc123
2. Spawn worktree agent with merge prompt -> agent is now at abc123
3. Agent makes changes, commits -> new commit def456 on `worktree-agent-xyz`
4. Agent completes, returns worktreeBranch: "worktree-agent-xyz"
5. In main repo: `git merge worktree-agent-xyz --no-edit` -> fast-forward to def456
```

## Test Results

All approaches were tested on 2026-03-19:

| Approach | Result |
|---|---|
| Default worktree (no intervention) | Branches from **main** HEAD |
| `git checkout <branch>` in prompt | **Fails** — branch already in use by main worktree |
| `git merge origin/<branch>` in prompt | **Works** — fast-forwards to current branch HEAD |
| Merge changes back to main repo | **Works** — fast-forward merge succeeds |

## Troubleshooting

**Agent says merge failed with conflicts**: Your branch has diverged significantly from main.
The merge will create a merge commit instead of fast-forwarding. This is fine for most worktree
work since the worktree is disposable.

**`origin/<branch>` ref not found**: Push your branch first with `git push -u origin <branch>`,
or use the commit SHA instead.

**Worktree not cleaned up**: If the agent made changes, the worktree persists at
`.claude/worktrees/agent-<hash>`. You can clean it up with `git worktree remove .claude/worktrees/agent-<hash>`.

## Notes

- This behavior may change in future Claude Code versions if a `branch` parameter is added
- The worktree branch name will be `worktree-agent-<hash>`, not your branch name
- For parallel worktree agents, each one needs the merge step independently
- If your branch has diverged from main (not a fast-forward), the merge creates a merge commit — this is fine for read-only or disposable worktree work
