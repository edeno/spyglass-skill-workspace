"""Transcript parsing and transcript-level summaries."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from _schemas import PerEvalResult, TranscriptRecord

_UNCONFIGURED = Path("/__not_configured__")
OUT: Path = _UNCONFIGURED
DATA: Path = _UNCONFIGURED
WORKSPACE: Path = _UNCONFIGURED
BATCH_ORDER: list[int] = []


def configure_transcripts(out: Path, workspace: Path, batch_order: list[int]) -> None:
    """Set run-scoped transcript globals."""
    global OUT, DATA, WORKSPACE, BATCH_ORDER
    OUT = out
    DATA = OUT / ".data_tmp"
    DATA.mkdir(parents=True, exist_ok=True)
    WORKSPACE = workspace
    BATCH_ORDER = batch_order


def data_path(name: str) -> Path:
    """Return the path for generated transcript summary data."""
    return DATA / name


TRACKED_SCRIPTS = [
    "code_graph.py",  # static FK / source-walker — agent-facing
    "db_graph.py",  # live-DB introspection — agent-facing
    "scrub_dj_config.py",  # password-safe config viewer — agent-facing
    "verify_spyglass_env.py",  # config sanity-check — agent-facing
    "validate_skill.py",  # skill maintainer tool
    "validate_all.sh",  # skill maintainer tool
    "_index.py",  # skill maintainer tool
]
TRACKED_SCRIPT_ROLES = {
    "code_graph.py": "agent",
    "db_graph.py": "agent",
    "scrub_dj_config.py": "agent",
    "verify_spyglass_env.py": "agent",
    "validate_skill.py": "maintainer",
    "validate_all.sh": "maintainer",
    "_index.py": "maintainer",
}

def build_agent_to_run() -> dict[str, tuple[int, int, str]]:
    """Read every iteration-N/.agent_map.json and return agent_id -> (batch, eval_id, cond).

    Tolerant of unexpected directory shapes — entries with malformed eval-NNN
    names are skipped with a printed warning instead of raising IndexError /
    ValueError mid-pipeline.
    """
    agent_to_run: dict[str, tuple[int, int, str]] = {}
    for i in BATCH_ORDER:
        m_path = WORKSPACE / f"iteration-{i}" / ".agent_map.json"
        if not m_path.exists():
            continue
        for aid, rdir in json.loads(m_path.read_text()).items():
            parts = rdir.rstrip("/").split("/")
            if len(parts) < 2:
                print(f"  warn: skipping agent {aid} — malformed agent_map value {rdir!r}")
                continue
            eval_dir, cond = parts[-2], parts[-1]
            try:
                eid = int(eval_dir.split("-")[1])
            except (IndexError, ValueError):
                print(
                    f"  warn: skipping agent {aid} — could not parse eval_id from {eval_dir!r}"
                )
                continue
            agent_to_run[aid] = (i, eid, cond)
    return agent_to_run

def parse_transcripts(
    snapshot_dir: Path, agent_to_run: dict[str, tuple[int, int, str]]
) -> list[TranscriptRecord]:
    """Single-pass parse of every snapshotted transcript that maps to a run.

    Returns one record per transcript file with all the tool-call counters
    that downstream plots and stats need. Sorted by agent_id so output JSONs
    are deterministic regardless of filesystem iteration order.
    """
    records: list[TranscriptRecord] = []
    for tf in sorted(snapshot_dir.iterdir()):
        if tf.suffix != ".jsonl":
            continue
        aid = tf.stem
        if aid not in agent_to_run:
            continue
        batch, eval_id, cond = agent_to_run[aid]
        rec: TranscriptRecord = {
            "agent_id": aid,
            "batch": batch,
            "eval_id": eval_id,
            "condition": cond,
            "n_read_calls": 0,
            "n_bash_calls": 0,
            "n_tool_errors": 0,
            "ref_opens": Counter(),
            "script_executions": Counter(),
            "script_source_reads": Counter(),
            "spyglass_src_reads": 0,
            "skill_dir_touches": 0,
        }
        for line in tf.read_text().splitlines():
            if not line.startswith("{"):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            content = obj.get("message", {}).get("content", [])
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_result" and block.get("is_error"):
                    rec["n_tool_errors"] += 1
                    continue
                if block.get("type") != "tool_use":
                    continue
                name = block.get("name") or ""
                inp = block.get("input") or {}
                if name == "Read":
                    rec["n_read_calls"] += 1
                    path = inp.get("file_path") or ""
                    if "skills/spyglass/references/" in path:
                        ref = path.split("skills/spyglass/references/")[-1]
                        rec["ref_opens"][ref] += 1
                    elif path.endswith("SKILL.md") and "skills/spyglass/" in path:
                        rec["ref_opens"]["SKILL.md"] += 1
                    if "skills/spyglass/scripts/" in path:
                        fname = path.rsplit("/", 1)[-1]
                        if fname in TRACKED_SCRIPTS:
                            rec["script_source_reads"][fname] += 1
                    if "skills/spyglass/" in path:
                        rec["skill_dir_touches"] += 1
                    # Heuristic for "agent read upstream Spyglass source" — used
                    # to distinguish parametric-memory baseline from source-assisted
                    # baseline. Matches the path shape from the round-c dispatch
                    # template ("/spyglass/src/spyglass/").
                    if "/spyglass/src/" in path and "skills/spyglass/" not in path:
                        rec["spyglass_src_reads"] += 1
                elif name == "Bash":
                    rec["n_bash_calls"] += 1
                    cmd = inp.get("command", "") or ""
                    for s in TRACKED_SCRIPTS:
                        if _is_script_execution(cmd, s):
                            rec["script_executions"][s] += 1
                    if "skills/spyglass/" in cmd:
                        rec["skill_dir_touches"] += 1
                    # Source-assistance via cat/head/grep/etc. — round-c hand-audit
                    # found ~9 baseline runs using Bash to inspect Spyglass source
                    # rather than the Read tool, so the heuristic must catch both.
                    if "/spyglass/src/" in cmd and "skills/spyglass/" not in cmd:
                        rec["spyglass_src_reads"] += 1
                elif name in ("Glob", "LS", "Grep"):
                    target = (
                        inp.get("pattern") or inp.get("path") or ""
                    )
                    if "skills/spyglass/" in target:
                        rec["skill_dir_touches"] += 1
                    if "/spyglass/src/" in target and "skills/spyglass/" not in target:
                        rec["spyglass_src_reads"] += 1
                elif name == "WebFetch":
                    # Counts as "agent consulted upstream Spyglass source" if
                    # the URL points at the Spyglass GitHub repo (any branch /
                    # path / blob URL). Round-c saw this ~4× across baseline.
                    url = (inp.get("url") or "").lower()
                    if "github.com/lorenfranklab/spyglass" in url or "spyglass.readthedocs" in url:
                        rec["spyglass_src_reads"] += 1
        records.append(rec)
    return records

def write_transcript_stats(
    records: list[TranscriptRecord],
    total_ws: int,
    total_bs: int,
    per_eval: list[PerEvalResult] | None = None,
) -> None:
    """Aggregate transcript records into the cost-shape and contamination JSON.

    Captures the numbers SUMMARY.md cites in §"Transcript-level caveats":
    - Per-condition total Read / Bash tool-call counts.
    - Baseline runs that read upstream Spyglass source (source-assisted baseline).
    - Baseline runs that touched the skill bundle (contamination).
    - With-skill SKILL.md activation deduplicated to unique evals (not transcripts).
    """
    n_read = {"with_skill": 0, "without_skill": 0}
    n_bash = {"with_skill": 0, "without_skill": 0}
    n_errors = {"with_skill": 0, "without_skill": 0}
    src_runs = {"with_skill": set(), "without_skill": set()}
    bs_skill_contaminated: set[str] = set()
    ws_evals_opened_skill_md: set[tuple[int, int]] = set()

    for r in records:
        cond = r["condition"]
        n_read[cond] = n_read.get(cond, 0) + r["n_read_calls"]
        n_bash[cond] = n_bash.get(cond, 0) + r["n_bash_calls"]
        n_errors[cond] = n_errors.get(cond, 0) + r["n_tool_errors"]
        if r["spyglass_src_reads"] > 0:
            src_runs[cond].add(r["agent_id"])
        if cond == "without_skill" and r["skill_dir_touches"] > 0:
            bs_skill_contaminated.add(r["agent_id"])
        if cond == "with_skill" and r["ref_opens"].get("SKILL.md", 0) > 0:
            ws_evals_opened_skill_md.add((r["batch"], r["eval_id"]))

    n_ws_evals_total = len({(r["batch"], r["eval_id"]) for r in records if r["condition"] == "with_skill"})

    payload = {
        "n_with_skill_transcripts": total_ws,
        "n_without_skill_transcripts": total_bs,
        "tool_calls": {
            "with_skill": {
                "read": n_read["with_skill"],
                "bash": n_bash["with_skill"],
                "errors": n_errors["with_skill"],
            },
            "without_skill": {
                "read": n_read["without_skill"],
                "bash": n_bash["without_skill"],
                "errors": n_errors["without_skill"],
            },
            "errors_note": "n tool_result blocks with is_error=true. Reflects retried/recovered failures inside a transcript — not whether the eval ultimately passed.",
        },
        "spyglass_src_assisted_runs": {
            "with_skill": len(src_runs["with_skill"]),
            "without_skill": len(src_runs["without_skill"]),
            "note": (
                "n transcripts where any tool reached /spyglass/src/ outside "
                "skills/spyglass/, OR WebFetched github.com/LorenFrankLab/spyglass "
                "or spyglass.readthedocs. Includes Read paths, Bash commands "
                "(cat/head/grep on source), and Glob/LS/Grep targets. Mechanical "
                "proxy for 'agent consulted upstream Spyglass source'."
            ),
        },
        "baseline_skill_contamination": {
            "n_runs": len(bs_skill_contaminated),
            "note": "n without_skill transcripts that touched any path under skills/spyglass/ (Read, Bash, Glob, or LS). Despite the dispatch prompt forbidding this, some baseline runs accessed the skill bundle.",
        },
        "skill_md_activation": {
            "with_skill_unique_evals_opening": len(ws_evals_opened_skill_md),
            "with_skill_total_unique_evals": n_ws_evals_total,
            "rate": (
                round(100 * len(ws_evals_opened_skill_md) / n_ws_evals_total, 2)
                if n_ws_evals_total
                else 0.0
            ),
            "note": "Per-eval (not per-transcript) rate at which SKILL.md was opened in any with_skill transcript for that eval. Deduplicates retries; should be ~100% if activation is reliable.",
        },
    }

    # Mean number of references opened per transcript, split by outcome.
    # Round-c surfaced a counterintuitive pattern here: failing ws transcripts
    # open MORE refs than passing ones, supporting "loaded the right ref but
    # didn't escalate" over "didn't find the right ref". Reported only when
    # per_eval is available (caller passes it).
    if per_eval is not None:
        pass_by_eval: dict[int, dict[str, bool]] = {
            r["eval_id"]: {"ws_pass": bool(r["ws_pass"]), "bs_pass": bool(r["bs_pass"])}
            for r in per_eval
        }
        buckets: dict[str, list[int]] = {
            "with_skill_pass": [], "with_skill_fail": [],
            "without_skill_pass": [], "without_skill_fail": [],
        }
        for r in records:
            outcome = pass_by_eval.get(r["eval_id"], {})
            cond = r["condition"]
            key_pass = "ws_pass" if cond == "with_skill" else "bs_pass"
            label = f"{cond}_{'pass' if outcome.get(key_pass) else 'fail'}"
            buckets[label].append(len(r["ref_opens"]))

        def mean_or_zero(xs: list[int]) -> float:
            return round(sum(xs) / len(xs), 2) if xs else 0.0

        mean_refs_block: dict = {
            label: {"n": len(xs), "mean_refs_opened": mean_or_zero(xs)}
            for label, xs in buckets.items()
        }
        mean_refs_block["note"] = (
            "Mean count of distinct references opened per transcript, split by "
            "(condition, ws/bs pass-fail). Round-c showed ws_fail > ws_pass, "
            "i.e. failing ws transcripts open MORE refs than passing ones — "
            "consistent with the SUMMARY thesis that failures are 'loaded "
            "enough but didn't escalate to verification', not 'didn't find "
            "the right ref'."
        )
        payload["mean_refs_per_outcome"] = mean_refs_block

    (data_path("transcript_stats.json")).write_text(json.dumps(payload, indent=2) + "\n")

def _is_script_execution(cmd: str, script: str) -> bool:
    """Did this Bash command actually execute the script?

    Required to be preceded by python / python3 / bash / sh / ./ (or be the
    very first token, allowing for env-var prefixes). Bare mentions of the
    filename — e.g. inside a grep, cat, ls, or head argument — do NOT count
    as executions. This prevents a measurement bug where a `grep validate_skill.py
    src.py` was being recorded as an invocation of the validator.

    The optional `(?:\\S+/)?` before the escaped script name allows a path
    prefix that ends in `/` (e.g. `skills/spyglass/scripts/code_graph.py`)
    but rejects substring matches like `my_code_graph.py` matching
    `code_graph.py`. The trailing `(?:[\\s|;&<>]|$)` requires the script name
    to end at end-of-string or a shell token boundary, so `code_graph.py.bak`
    is rejected (not a real invocation).
    """
    pat = (
        rf"(?:^|[\s|;&])"
        rf"(?:(?:python3?|bash|sh)\s+(?:\S+/)?{re.escape(script)}"
        rf"|\./(?:\S+/)?{re.escape(script)})"
        rf"(?:[\s|;&<>]|$)"
    )
    return re.search(pat, cmd) is not None
