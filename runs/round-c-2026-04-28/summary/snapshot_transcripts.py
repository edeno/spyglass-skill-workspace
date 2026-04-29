"""Snapshot subagent transcripts from a live Claude Code session into the workspace.

The Claude Code harness writes one JSONL transcript per dispatched subagent into
a session-scoped temp directory:

    /private/tmp/claude-501/<workspace-hash>/<session-uuid>/tasks/<agent-id>.output

That directory is wiped on session change or reboot — it's not durable. To make
the reference-utilization plot reproducible after the session ends, we snapshot
the transcripts for every agent_id we recorded in any iteration's
.agent_map.json into transcripts_snapshot/<agent-id>.jsonl.

Run this ONCE at the end of an eval sweep, before the session is closed:

    python <workspace-repo>/runs/<run-id>/summary/snapshot_transcripts.py

If --tasks-dir is omitted, the script finds the live session's tasks dir via
the encoded-cwd convention. The encoded cwd is derived from --skill-root
(or SPYGLASS_SKILL env var, or sibling-clone default), since Claude Code
sessions are typically rooted at the spyglass-skill repo when dispatching
eval subagents.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path


_HERE = Path(__file__).resolve()
# RUN_DIR is the per-sweep directory (sibling of summary/ holding iteration-N/).
RUN_DIR = _HERE.parent.parent
SNAPSHOT_DIR = _HERE.parent / "transcripts_snapshot"


def find_skill_root(args_skill_root: Path | None) -> Path:
    """Locate the spyglass-skill repo root.

    Resolution order:
    1. --skill-root CLI arg (explicit override)
    2. SPYGLASS_SKILL environment variable
    3. Sibling-clone convention: ../spyglass-skill/ relative to the workspace repo
    4. Legacy in-tree layout: walk up from this script looking for
       skills/spyglass/SKILL.md (only resolves when this script lived under
       the spyglass-skill repo, before the workspace was extracted).
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

    # _HERE is .../summary/snapshot_transcripts.py; walk up four levels:
    # script -> summary -> run-dir -> runs/ -> workspace-repo.
    workspace_repo_root = _HERE.parent.parent.parent.parent
    sibling = workspace_repo_root.parent / "spyglass-skill"
    if (sibling.joinpath(*marker)).is_file():
        return sibling.resolve()

    for parent in [_HERE, *_HERE.parents]:
        if (parent.joinpath(*marker)).is_file():
            return parent

    raise SystemExit(
        "Could not locate spyglass-skill repo. Pass --skill-root <path>, "
        "set SPYGLASS_SKILL=<path>, or clone spyglass-skill as a sibling "
        f"of {workspace_repo_root}."
    )


def find_live_tasks_dir(needed_ids: set[str], skill_root: Path) -> Path | None:
    """Heuristically locate the session tasks directory that holds our agent IDs.

    The harness path encodes the session's cwd with `/` -> `-`. We assume
    Claude Code was rooted at the spyglass-skill repo when the eval subagents
    were dispatched, so we search under the encoded skill_root path. There
    may be several past sessions under one workspace; we pick the session
    whose tasks/ directory contains the largest fraction of our mapped
    agent IDs — that's almost always the eval-sweep session, even if it's
    not the newest.
    """
    encoded_cwd = "-" + str(skill_root).replace("/", "-").lstrip("-")
    base = Path(f"/private/tmp/claude-{os.getuid()}") / encoded_cwd
    if not base.exists():
        return None

    candidates: list[tuple[int, Path]] = []
    for session_dir in base.iterdir():
        tasks = session_dir / "tasks"
        if not tasks.is_dir():
            continue
        try:
            present = {p.stem for p in tasks.iterdir()}
        except OSError:
            continue
        overlap = len(present & needed_ids)
        if overlap > 0:
            candidates.append((overlap, tasks))

    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def collect_mapped_agent_ids() -> set[str]:
    """Read every iteration-N/.agent_map.json under the workspace, collect the keys."""
    ids: set[str] = set()
    for i in range(1, 8):
        m_path = RUN_DIR / f"iteration-{i}" / ".agent_map.json"
        if m_path.exists():
            ids.update(json.loads(m_path.read_text()).keys())
    return ids


def snapshot(tasks_dir: Path) -> None:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    mapped = collect_mapped_agent_ids()
    if not mapped:
        raise SystemExit(f"No agent IDs found in {RUN_DIR}/iteration-*/.agent_map.json")

    copied = skipped = 0
    for aid in mapped:
        src = tasks_dir / f"{aid}.output"
        if not src.exists():
            skipped += 1
            continue
        shutil.copy2(src, SNAPSHOT_DIR / f"{aid}.jsonl")
        copied += 1

    size_kb = sum(p.stat().st_size for p in SNAPSHOT_DIR.iterdir()) / 1024
    print(f"Snapshotted {copied} transcripts ({skipped} mapped IDs missing on disk)")
    print(f"Total snapshot size: {size_kb:.1f} KB at {SNAPSHOT_DIR}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tasks-dir",
        type=Path,
        default=None,
        help="Live session tasks/ directory. If omitted, auto-detected from /private/tmp/.",
    )
    parser.add_argument(
        "--skill-root",
        type=Path,
        default=None,
        help=(
            "Path to the spyglass-skill repo (used to derive the harness's "
            "encoded-cwd path when auto-detecting tasks/). Defaults to "
            "../spyglass-skill/ as a sibling of the workspace repo. Override "
            "via this flag or the SPYGLASS_SKILL environment variable."
        ),
    )
    args = parser.parse_args()

    skill_root = find_skill_root(args.skill_root)
    mapped = collect_mapped_agent_ids()
    if not mapped:
        raise SystemExit(f"No agent IDs found in {RUN_DIR}/iteration-*/.agent_map.json")

    tasks_dir = args.tasks_dir or find_live_tasks_dir(mapped, skill_root)
    if tasks_dir is None or not tasks_dir.exists():
        raise SystemExit(
            "Could not locate the eval-sweep session tasks directory. "
            "Pass --tasks-dir explicitly. Expected path shape: "
            "/private/tmp/claude-<uid>/<encoded-cwd>/<session-uuid>/tasks/"
        )
    print(f"Reading transcripts from: {tasks_dir}")
    snapshot(tasks_dir)


if __name__ == "__main__":
    main()
