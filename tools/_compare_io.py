"""Cross-run data join for eval-sweep comparisons.

Loads two runs side by side and produces overlap-only per-eval pair rows
with rubric-drift detection, plus the auxiliary inputs the writers and
figures need (overlap audit, targeted-edit map, taxonomy join).

Every aggregate is computed on the overlap subset only; full-run cumulative
JSON files are intentionally not consulted, since round-style targeted reruns
are subsets of prior full runs.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import shutil
import tempfile
from pathlib import Path
from typing import Literal, TypedDict

from _eval_io import (
    load_benchmarks,
    load_eval_catalog_for_run,
    load_eval_categories_from_run,
    load_expected_refs_from_catalog,
    load_expected_scripts_from_catalog,
    load_per_eval_duration_s,
    load_per_eval_timing,
)
from _schemas import EvalCategories, ExpectedResources, TranscriptRecord
from _transcripts import build_agent_to_run, configure_transcripts, parse_transcripts
from _util import discover_iterations

Transition = Literal["improved", "regressed", "stable_pass", "stable_fail"]


class RunBundle(TypedDict):
    """Everything we need from a single run for cross-run comparison."""
    run_dir: Path
    run_id: str
    batch_order: list[int]
    benchmarks: dict[int, dict]
    timing: dict[tuple[int, int, str], int]
    duration: dict[tuple[int, int, str], float]
    # Pre-bucketed timing / duration so per-eval lookups stay O(1) instead
    # of scanning the full table per call.
    timing_by_eid_cond: dict[tuple[int, str], list[int]]
    duration_by_eid_cond: dict[tuple[int, str], list[float]]
    categories: EvalCategories
    per_eval: dict[int, dict]  # eval_id -> per-eval row (last batch wins)
    # eval_id -> snapshot entry, parsed once. Empty if the run has no
    # evals_snapshot.json. Used by build_per_eval_pairs (intent),
    # write_catalog_diff_json, and the semantic-hash helper so the
    # snapshot is parsed at most once per run.
    catalog: dict[int, dict]
    # Raw bytes hash of the snapshot file (forensic, metadata-only); the
    # semantic hash lives in `provenance["evals_catalog_semantic_sha256"]`.
    failure_taxonomy: dict[int, dict[str, str]]
    edit_to_evals: dict[str, list[int]]
    has_transcripts: bool
    provenance: dict[str, str]


class OverlapAudit(TypedDict):
    old_run_id: str
    new_run_id: str
    old_total: int
    new_total: int
    n_overlap: int
    overlap_eval_ids: list[int]
    old_only: list[int]
    new_only: list[int]


class PerEvalPair(TypedDict):
    eval_id: int
    eval_name: str
    stage: str
    tier: str
    difficulty: str
    intent: str
    ws_missing_old: bool
    ws_missing_new: bool
    bs_missing_old: bool
    bs_missing_new: bool
    ws_pass_old: bool
    bs_pass_old: bool
    ws_pass_new: bool
    bs_pass_new: bool
    ws_passed_old: int
    ws_total_old: int
    bs_passed_old: int
    bs_total_old: int
    ws_passed_new: int
    ws_total_new: int
    bs_passed_new: int
    bs_total_new: int
    ws_rubric_changed: bool
    bs_rubric_changed: bool
    rubric_changed: bool  # ws_rubric_changed OR bs_rubric_changed
    tokens_ws_old: int | None
    tokens_ws_new: int | None
    tokens_bs_old: int | None
    tokens_bs_new: int | None
    duration_ws_old: float | None
    duration_ws_new: float | None
    duration_bs_old: float | None
    duration_bs_new: float | None
    outcome_old: str
    outcome_new: str
    ws_transition: Transition | None
    bs_transition: Transition | None
    failure_type_old: str
    failure_type_new: str
    regression_interpretation: str


def load_run_bundle(run_dir: Path) -> RunBundle:
    """Read everything we need from a single run for comparison.

    Loads benchmarks per iteration (not the cumulative summary), per-eval
    timing, categories from per-dispatch eval_metadata.json snapshots,
    failure_taxonomy.csv if a summary was generated, and the optional
    subset.edit_to_evals block from run.json.
    """
    run_dir = run_dir.resolve()
    batch_order = discover_iterations(run_dir)
    if not batch_order:
        raise SystemExit(f"No iteration-N/ dirs found under {run_dir}")
    benchmarks = load_benchmarks(run_dir, batch_order)
    timing = load_per_eval_timing(run_dir, batch_order)
    duration = load_per_eval_duration_s(run_dir, batch_order)
    categories = load_eval_categories_from_run(run_dir, batch_order)
    per_eval = _flatten_per_eval(benchmarks)
    run_meta = _load_run_meta(run_dir)
    catalog = _load_run_catalog_dict(run_dir)
    return {
        "run_dir": run_dir,
        "run_id": run_meta.get("run_id") or run_dir.name,
        "batch_order": batch_order,
        "benchmarks": benchmarks,
        "timing": timing,
        "duration": duration,
        "timing_by_eid_cond": _bucket_by_eid_cond(timing),
        "duration_by_eid_cond": _bucket_by_eid_cond(duration),
        "categories": categories,
        "per_eval": per_eval,
        "catalog": catalog,
        "failure_taxonomy": _load_failure_taxonomy(run_dir),
        "edit_to_evals": _load_edit_to_evals(run_meta),
        "has_transcripts": _has_transcripts(run_dir),
        "provenance": _provenance_block(run_dir, run_meta, catalog),
    }


def _bucket_by_eid_cond(table):
    """Pre-bucket a (batch, eval_id, cond) -> value table by (eval_id, cond).

    Lets `_bucketed_sum` look up an eval's tokens or duration in O(1)
    instead of scanning the whole table per call. Same return shape works
    for ints (timing) and floats (duration).
    """
    out: dict[tuple[int, str], list] = {}
    for (_, eid, cond), value in table.items():
        out.setdefault((eid, cond), []).append(value)
    return out


def compute_overlap(old: RunBundle, new: RunBundle) -> OverlapAudit:
    """Build the overlap audit; eval_ids sorted ascending in every list."""
    old_ids = set(old["per_eval"])
    new_ids = set(new["per_eval"])
    overlap = sorted(old_ids & new_ids)
    return {
        "old_run_id": old["run_id"],
        "new_run_id": new["run_id"],
        "old_total": len(old_ids),
        "new_total": len(new_ids),
        "n_overlap": len(overlap),
        "overlap_eval_ids": overlap,
        "old_only": sorted(old_ids - new_ids),
        "new_only": sorted(new_ids - old_ids),
    }


def build_per_eval_pairs(
    old: RunBundle, new: RunBundle, overlap: OverlapAudit
) -> list[PerEvalPair]:
    """One row per overlap eval, joining ws/bs counts, tokens, and taxonomy.

    Tokens are summed across the eval's batches in each run (a given eval is
    typically only in one batch, but the structure tolerates multi-batch).
    """
    # Catalog-sourced metadata (intent and any future per-eval annotations)
    # comes from the run's evals_snapshot, not the per-dispatch
    # eval_metadata.json. Already cached on each bundle by load_run_bundle.
    new_catalog = new["catalog"]
    old_catalog = old["catalog"]
    pairs: list[PerEvalPair] = []
    for eid in overlap["overlap_eval_ids"]:
        old_row = old["per_eval"][eid]
        new_row = new["per_eval"][eid]
        cats = new["categories"].get(eid) or old["categories"].get(eid) or {}
        catalog_entry = new_catalog.get(eid) or old_catalog.get(eid) or {}
        intent = str(catalog_entry.get("intent") or "unknown")
        ws_missing_old = bool(old_row["ws_missing"])
        ws_missing_new = bool(new_row["ws_missing"])
        bs_missing_old = bool(old_row["bs_missing"])
        bs_missing_new = bool(new_row["bs_missing"])
        # Rubric drift is per-condition: a baseline-only rubric change should
        # not make a with-skill regression look rubric-sensitive, and vice
        # versa. Missing-cell pairs are not rubric drift; missing-data is
        # flagged separately. rubric_changed is the OR for downstream
        # consumers that want one combined flag.
        ws_rubric_changed = (
            not ws_missing_old
            and not ws_missing_new
            and old_row["ws_total"] != new_row["ws_total"]
        )
        bs_rubric_changed = (
            not bs_missing_old
            and not bs_missing_new
            and old_row["bs_total"] != new_row["bs_total"]
        )
        outcome_old = _outcome_label(
            old_row["ws_pass"], old_row["bs_pass"], ws_missing_old, bs_missing_old
        )
        outcome_new = _outcome_label(
            new_row["ws_pass"], new_row["bs_pass"], ws_missing_new, bs_missing_new
        )
        ws_transition = _transition(
            old_row["ws_pass"], new_row["ws_pass"], ws_missing_old or ws_missing_new
        )
        bs_transition = _transition(
            old_row["bs_pass"], new_row["bs_pass"], bs_missing_old or bs_missing_new
        )
        failure_old = old["failure_taxonomy"].get(eid, {}).get("failure_type", "")
        failure_new = new["failure_taxonomy"].get(eid, {}).get("failure_type", "")
        pair: PerEvalPair = {
            "eval_id": eid,
            "eval_name": new_row["eval_name"],
            "stage": cats.get("stage", "unknown"),
            "tier": cats.get("tier", "unknown"),
            "difficulty": cats.get("difficulty", "unknown"),
            "intent": intent,
            "ws_missing_old": ws_missing_old,
            "ws_missing_new": ws_missing_new,
            "bs_missing_old": bs_missing_old,
            "bs_missing_new": bs_missing_new,
            "ws_pass_old": old_row["ws_pass"],
            "bs_pass_old": old_row["bs_pass"],
            "ws_pass_new": new_row["ws_pass"],
            "bs_pass_new": new_row["bs_pass"],
            "ws_passed_old": old_row["ws_passed"],
            "ws_total_old": old_row["ws_total"],
            "bs_passed_old": old_row["bs_passed"],
            "bs_total_old": old_row["bs_total"],
            "ws_passed_new": new_row["ws_passed"],
            "ws_total_new": new_row["ws_total"],
            "bs_passed_new": new_row["bs_passed"],
            "bs_total_new": new_row["bs_total"],
            "ws_rubric_changed": ws_rubric_changed,
            "bs_rubric_changed": bs_rubric_changed,
            "rubric_changed": ws_rubric_changed or bs_rubric_changed,
            "tokens_ws_old": _bucketed_sum(old["timing_by_eid_cond"], eid, "with_skill"),
            "tokens_ws_new": _bucketed_sum(new["timing_by_eid_cond"], eid, "with_skill"),
            "tokens_bs_old": _bucketed_sum(old["timing_by_eid_cond"], eid, "without_skill"),
            "tokens_bs_new": _bucketed_sum(new["timing_by_eid_cond"], eid, "without_skill"),
            "duration_ws_old": _bucketed_sum(old["duration_by_eid_cond"], eid, "with_skill"),
            "duration_ws_new": _bucketed_sum(new["duration_by_eid_cond"], eid, "with_skill"),
            "duration_bs_old": _bucketed_sum(old["duration_by_eid_cond"], eid, "without_skill"),
            "duration_bs_new": _bucketed_sum(new["duration_by_eid_cond"], eid, "without_skill"),
            "outcome_old": outcome_old,
            "outcome_new": outcome_new,
            "ws_transition": ws_transition,
            "bs_transition": bs_transition,
            "failure_type_old": failure_old,
            "failure_type_new": failure_new,
            "regression_interpretation": _interpret_regression(
                ws_transition, ws_rubric_changed, failure_new
            ),
        }
        pairs.append(pair)
    return pairs


def _flatten_per_eval(benchmarks: dict[int, dict]) -> dict[int, dict]:
    """Map eval_id -> {ws/bs pass + counts + name + batch + missing flags}.

    Uses the union of ws and bs eval IDs per batch so partial dispatches
    (e.g. ws aborted but bs ran, or vice versa) carry through with explicit
    ws_missing / bs_missing flags rather than being silently dropped or
    imputed as failed.
    """
    out: dict[int, dict] = {}
    for batch_id, bench in benchmarks.items():
        ws_results = {
            e["eval_id"]: e
            for e in bench["configurations"]["with_skill"]["eval_results"]
        }
        bs_results = {
            e["eval_id"]: e
            for e in bench["configurations"]["without_skill"]["eval_results"]
        }
        for eid in sorted(set(ws_results) | set(bs_results)):
            ws_r = ws_results.get(eid)
            bs_r = bs_results.get(eid)
            name = (ws_r or bs_r or {}).get("eval_name", f"eval-{eid}")
            out[eid] = {
                "eval_id": eid,
                "eval_name": name,
                "batch": batch_id,
                "ws_missing": ws_r is None,
                "bs_missing": bs_r is None,
                "ws_pass": bool(ws_r["all_passed"]) if ws_r else False,
                "bs_pass": bool(bs_r["all_passed"]) if bs_r else False,
                "ws_passed": int(ws_r["passed_count"]) if ws_r else 0,
                "ws_total": int(ws_r["total"]) if ws_r else 0,
                "bs_passed": int(bs_r["passed_count"]) if bs_r else 0,
                "bs_total": int(bs_r["total"]) if bs_r else 0,
            }
    return out


def _load_run_meta(run_dir: Path) -> dict:
    path = run_dir / "run.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _load_edit_to_evals(run_meta: dict) -> dict[str, list[int]]:
    subset = run_meta.get("subset", {}) if isinstance(run_meta, dict) else {}
    raw = subset.get("edit_to_evals", {}) if isinstance(subset, dict) else {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[int]] = {}
    for edit_id, eval_ids in raw.items():
        if not isinstance(eval_ids, list):
            continue
        out[str(edit_id)] = [int(e) for e in eval_ids if isinstance(e, int)]
    return out


def _load_failure_taxonomy(run_dir: Path) -> dict[int, dict[str, str]]:
    """Read summary/data/failure_taxonomy.csv if present."""
    path = run_dir / "summary" / "data" / "failure_taxonomy.csv"
    if not path.is_file():
        return {}
    out: dict[int, dict[str, str]] = {}
    for row in csv.DictReader(io.StringIO(path.read_text())):
        eid = row.get("eval_id", "")
        if eid.isdigit():
            out[int(eid)] = {
                "failure_type": row.get("failure_type", ""),
                "notes": row.get("notes", ""),
            }
    return out


def _has_transcripts(run_dir: Path) -> bool:
    snap = run_dir / "transcripts_snapshot"
    return snap.is_dir() and any(snap.iterdir())


def _bucketed_sum(by_eid_cond, eid: int, cond: str):
    """Sum the values for one (eid, cond) bucket; None when the bucket is empty.

    Reads from a pre-bucketed dict produced by `_bucket_by_eid_cond`. Replaces
    the previous O(n_table) per-call linear scan with O(1) lookup.
    """
    values = by_eid_cond.get((eid, cond))
    return sum(values) if values else None


def _outcome_label(
    ws_pass: bool, bs_pass: bool, ws_missing: bool = False, bs_missing: bool = False
) -> str:
    """4-cell outcome label, with explicit `missing` rather than imputed-fail."""
    if ws_missing or bs_missing:
        return "missing"
    if ws_pass and bs_pass:
        return "both_pass"
    if ws_pass:
        return "skill_only"
    if bs_pass:
        return "baseline_only"
    return "both_fail"


def _transition(old_pass: bool, new_pass: bool, missing: bool = False) -> Transition | None:
    """Pass→pass transition, or None if either side's cell is missing."""
    if missing:
        return None
    if old_pass and new_pass:
        return "stable_pass"
    if not old_pass and not new_pass:
        return "stable_fail"
    return "improved" if new_pass else "regressed"


