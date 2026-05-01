from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = REPO_ROOT / "scripts" / "install_codex_queue.sh"


def test_installer_copies_runner_files_and_updates_gitignore(tmp_path: Path) -> None:
    target = tmp_path / "target-repo"
    target.mkdir()
    (target / ".gitignore").write_text("dist/\n.codex-queue/\n", encoding="utf-8")

    result = subprocess.run(
        ["bash", str(INSTALLER), str(target)],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    for rel in [
        "scripts/codex_queue_worker.py",
        "scripts/start_codex_workers.sh",
        "scripts/add_codex_task.sh",
        "scripts/install_codex_queue.sh",
        "config/codex-profiles.toml",
    ]:
        assert (target / rel).read_text(encoding="utf-8") == (REPO_ROOT / rel).read_text(
            encoding="utf-8"
        )

    assert (target / ".gitignore").read_text(encoding="utf-8") == "dist/\n.codex-queue/\n"
    assert os.access(target / "scripts/start_codex_workers.sh", os.X_OK)
    assert os.access(target / "scripts/add_codex_task.sh", os.X_OK)
    assert os.access(target / "scripts/install_codex_queue.sh", os.X_OK)
    assert os.access(target / "scripts/codex_queue_worker.py", os.X_OK)


def test_installer_creates_gitignore_when_missing(tmp_path: Path) -> None:
    target = tmp_path / "target-repo"
    target.mkdir()

    result = subprocess.run(
        ["bash", str(INSTALLER), str(target)],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    gitignore = target / ".gitignore"
    assert gitignore.read_text(encoding="utf-8") == ".codex-queue/\n"
    assert stat.S_IMODE((target / "config/codex-profiles.toml").stat().st_mode) & stat.S_IXUSR == 0


def test_installer_rejects_missing_target(tmp_path: Path) -> None:
    target = tmp_path / "missing"

    result = subprocess.run(
        ["bash", str(INSTALLER), str(target)],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 2
    assert "Target directory does not exist" in result.stderr
