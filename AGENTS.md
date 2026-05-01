# AGENTS.md

Keep this repository small, reviewable, and safe for local automation.

## Rules

- Keep changes focused on the Codex queue runner and its documentation.
- Do not add hosted services, background daemons, or package dependencies unless
  they are required for the local queue runner.
- Do not hardcode credentials, tokens, paths to private repositories, or personal
  machine details.
- Preserve sandboxed Codex execution by default.
- The wrapper script owns Git commits and merges; Codex workers should not.

## Validation

Run the checks that match your changes:

```bash
python3 -m py_compile scripts/codex_queue_worker.py
bash -n scripts/start_codex_workers.sh
bash -n scripts/add_codex_task.sh
python3 -m pytest
```

If Ruff is available:

```bash
ruff check .
ruff format --check .
```