def _interpret_regression(
    ws_transition: Transition | None, rubric_changed: bool, failure_type_new: str
) -> str:
    """Label ws_transition with the most informative root cause we can infer.

    rubric_friction takes precedence (annotator labeled the failure), then
    rubric_drift (counts changed but no annotation), then content_regression
    when rubric is stable. Improvements and stable cells are blank.
    """
    if ws_transition != "regressed":
        return ""
    if failure_type_new == "rubric_friction":
        return "rubric_friction"
    if rubric_changed:
        return "rubric_drift"
    return "content_regression"


def _provenance_block(
    run_dir: Path, run_meta: dict, catalog: dict[int, dict] | None = None
) -> dict[str, str]:
    """Pull comparable provenance fields from run.json + evals snapshot.

    Captures the dimensions that drive cross-run drift in skill quality
    measurements:

    - **causal** (drift here can shift headline / transition deltas): skill
      commit (start + end), spyglass src commit, model, harness, dispatch
      prompt template, grader model / model version / prompt template /
      prompt sha256, and ``evals_catalog_semantic_sha256``.
    - **metadata** (label-only or wrapper noise): skill_branch, round_label,
      and ``evals_snapshot_sha256_raw``.

    Two evals-catalog hashes are emitted:

    - ``evals_catalog_semantic_sha256``: hash of a canonical normalized
      representation of the catalog that ignores wrapper / formatting noise
      (``source`` field, key order, whitespace) and covers every semantic
      per-eval field (id, name, eval_name, stage / tier / difficulty,
      prompt, expected_output, expectations, assertions, files,
      expected_refs, expected_scripts). This is the causal dimension — it
      changes only when actual eval content changes.
    - ``evals_snapshot_sha256_raw``: hash of the raw snapshot bytes. Useful
      for forensics but tagged metadata-only because reformatting / source
      path changes flip it without any change to what was measured.

    Empty string when a field is absent on a given run.
    """
    keys = (
        "skill_commit_at_sweep_start",
        "skill_commit_at_sweep_end",
        "skill_branch",
        "spyglass_src_commit",
        "model",
        "harness",
        "dispatch_prompt_template",
        # Grader provenance: when the grading model / its prompt template
        # changes, headline movement can no longer be cleanly attributed to
        # the skill. run.json may declare any subset of these keys; missing
        # keys read as empty and are not flagged changed (per the writer's
        # both-non-empty rule).
        "grader_model",
        "grader_model_version",
        "grader_prompt_template",
        "grader_prompt_sha256",
        "round_label",
    )
    # Normalize null / missing to empty string so a run.json with `"key": null`
    # is treated as "absent" rather than the literal string "None". Without
    # this, a missing field on one side reads as a drift against a present
    # value on the other side.
    out: dict[str, str] = {}
    for key in keys:
        value = run_meta.get(key)
        out[key] = "" if value is None else str(value)
    out["evals_catalog_semantic_sha256"] = _evals_catalog_semantic_hash(run_dir, catalog)
    out["evals_snapshot_sha256_raw"] = _evals_snapshot_raw_hash(run_dir)
    return out


