# Claude Code Worktree Workaround

**Skill page:** https://skills.sb28.ai/cc-worktree-workaround

Workaround for Claude Code worktree agents always branching from `main` instead of the current feature branch.

## Quick Fix

Prepend this to any worktree agent prompt:

```
BEFORE DOING ANYTHING ELSE:
1. Run `git merge origin/<current-branch> --no-edit`
2. Run `git branch -m worktree/<descriptive-name>`
```

## What's Covered

- Why worktrees default to main (no `branch` parameter in Agent tool)
- Why `git checkout` fails (branch already in use by main worktree)
- The merge workaround (fast-forward to feature branch HEAD)
- Smart branch naming (`worktree/<purpose>` convention)
- Full round-trip: merge in, commit, merge back

## Related Issues

- anthropics/claude-code#23622 — Feature request: support selecting base branch when creating git worktree
- anthropics/claude-code#27134 — Worktree always branches from origin/main
- anthropics/claude-code#32506 — Worktree creation should use selected branch instead of default branch
