"""Shared helpers for the eval-sweep tools."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def find_skill_root(args_skill_root: Path | None) -> Path:
    """Locate the spyglass-skill repo root.

    Resolution order:
    1. --skill-root CLI arg (explicit override)
    2. SPYGLASS_SKILL environment variable
    3. Sibling-clone convention: ../spyglass-skill/ relative to the workspace repo
    """
    marker = ("skills", "spyglass", "SKILL.md")

    if args_skill_root:
        candidate = args_skill_root.expanduser().resolve()
        if (candidate.joinpath(*marker)).is_file():
            return candidate
        raise SystemExit(
            f"--skill-root {candidate} is not a spyglass-skill repo "
            f"(missing {'/'.join(marker)})"
        )

    env_path = os.environ.get("SPYGLASS_SKILL")
    if env_path:
        candidate = Path(env_path).expanduser().resolve()
        if (candidate.joinpath(*marker)).is_file():
            return candidate
        raise SystemExit(
            f"SPYGLASS_SKILL={env_path!r} is not a spyglass-skill repo "
            f"(missing {'/'.join(marker)})"
        )

    sibling = REPO_ROOT.parent / "spyglass-skill"
    if (sibling.joinpath(*marker)).is_file():
        return sibling.resolve()

    raise SystemExit(
        "Could not locate spyglass-skill repo. Pass --skill-root <path>, "
        "set SPYGLASS_SKILL=<path>, or clone spyglass-skill as a sibling "
        f"of {REPO_ROOT}."
    )


def discover_iterations(run_dir: Path) -> list[int]:
    """Return sorted list of batch IDs from `iteration-N/` subdirs under run_dir."""
    batches: list[int] = []
    for p in run_dir.glob("iteration-*"):
        if not p.is_dir():
            continue
        suffix = p.name.split("-", 1)[1]
        if suffix.isdigit():
            batches.append(int(suffix))
    return sorted(batches)
