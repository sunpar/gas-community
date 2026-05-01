#!/usr/bin/env python3
"""Run one markdown task from the local Codex queue."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

LEVELS = ("high", "medium", "low")


class CommandError(RuntimeError):
    """Raised when a subprocess command fails."""

    def __init__(self, cmd: list[str], returncode: int, stdout: str, stderr: str) -> None:
        self.cmd = cmd
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(
            "Command failed: "
            + " ".join(cmd)
            + f"\nreturncode={returncode}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"
        )


@dataclass
class Claim:
    # pylint: disable=too-many-instance-attributes
    task_id: str
    level: str
    original_name: str
    claimed_path: str
    claimed_at: str
    worker_id: str
    hostname: str
    pid: int
    base_branch: str | None = None
    base_sha: str | None = None
    task_branch: str | None = None
    worktree_path: str | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def run_cmd(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    input_text: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and proc.returncode != 0:
        raise CommandError(cmd, proc.returncode, proc.stdout, proc.stderr)
    return proc


def git(repo: Path, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run_cmd(["git", "-C", str(repo), *args], check=check)


def git_stdout(repo: Path, args: list[str], *, check: bool = True) -> str:
    return git(repo, args, check=check).stdout.strip()


def ensure_queue_dirs(queue_root: Path) -> None:
    for rel in [
        "inbox",
        "processing/high",
        "processing/medium",
        "processing/low",
        "done/high",
        "done/medium",
        "done/low",
        "failed/high",
        "failed/medium",
        "failed/low",
        "logs",
        "locks",
    ]:
        (queue_root / rel).mkdir(parents=True, exist_ok=True)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def difficulty_from_filename(filename: str, match_mode: str) -> tuple[str | None, list[str]]:
    name = filename.lower()
    hits: list[str] = []
    for level in LEVELS:
        if match_mode == "contains":
            matched = level in name
        else:
            matched = re.search(rf"(^|[^a-z0-9]){level}([^a-z0-9]|$)", name) is not None
        if matched:
            hits.append(level)
    if len(hits) == 1:
        return hits[0], hits
    return None, hits


def claim_metadata_path(claimed_path: Path) -> Path:
    return claimed_path.with_name(claimed_path.name + ".claim.json")


def claim_next_task(
    queue_root: Path,
    level: str,
    worker_id: str,
    match_mode: str,
) -> Claim | None:
    inbox = queue_root / "inbox"
    processing = queue_root / "processing" / level
    for candidate in sorted(inbox.glob("*.md")):
        detected, _hits = difficulty_from_filename(candidate.name, match_mode)
        if detected != level:
            continue
        task_id = f"{utc_stamp()}-{level}-{uuid.uuid4().hex[:8]}"
        claimed_path = processing / f"{task_id}__{candidate.name}"
        try:
            os.rename(candidate, claimed_path)
        except (FileNotFoundError, OSError):
            continue
        claim = Claim(
            task_id=task_id,
            level=level,
            original_name=candidate.name,
            claimed_path=str(claimed_path),
            claimed_at=utc_now(),
            worker_id=worker_id,
            hostname=socket.gethostname(),
            pid=os.getpid(),
        )
        write_json(claim_metadata_path(claimed_path), asdict(claim))
        return claim
    return None


def update_claim_metadata(claim: Claim) -> None:
    write_json(claim_metadata_path(Path(claim.claimed_path)), asdict(claim))


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-") or "unnamed"


@contextmanager
def directory_lock(
    lock_dir: Path,
    *,
    timeout_seconds: float,
    poll_seconds: float = 1.0,
) -> Iterator[None]:
    start = time.monotonic()
    lock_dir.parent.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            os.mkdir(lock_dir)
            (lock_dir / "owner.json").write_text(
                json.dumps(
                    {
                        "created_at": utc_now(),
                        "hostname": socket.gethostname(),
                        "pid": os.getpid(),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            break
        except FileExistsError as exc:
            elapsed = time.monotonic() - start
            if 0 <= timeout_seconds < elapsed:
                raise TimeoutError(f"Timed out waiting for lock: {lock_dir}") from exc
            time.sleep(poll_seconds)
    try:
        yield
    finally:
        shutil.rmtree(lock_dir, ignore_errors=True)


def current_branch(repo_root: Path) -> str:
    proc = git(repo_root, ["symbolic-ref", "--quiet", "--short", "HEAD"], check=False)
    branch = proc.stdout.strip()
    if proc.returncode != 0 or not branch:
        raise RuntimeError(
            f"Repository is in detached HEAD state or has no current branch: {repo_root}"
        )
    return branch


def create_task_worktree(repo_root: Path, worktree_root: Path, claim: Claim) -> tuple[Path, str]:
    base_branch = current_branch(repo_root)
    base_sha = git_stdout(repo_root, ["rev-parse", "HEAD"])
    branch = f"codex/{claim.level}/{claim.task_id}"
    worktree_path = worktree_root / claim.task_id
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    git(repo_root, ["worktree", "add", "-b", branch, str(worktree_path), base_sha])
    claim.base_branch = base_branch
    claim.base_sha = base_sha
    claim.task_branch = branch
    claim.worktree_path = str(worktree_path)
    update_claim_metadata(claim)
    return worktree_path, branch


def build_codex_prompt(task_text: str, claim: Claim) -> str:
    return f"""
