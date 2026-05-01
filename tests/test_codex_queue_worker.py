from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "codex_queue_worker.py"
SPEC = importlib.util.spec_from_file_location("codex_queue_worker", MODULE_PATH)
assert SPEC is not None
worker = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = worker
SPEC.loader.exec_module(worker)


def test_difficulty_from_filename_uses_token_matching() -> None:
    assert worker.difficulty_from_filename("high__task.md", "token") == ("high", ["high"])
    assert worker.difficulty_from_filename("task-high.md", "token") == ("high", ["high"])
    assert worker.difficulty_from_filename("task.high.md", "token") == ("high", ["high"])
    assert worker.difficulty_from_filename("highlight-bug.md", "token") == (None, [])


def test_difficulty_from_filename_rejects_ambiguous_matches() -> None:
    assert worker.difficulty_from_filename("high-medium-task.md", "token") == (
        None,
        ["high", "medium"],
    )


def test_contains_match_mode_allows_literal_substrings() -> None:
    assert worker.difficulty_from_filename("highlight-bug.md", "contains") == ("high", ["high"])


def test_safe_name_normalizes_branch_names_for_lock_paths() -> None:
    assert worker.safe_name("feature/market data cleanup") == "feature-market-data-cleanup"


def test_dynamic_fence_expands_when_text_contains_backticks() -> None:
    fenced = worker.dynamic_fence("```")
    assert fenced.startswith("````\n")
    assert fenced.endswith("\n````")
