"""Snapshot subagent transcripts from a live Claude Code session into a run.

The Claude Code harness writes one JSONL transcript per dispatched subagent
into a session-scoped temp directory:

    /private/tmp/claude-<uid>/<workspace-hash>/<session-uuid>/tasks/<agent-id>.output

That directory is wiped on session change or reboot — it's not durable. To
make the reference-utilization plot reproducible after the session ends, this
script copies each transcript referenced in any iteration-N/.agent_map.json
under the target run into `<run>/transcripts_snapshot/<agent-id>.jsonl`.

Run this ONCE at the end of an eval sweep, before the session is closed:

    python tools/snapshot_transcripts.py --run runs/<run-id>/

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

from common import discover_iterations, find_skill_root


def collect_mapped_agent_ids(run_dir: Path) -> set[str]:
    """Read every iteration-N/.agent_map.json under run_dir, collect the keys."""
    ids: set[str] = set()
    for i in discover_iterations(run_dir):
        m_path = run_dir / f"iteration-{i}" / ".agent_map.json"
        if m_path.exists():
            ids.update(json.loads(m_path.read_text()).keys())
    return ids


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
    # macOS path. On Linux the equivalent is /tmp/claude-<uid>/<encoded-cwd>/.
    # If/when this script is ported to Linux, fall back to /tmp/ here. For now
    # the --tasks-dir flag is the documented escape hatch.
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


def snapshot(tasks_dir: Path, run_dir: Path, snapshot_dir: Path) -> None:
    """Copy per-eval task transcripts into a run-local snapshot directory.

    Parameters
    ----------
    tasks_dir
        Directory containing ``<agent_id>.output`` transcript files.
    run_dir
        Eval run directory whose per-condition metadata maps evals to agent
        IDs.
    snapshot_dir
        Destination directory for copied ``<agent_id>.jsonl`` transcript
        snapshots.
    """

    snapshot_dir.mkdir(parents=True, exist_ok=True)
    mapped = collect_mapped_agent_ids(run_dir)
    if not mapped:
        raise SystemExit(f"No agent IDs found in {run_dir}/iteration-*/.agent_map.json")

    copied = skipped = 0
    for aid in mapped:
        src = tasks_dir / f"{aid}.output"
        if not src.exists():
            skipped += 1
            continue
        shutil.copy2(src, snapshot_dir / f"{aid}.jsonl")
        copied += 1

    size_kb = sum(p.stat().st_size for p in snapshot_dir.iterdir()) / 1024
    print(
        f"Snapshotted {copied}/{len(mapped)} transcripts to {snapshot_dir} ({size_kb:.1f} KB)"
    )
    if skipped:
        print(
            f"  WARN: {skipped} mapped agent IDs were not on disk under {tasks_dir}.\n"
            f"  Likely cause: the live Claude Code session was rotated (the harness\n"
            f"  wipes /private/tmp/claude-<uid>/<workspace-hash>/ on session change\n"
            f"  or reboot). Snapshots can ONLY be taken from the same session that\n"
            f"  dispatched the eval subagents — there is no recovery path once the\n"
            f"  session closes. Re-dispatch the missing evals if needed."
        )


def main() -> None:
    """Parse CLI arguments and snapshot transcripts for one eval run."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run",
        type=Path,
        required=True,
        help="Path to runs/<run-id>/ — the per-sweep directory holding iteration-N/.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Snapshot output dir. Defaults to <run>/transcripts_snapshot/.",
    )
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

    run_dir = args.run.resolve()
    if not run_dir.is_dir():
        raise SystemExit(f"--run {run_dir} is not a directory")
    snapshot_dir = (args.out or run_dir / "transcripts_snapshot").resolve()

    skill_root = find_skill_root(args.skill_root)
    mapped = collect_mapped_agent_ids(run_dir)
    if not mapped:
        raise SystemExit(f"No agent IDs found in {run_dir}/iteration-*/.agent_map.json")

    tasks_dir = args.tasks_dir or find_live_tasks_dir(mapped, skill_root)
    if tasks_dir is None or not tasks_dir.exists():
        raise SystemExit(
            "Could not locate the eval-sweep session tasks directory. "
            "Pass --tasks-dir explicitly. Expected path shape: "
            "/private/tmp/claude-<uid>/<encoded-cwd>/<session-uuid>/tasks/"
        )
    print(f"Reading transcripts from: {tasks_dir}")
    snapshot(tasks_dir, run_dir, snapshot_dir)


if __name__ == "__main__":
    main()
