# Operating Model

## Directory Layout

Inside the target Git repository:

```text
.codex-queue/
  inbox/
  processing/
    high/
    medium/
    low/
  done/
    high/
    medium/
    low/
  failed/
    high/
    medium/
    low/
  logs/
  locks/
```

Outside the target repository, by default:

```text
../.<repo-name>-codex-worktrees/
  <task-id>/
```

## Claiming

Workers claim tasks with an atomic rename from `inbox/` to
`processing/<level>/`. The rename is the task lock; there is no separate per-task
lock file.

Claimed filenames include a timestamp, difficulty, random suffix, and original
filename:

```text
20260501T184500Z-high-a1b2c3d4__high__some-task.md
```

## Git Ownership

Codex implements code changes only. The wrapper owns:

- branch creation
- worktree creation
- staging
- committing
- merge locking
- merge-back
- task archival

Successful task commits use this subject format:

```text
codex(<level>): <original-task-filename> [<task-id>]
```

Merge commits use this subject format:

```text
Merge codex/<level>/<task-id> for <original-task-filename> [<task-id>]
```

## Merge Lock

Merges are serialized per base branch with a lock directory:

```text
.codex-queue/locks/merge-<safe-base-branch>.lock/
```

The worker checks that the main repository is still on the original branch and
has no uncommitted changes before merging.

## Result Reports

Every completed task markdown file receives an appended result block containing:

- status
- task ID
- difficulty
- base branch and SHA
- task branch
- worktree path
- Codex logs
- commit SHA
- merge SHA
- final Codex message
- error text, if any

## Skill Sequence

The worker prompt explicitly asks Codex to invoke these skills after implementation:

- `$review-workspace-changes`
- `$update-docs`
- `$deslop`

Make those skills available through your Codex skill configuration before using
the queue.

