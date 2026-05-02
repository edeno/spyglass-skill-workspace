"""Atomic publish helper for staged → final output dirs and files.

Used by both single-run summary generation (summary.writers) and cross-run
comparison generation (compare_runs.py). The staging pattern stages
outputs to .data_tmp/ / .figures_tmp/ / .INDEX.tmp under the destination dir,
then renames them into place atomically — backing up any existing finals to
.previous and rolling those back on failure.
"""

from __future__ import annotations

import shutil
from pathlib import Path


def commit_staged_outputs(
    resources: list[tuple[Path, Path]],
) -> None:
    """Atomically rename each (staged, final) pair, with rollback on failure.

    All staged paths must exist before any rename happens. Existing finals are
    backed up to ``.<name>.previous`` first; if any rename fails after that
    point, both the staged→final renames and the final→.previous backups are
    reversed so the destination dir is left in its prior state.

    Caller owns ordering of the resources list. Files and directories are
    handled identically (Path.rename works for both).
    """
    missing = [str(staged) for staged, _ in resources if not staged.exists()]
    if missing:
        raise FileNotFoundError(f"missing staged outputs: {', '.join(missing)}")

    backups: list[tuple[Path, Path]] = []
    moved: list[tuple[Path, Path]] = []
    try:
        for _, final in resources:
            backup = _backup_path(final)
            _remove_path(backup)
            if final.exists():
                final.rename(backup)
                backups.append((backup, final))
        for staged, final in resources:
            staged.rename(final)
            moved.append((final, staged))
    except Exception:
        for final, staged in reversed(moved):
            if final.exists():
                final.rename(staged)
        for backup, final in reversed(backups):
            if backup.exists():
                backup.rename(final)
        raise
    else:
        for backup, _ in backups:
            _remove_path(backup)


def _backup_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.previous")


def _remove_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    else:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