_SEMANTIC_SCALAR_FIELDS: tuple[str, ...] = (
    "name",
    "eval_name",
    "stage",
    "tier",
    "difficulty",
    # Eval intent: should_trigger / should_not_trigger / near_miss_negative /
    # destructive_operation_caution / setup / ingestion / debugging /
    # custom_pipeline_authoring / unknown. Tracks whether the eval set is
    # balanced for activation *behavior* (restraint, not just helpfulness).
    "intent",
    "prompt",
    "expected_output",
)
_SEMANTIC_LIST_FIELDS: tuple[str, ...] = ("assertions", "files")
_SEMANTIC_RESOURCE_FIELDS: tuple[str, ...] = ("expected_refs", "expected_scripts")


def _evals_catalog_semantic_hash(
    run_dir: Path, catalog: dict[int, dict] | None = None
) -> str:
    """sha256 of a canonical normalized representation of the eval catalog.

    Stable under wrapper / formatting changes: ignores the snapshot's
    ``source`` field, key order, and whitespace. Hashes every semantic
    per-eval field — id, scalar text fields (name, eval_name, stage, tier,
    difficulty, prompt, expected_output), list fields (assertions, files),
    expectations, and the expected_refs / expected_scripts blocks. This is
    the hash that should drive the causal_changed flag in
    provenance_diff.json — drift here means an actual eval was added,
    removed, or had its content edited.

    Accepts a pre-parsed ``catalog`` dict (eval_id -> entry) so callers
    that already loaded the snapshot don't pay for a second JSON parse.
    """
    if catalog is None:
        loaded = _load_run_catalog(run_dir)
        if loaded is None:
            return ""
        entries = loaded
    else:
        entries = list(catalog.values())
    canonical = [_canonical_eval(e) for e in entries if _eval_id(e) is not None]
    canonical.sort(key=lambda e: e["id"])
    payload = json.dumps(
        canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _eval_id(entry: object) -> int | None:
    if not isinstance(entry, dict):
        return None
    try:
        return int(entry["id"])
    except (KeyError, TypeError, ValueError):
        return None


def _canonical_eval(entry: dict) -> dict:
    """Normalize one eval entry to its semantic payload, sorted/canonical."""
    norm: dict = {"id": _eval_id(entry)}
    for field in _SEMANTIC_SCALAR_FIELDS:
        norm[field] = entry.get(field, "") if entry.get(field) is not None else ""
    for field in _SEMANTIC_LIST_FIELDS:
        value = entry.get(field) or []
        norm[field] = _canonical_list(value)
    norm["expectations"] = _canonical_expectations(entry.get("expectations") or [])
    for field in _SEMANTIC_RESOURCE_FIELDS:
        norm[field] = _canonical_resource_block(entry.get(field))
    return norm


def _canonical_list(values: object) -> object:
    """Normalize a list-of-strings/dicts OR a dict-of-lists for hashing/diffing.

    Some fields (assertions in the real catalog shape) are dict-of-lists like
    ``{"required_substrings": [...], "forbidden_substrings": [...],
    "behavioral_checks": [...]}`` rather than flat lists. Both shapes need
    canonical normalization so silent edits to any sub-list flip the hash.
    Returns a list when input is list-shaped, a sorted-key dict when
    input is dict-shaped, and ``[]`` when input is anything else.
    """
    if isinstance(values, dict):
        return {
            str(k): _canonical_list(values[k])
            for k in sorted(str(k) for k in values)
        }
    if not isinstance(values, list):
        return []
    out = []
    for v in values:
        if isinstance(v, dict):
            out.append({k: v[k] for k in sorted(v)})
        else:
            out.append(str(v))
    out.sort(key=lambda x: json.dumps(x, sort_keys=True, ensure_ascii=False))
    return out


def _canonical_expectations(expectations: list) -> list:
    """Normalize a list of expectation rows: sort by stable text representation."""
    norm = []
    for exp in expectations:
        if isinstance(exp, dict):
            # sort_keys is applied later, but a dict comparison wants a stable
            # repr for sorting; use the JSON form.
            norm.append({k: exp[k] for k in sorted(exp)})
        else:
            norm.append({"_repr": repr(exp)})
    return sorted(norm, key=lambda d: json.dumps(d, sort_keys=True, ensure_ascii=False))


def _canonical_resource_block(block: object) -> dict:
    """Normalize a {required, optional, distractor} resource block."""
    if not isinstance(block, dict):
        return {"required": [], "optional": [], "distractor": []}
    return {
        slot: sorted(str(v) for v in (block.get(slot) or []))
        for slot in ("required", "optional", "distractor")
    }


def _load_run_catalog(run_dir: Path) -> list[dict] | None:
    """Read the run-local evals_snapshot.json and return its evals list, or None."""
    for candidate in (
        run_dir / "evals_snapshot.json",
        run_dir / "summary" / "data" / "evals_snapshot.json",
    ):
        if candidate.is_file():
            try:
                payload = json.loads(candidate.read_text())
            except (json.JSONDecodeError, OSError):
                return None
            evals = payload.get("evals")
            if isinstance(evals, list):
                return evals
            return None
    return None


def _evals_snapshot_raw_hash(run_dir: Path) -> str:
    """sha256 of the raw bytes of the run-local evals_snapshot.json.

    Returns "" if no snapshot exists on this run. Hashing raw bytes (not
    parsed JSON) so a reformatted-but-content-equal file still hashes
    differently — useful for forensics but **does not** drive causal_changed
    because reformatting / source path changes are not real eval drift.
    """
    for candidate in (
        run_dir / "evals_snapshot.json",
        run_dir / "summary" / "data" / "evals_snapshot.json",
    ):
        if candidate.is_file():
            return hashlib.sha256(candidate.read_bytes()).hexdigest()[:12]
    return ""


def load_routing_records(bundle: RunBundle) -> dict[tuple[int, str], TranscriptRecord]:
    """Parse a run's snapshotted transcripts and key them by (eval_id, condition).

    Returns an empty dict if the run has no transcripts_snapshot. Uses the
    existing _transcripts module API, which mutates module-level globals via
    configure_transcripts; this is safe to call sequentially for old then new
    because each call captures its records before the next reconfigure.

    configure_transcripts insists on creating an OUT/.data_tmp dir. We never
    write transcript output here, so we route that through a tempfile and
    remove it before returning so the run dirs stay clean.
    """
    if not bundle["has_transcripts"]:
        return {}
    snap = bundle["run_dir"] / "transcripts_snapshot"
    staging_root = Path(tempfile.mkdtemp(prefix="compare-transcripts-"))
    try:
        configure_transcripts(
            staging_root / "fake_out",
            bundle["run_dir"],
            bundle["batch_order"],
        )
        agent_to_run = build_agent_to_run()
        records = parse_transcripts(snap, agent_to_run)
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)
    out: dict[tuple[int, str], TranscriptRecord] = {}
    for r in records:
        out[(int(r["eval_id"]), str(r["condition"]))] = r
    return out


