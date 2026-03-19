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

Additionally, the auto-generated branch names (`worktree-agent-<hash>`) are opaque and
impossible to distinguish when running multiple agents in parallel.

## Why `git checkout` Doesn't Work

The obvious fix — telling the agent to `git checkout <your-branch>` — fails:

```
fatal: 'feature/my-branch' is already used by worktree at '/path/to/repo'
```

Git enforces that a branch can only be checked out in **one worktree at a time**.
Since the main repo already has your branch checked out, the worktree agent cannot
check it out.

## How It Works

Use `git merge` + `git branch -m` in the agent prompt to both get the right code
AND give the branch a descriptive name.

### The Prompt Pattern

Prepend this to any worktree agent prompt:

```
BEFORE DOING ANYTHING ELSE:
1. Run `git merge origin/<current-branch> --no-edit` to get the latest code.
2. Run `git branch -m worktree/<descriptive-name>` to name this branch.
```

### Full Agent Tool Call Example

```javascript
Agent({
  description: "Run tests on feature branch",
  prompt: `BEFORE DOING ANYTHING ELSE:\n1. Run \`git merge origin/feature/my-work --no-edit\`\n2. Run \`git branch -m worktree/run-tests\`\n\nThen: cd app && bun run test`,
  isolation: "worktree"
})
```

### Smart Naming Conventions

Use `worktree/<purpose>` as the naming pattern:

| Agent Task | Branch Name |
|---|---|
| Running tests | `worktree/run-tests` |
| Refactoring auth module | `worktree/refactor-auth` |
| Fixing scope engine bug | `worktree/fix-scope-engine` |
| Parallel slice 3 of refactor | `worktree/slice-3-extract-types` |

For parallel agents, add distinguishing suffixes:

```
worktree/slice-1-schema
worktree/slice-2-routes
worktree/slice-3-components
```

### Important: The Return Value Lies

The `worktreeBranch` returned in the Agent tool result will still report the **old
auto-generated name** (`worktree-agent-<hash>`). Ignore it — use the name you specified
in the prompt.

### If Branch Isn't Pushed to Remote

The `origin/<branch>` ref requires the branch to be pushed. If it hasn't been pushed yet,
use the commit SHA directly:

```
git merge abc123def --no-edit
```

## Merging Worktree Changes Back

After the agent completes and makes commits, merge its branch back using the descriptive
name you chose:

```bash
# From the main repo (on your feature branch):
git merge worktree/run-tests --no-edit
```

Much cleaner than `git merge worktree-agent-a35d659b --no-edit`.

### Full Round-Trip

```
1. You're on `feature/my-work` at commit abc123
2. Spawn worktree agent with merge + rename prompt
3. Agent merges to abc123, renames branch to `worktree/fix-auth`
4. Agent makes changes, commits -> new commit def456 on `worktree/fix-auth`
5. In main repo: `git merge worktree/fix-auth --no-edit` -> fast-forward to def456
```

## Test Results

All approaches tested on 2026-03-19:

| Approach | Result |
|---|---|
| Default worktree (no intervention) | Branches from **main** HEAD |
| `git checkout <branch>` in prompt | **Fails** — branch already in use by main worktree |
| `git merge origin/<branch>` in prompt | **Works** — fast-forwards to current branch HEAD |
| `git branch -m worktree/<name>` after merge | **Works** — renamed, visible from main repo |
| Merge back using renamed branch | **Works** — fast-forward merge succeeds |

## Troubleshooting

**Agent says merge failed with conflicts**: Your branch has diverged significantly from main.
The merge will create a merge commit instead of fast-forwarding. This is fine for most worktree
work since the worktree is disposable.

**`origin/<branch>` ref not found**: Push your branch first with `git push -u origin <branch>`,
or use the commit SHA instead.

**Worktree not cleaned up**: If the agent made changes, the worktree persists at
`.claude/worktrees/agent-<hash>`. Be careful pruning — other agents may still be using them.
Clean up with `git worktree remove .claude/worktrees/agent-<hash>` only when you're sure
no agents are running.

**`worktreeBranch` shows old name**: Expected behavior. The return value always reports the
original auto-generated name. Use the name you specified in your prompt instead.

## Notes

- This behavior may change in future Claude Code versions if a `branch` parameter is added
- For parallel worktree agents, each one needs the merge + rename step independently
- If your branch has diverged from main (not a fast-forward), the merge creates a merge commit — this is fine for read-only or disposable worktree work