You are the {claim.level.upper()} Codex queue worker for this repository.
Task metadata:
- task_id: {claim.task_id}
- difficulty: {claim.level}
- original_filename: {claim.original_name}
- base_branch: {claim.base_branch}
- base_sha: {claim.base_sha}
- task_branch: {claim.task_branch}
Execute the markdown task below.
Required workflow, in order:
1. Inspect the repository and understand the relevant code before editing.
2. Implement the requested changes.
3. Run relevant tests, build checks, type checks, or linters for the changed area.
4. Explicitly invoke and follow $review-workspace-changes.
5. Explicitly invoke and follow $update-docs.
6. Explicitly invoke and follow $deslop.
7. Do not commit, merge, push, delete branches, remove worktrees, or edit queue files.
   The external queue worker will handle Git commit and merge.
8. End with a concise completion report containing:
   - summary
   - changed files
   - tests/checks run
   - review findings addressed
   - documentation updates
   - remaining risks or follow-ups
Markdown task:
---
{task_text}
---
""".strip()


def run_codex(
    worktree_path: Path,
    queue_root: Path,
    claim: Claim,
    prompt: str,
) -> dict[str, str | int]:
    logs_dir = queue_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = logs_dir / f"{claim.task_id}.prompt.md"
    jsonl_log = logs_dir / f"{claim.task_id}.jsonl"
    stderr_log = logs_dir / f"{claim.task_id}.stderr.log"
    final_message = logs_dir / f"{claim.task_id}.final.md"
    prompt_path.write_text(prompt, encoding="utf-8")
    cmd = [
        "codex",
        "exec",
        "--cd",
        str(worktree_path),
        "--profile",
        f"agent-{claim.level}",
        "--sandbox",
        "workspace-write",
        "--ask-for-approval",
        "never",
        "--json",
        "--output-last-message",
        str(final_message),
        "-",
    ]
    with (
        jsonl_log.open("w", encoding="utf-8") as out,
        stderr_log.open(
            "w",
            encoding="utf-8",
        ) as err,
    ):
        proc = subprocess.run(
            cmd,
            input=prompt,
            text=True,
            stdout=out,
            stderr=err,
            check=False,
        )
    return {
        "returncode": proc.returncode,
        "prompt_path": str(prompt_path),
        "jsonl_log": str(jsonl_log),
        "stderr_log": str(stderr_log),
        "final_message": str(final_message),
    }


def has_worktree_changes(worktree_path: Path) -> bool:
    return bool(git_stdout(worktree_path, ["status", "--porcelain=v1"]))


def commit_worktree_changes(worktree_path: Path, claim: Claim) -> str | None:
    if not has_worktree_changes(worktree_path):
        return None
    git(worktree_path, ["add", "-A"])
    diff_proc = git(worktree_path, ["diff", "--cached", "--quiet"], check=False)
    if diff_proc.returncode == 0:
        return None
    if diff_proc.returncode != 1:
        raise CommandError(
            ["git", "diff", "--cached", "--quiet"],
            diff_proc.returncode,
            diff_proc.stdout,
            diff_proc.stderr,
        )
    subject = f"codex({claim.level}): {claim.original_name} [{claim.task_id}]"
    git(
        worktree_path,
        [
            "-c",
            "user.name=Codex Queue",
            "-c",
            "user.email=codex-queue@example.local",
            "commit",
            "-m",
            subject,
        ],
    )
    return git_stdout(worktree_path, ["rev-parse", "HEAD"])


def wait_for_clean_repo(repo_root: Path, wait_seconds: float) -> None:
    deadline = time.monotonic() + wait_seconds
    while True:
        status = git_stdout(repo_root, ["status", "--porcelain=v1"])
        if not status:
            return
        if wait_seconds <= 0 or time.monotonic() > deadline:
            raise RuntimeError(
                "Base repository is not clean, so automatic merge is unsafe. "
                "Commit/stash/remove these changes and merge the task branch manually.\n\n" + status
            )
        time.sleep(2.0)


def merge_task_branch(
    repo_root: Path,
    queue_root: Path,
    claim: Claim,
    merge_wait_seconds: float,
) -> str:
    if not claim.task_branch or not claim.base_branch:
        raise RuntimeError("Cannot merge because claim is missing task_branch or base_branch")
    lock_name = f"merge-{safe_name(claim.base_branch)}.lock"
    lock_dir = queue_root / "locks" / lock_name
    with directory_lock(lock_dir, timeout_seconds=merge_wait_seconds):
        current = current_branch(repo_root)
        if current != claim.base_branch:
            raise RuntimeError(
                f"Base repository is currently on branch {current!r}, but task was branched from "
                f"{claim.base_branch!r}. Switch back to {claim.base_branch!r} and merge manually."
            )
        wait_for_clean_repo(repo_root, merge_wait_seconds)
        merge_message = f"Merge {claim.task_branch} for {claim.original_name} [{claim.task_id}]"
        proc = git(
            repo_root,
            ["merge", "--no-ff", claim.task_branch, "-m", merge_message],
            check=False,
        )
        if proc.returncode != 0:
            git(repo_root, ["merge", "--abort"], check=False)
            raise RuntimeError(
                "Automatic merge failed and was aborted. Resolve manually from "
                "the retained task branch/worktree.\n\n"
                f"STDOUT:\n{proc.stdout}\n\nSTDERR:\n{proc.stderr}"
            )
        return git_stdout(repo_root, ["rev-parse", "HEAD"])


def dynamic_fence(text: str) -> str:
    fence = "```"
    while fence in text:
        fence += "`"
    return f"{fence}\n{text}\n{fence}"


def append_task_result(
    claim: Claim,
    *,
    status: str,
    codex_info: dict[str, str | int],
    commit_sha: str | None,
    merge_sha: str | None,
    error: str | None,
) -> None:
    # pylint: disable=too-many-arguments
    claimed_file = Path(claim.claimed_path)
    final_message_path = (
        Path(str(codex_info.get("final_message", ""))) if codex_info.get("final_message") else None
    )
    final_text = ""
    if final_message_path and final_message_path.exists():
        final_text = final_message_path.read_text(encoding="utf-8", errors="replace").strip()
    worktree_status = ""
    worktree_diff_stat = ""
    if claim.worktree_path and Path(claim.worktree_path).exists():
        wt = Path(claim.worktree_path)
        worktree_status = git_stdout(wt, ["status", "--porcelain=v1"], check=False)
        worktree_diff_stat = git_stdout(wt, ["diff", "--stat"], check=False)
    payload = {
        "status": status,
        "finished_at": utc_now(),
        "task_id": claim.task_id,
        "difficulty": claim.level,
        "original_filename": claim.original_name,
        "worker_id": claim.worker_id,
        "hostname": claim.hostname,
        "pid": claim.pid,
        "base_branch": claim.base_branch,
        "base_sha": claim.base_sha,
        "task_branch": claim.task_branch,
        "worktree_path": claim.worktree_path,
        "codex": codex_info,
        "commit_sha": commit_sha,
        "merge_sha": merge_sha,
        "error": error,
    }
    block = f"""