def load_expected_resources(bundle: RunBundle) -> tuple[ExpectedResources, ExpectedResources]:
    """Return expected_refs / expected_scripts from the run's cached catalog."""
    catalog_entries = list(bundle["catalog"].values())
    return (
        load_expected_refs_from_catalog(catalog_entries),
        load_expected_scripts_from_catalog(catalog_entries),
    )


def load_eval_catalog(bundle: RunBundle) -> dict[int, dict]:
    """Return the run's evals_snapshot keyed by eval id.

    The snapshot is parsed once when the bundle is constructed
    (`load_run_bundle`) and cached on `bundle["catalog"]`; this function
    is kept as the public accessor so callers don't reach into the
    TypedDict directly.
    """
    return bundle["catalog"]


def _load_run_catalog_dict(run_dir: Path) -> dict[int, dict]:
    """Read evals_snapshot.json and key it by eval id; `{}` if absent."""
    fallback = run_dir / "_unused_evals.json"  # never read
    try:
        catalog, _, _ = load_eval_catalog_for_run(run_dir, fallback)
    except FileNotFoundError:
        return {}
    out: dict[int, dict] = {}
    for entry in catalog:
        try:
            out[int(entry["id"])] = entry
        except (KeyError, TypeError, ValueError):
            continue
    return out
