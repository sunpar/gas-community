# gas-community

`gas-community` is a local Git agent scheduler for Codex CLI. It turns markdown files
into queued coding jobs, runs each job in an isolated Git worktree, and serializes
merge-back into the branch that was current when the task was claimed.

The core loop is:

1. Drop a markdown task into `.codex-queue/inbox/`.
2. A worker matching the filename difficulty atomically claims the task.
3. The worker creates a task branch and sibling worktree from the current branch HEAD.
4. `codex exec` runs inside the isolated worktree.
5. The wrapper commits successful worktree changes.
6. A merge lock serializes merge-back into the original branch.
7. The task markdown moves to `done/` or `failed/` with a result report appended.

## Requirements

- Python 3.11+
- Git
- GitHub CLI only if you want to publish your own fork
- Codex CLI available on `PATH`
- Codex profiles named `agent-high`, `agent-medium`, and `agent-low`

## Install

Run the installer with the Git repository where you want to run queued Codex
jobs:

```bash
./scripts/install_codex_queue.sh /path/to/target/repo
```

The installer copies the queue runner scripts into `scripts/`, copies the Codex
profile snippet into `config/codex-profiles.toml`, and ensures queue state is
ignored by the target repo's `.gitignore`:

```gitignore
.codex-queue/
```

Add the installed Codex profiles to `~/.codex/config.toml`:

```toml
[profiles.agent-high]
model = "gpt-5.5"
model_reasoning_effort = "xhigh"
approval_policy = "never"
sandbox_mode = "workspace-write"
web_search = "cached"

[profiles.agent-medium]
model = "gpt-5.5"
model_reasoning_effort = "medium"
approval_policy = "never"
sandbox_mode = "workspace-write"
web_search = "cached"

[profiles.agent-low]
model = "gpt-5.5"
model_reasoning_effort = "low"
approval_policy = "never"
sandbox_mode = "workspace-write"
web_search = "cached"
```

## Usage

Start one worker per difficulty:

```bash
./scripts/start_codex_workers.sh
```

Start more workers for specific levels:

```bash
AGENTS_HIGH=2 AGENTS_MEDIUM=2 AGENTS_LOW=1 ./scripts/start_codex_workers.sh
```

Queue a task:

```bash
./scripts/add_codex_task.sh high add-retry-logic <<'EOF'
Implement exponential backoff for the market data ingestion client.
Requirements:
- Retry transient HTTP 429/500/502/503/504 errors.
- Do not retry validation failures.
- Add tests.
EOF
```

The helper publishes tasks atomically as:

```text
.codex-queue/inbox/high__add-retry-logic.md
```

## Filename Routing

Workers route tasks by filename token:

```text
high__rewrite-auth-cache.md
medium__fix-csv-export.md
low__remove-unused-helper.md
```

Token matching means `high__task.md`, `task-high.md`, and `task.high.md` match
the high worker, but `highlight-bug.md` does not. Use
`--match-mode contains` for literal substring matching.

## Worktrees

By default, task worktrees are created outside the target repository:

```text
../.<repo-name>-codex-worktrees/<task-id>/
```

Do not place task worktrees inside the main repository worktree.

## Failure Behavior

- Codex failure moves the task to `.codex-queue/failed/<level>/`.
- Merge conflicts are aborted and marked failed.
- Failed task branches and worktrees are retained for inspection.
- Successful task worktrees are removed when `--cleanup-worktree-on-success` is used.
- Branch deletion is opt-in with `--delete-branch-on-success`.

## Security Notes

Anyone who can write to `.codex-queue/inbox/` can instruct a local code-running
agent. Treat queued markdown files as privileged input.

Keep sandboxing enabled for unattended runs:

```bash
--sandbox workspace-write
```

Keep `approval_policy = "never"` in the installed Codex profiles so unattended
workers do not pause for prompts.

The wrapper owns Git commits and merges. Codex is explicitly instructed not to
commit, merge, push, delete branches, remove worktrees, or edit queue files.