<!-- codex-task-result
{json.dumps(payload, indent=2, sort_keys=True)}
-->
## Codex task result
**Status:** `{status}`
**Task ID:** `{claim.task_id}`
**Difficulty:** `{claim.level}`
**Base branch:** `{claim.base_branch or ""}`
**Task branch:** `{claim.task_branch or ""}`
**Worktree:** `{claim.worktree_path or ""}`
**Commit SHA:** `{commit_sha or ""}`
**Merge SHA:** `{merge_sha or ""}`
**Codex return code:** `{codex_info.get("returncode", "")}`
### Worktree status
{dynamic_fence(worktree_status or "(clean or unavailable)")}
### Worktree diff stat
{dynamic_fence(worktree_diff_stat or "(no uncommitted diff or unavailable)")}
### Codex final message
{dynamic_fence(final_text or "(no final message captured)")}
"""
    if error:
        block += f"\n### Error\n\n{dynamic_fence(error)}\n"
    claimed_file.write_text(read_text(claimed_file) + block, encoding="utf-8")


def move_task_file(queue_root: Path, claim: Claim, terminal_status: str) -> Path:
    claimed = Path(claim.claimed_path)
    dest_dir = queue_root / terminal_status / claim.level
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / claimed.name
    os.rename(claimed, dest)
    meta = claim_metadata_path(claimed)
    if meta.exists():
        os.rename(meta, dest.with_name(dest.name + ".claim.json"))
    return dest


def cleanup_success(repo_root: Path, claim: Claim, *, delete_branch: bool) -> None:
    if claim.worktree_path and Path(claim.worktree_path).exists():
        git(repo_root, ["worktree", "remove", "--force", claim.worktree_path], check=False)
    if delete_branch and claim.task_branch:
        git(repo_root, ["branch", "-d", claim.task_branch], check=False)


def spawn_replacement() -> None:
    cmd = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]]
    subprocess.Popen(  # pylint: disable=consider-using-with
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Watch a markdown task queue and run one Codex task."
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--queue-root", type=Path, default=None)
    parser.add_argument("--worktree-root", type=Path, default=None)
    parser.add_argument("--level", required=True, choices=LEVELS)
    parser.add_argument("--poll-seconds", type=float, default=3.0)
    parser.add_argument("--match-mode", choices=("token", "contains"), default="token")
    parser.add_argument("--merge-wait-seconds", type=float, default=300.0)
    parser.add_argument("--respawn", action="store_true")
    parser.add_argument("--cleanup-worktree-on-success", action="store_true")
    parser.add_argument("--delete-branch-on-success", action="store_true")
    return parser.parse_args()


def main() -> int:
    # pylint: disable=too-many-locals
    args = parse_args()
    repo_root = args.repo_root.resolve()
    queue_root = (args.queue_root or (repo_root / ".codex-queue")).resolve()
    worktree_root = (
        args.worktree_root.resolve()
        if args.worktree_root
        else (repo_root.parent / f".{repo_root.name}-codex-worktrees").resolve()
    )
    if shutil.which("codex") is None:
        raise RuntimeError("codex executable not found on PATH")
    git(repo_root, ["rev-parse", "--show-toplevel"])
    ensure_queue_dirs(queue_root)
    worktree_root.mkdir(parents=True, exist_ok=True)
    worker_id = f"{args.level}-{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    claim: Claim | None = None
    while claim is None:
        claim = claim_next_task(queue_root, args.level, worker_id, args.match_mode)
        if claim is None:
            time.sleep(args.poll_seconds)
    codex_info: dict[str, str | int] = {}
    commit_sha: str | None = None
    merge_sha: str | None = None
    error: str | None = None
    terminal_status = "failed"
    try:
        worktree_path, _branch = create_task_worktree(repo_root, worktree_root, claim)
        task_text = read_text(Path(claim.claimed_path))
        prompt = build_codex_prompt(task_text, claim)
        codex_info = run_codex(worktree_path, queue_root, claim, prompt)
        if int(codex_info["returncode"]) != 0:
            raise RuntimeError(f"Codex returned non-zero exit code: {codex_info['returncode']}")
        commit_sha = commit_worktree_changes(worktree_path, claim)
        if commit_sha is not None:
            merge_sha = merge_task_branch(repo_root, queue_root, claim, args.merge_wait_seconds)
        terminal_status = "done"
    except Exception as exc:  # pylint: disable=broad-exception-caught
        error = str(exc)
        terminal_status = "failed"
    append_task_result(
        claim,
        status=terminal_status,
        codex_info=codex_info,
        commit_sha=commit_sha,
        merge_sha=merge_sha,
        error=error,
    )
    move_task_file(queue_root, claim, terminal_status)
    if terminal_status == "done" and args.cleanup_worktree_on_success:
        cleanup_success(repo_root, claim, delete_branch=args.delete_branch_on_success)
    if args.respawn:
        spawn_replacement()
    return 0 if terminal_status == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
