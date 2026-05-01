"""CSV/JSON writers for cross-run comparison outputs.

Outputs:
- overlap.json + headline_diff.json
- transitions.csv (per overlap eval)
- targeted_edits_long.csv + targeted_edits_summary.csv (when the new run
  declares run.json["subset"]["edit_to_evals"])
- outcome_2x2_shift.json (4-cell counts at old vs new + 4x4 flow matrix on
  the joint set where both ws and bs cells are present in both runs)
- cost_shift.csv (per-overlap-eval token deltas for ws and bs, joined with
  ws_transition + per-condition pair-completeness flags so cost-by-transition
  figures don't silently mix complete and partial timing)
- routing_shift.csv (per (eval, condition) required-ref / required-script
  recall + unexpected-resource counts at old vs new, with routing_complete=
  false rows preserved when transcripts are missing on either side; gated on
  both runs having transcripts_snapshot/)

Aggregates honor rubric drift per-condition: ws expectation deltas are flagged
rubric_sensitive when any overlap eval has ws_total_old != ws_total_new, and bs
deltas are flagged independently for the bs side. headline_diff.json reports
both flags plus a combined `any` so consumers can pick the granularity they need.
"""

from __future__ import annotations

import csv
import io
import json
from collections import Counter
from collections.abc import Mapping
from pathlib import Path

from _aggregations import exact_mcnemar_p
from _compare_io import OverlapAudit, PerEvalPair, RunBundle
from _schemas import ExpectedResources, TranscriptRecord

_OUTCOME_BUCKETS = ("both_pass", "skill_only", "baseline_only", "both_fail")

# (family, priority, purpose) for each comparison output. New writers/figures
# should add entries here; anything missing falls back to appendix priority
# and is reported on stdout so it can be promoted deliberately.
COMPARISON_MANIFEST_OVERRIDES: dict[str, tuple[str, str, str]] = {
    "INDEX.md": ("audit", "primary", "Generated guide to comparison outputs grouped by priority."),
    "data/comparison_manifest.json": (
        "audit",
        "primary",
        "Output family/priority/purpose index for this comparison.",
    ),
    "data/overlap.json": (
        "audit",
        "primary",
        "Overlap audit: old/new totals, n_overlap, old_only/new_only eval ids. "
        "Read this first to confirm what was actually compared.",
    ),
    "data/headline_diff.json": (
        "headline",
        "primary",
        "Overlap-only ws/bs full-pass shift, expectation deltas with rubric_sensitive flags, "
        "transition tables, and a diagnostic-only McNemar p-value.",
    ),
    "data/transitions.csv": (
        "transitions",
        "primary",
        "One row per overlap eval with ws/bs transitions, rubric drift, token deltas, "
        "and regression_interpretation (rubric_friction / rubric_drift / content_regression).",
    ),
    "data/outcome_2x2_shift.json": (
        "outcome_flow",
        "primary",
        "4-cell outcome counts at old vs new on the joint set, plus a 4x4 flow matrix "
        "with eval_id examples per cell.",
    ),
    "data/cost_shift.csv": (
        "cost",
        "secondary",
        "Per-overlap-eval token deltas for ws and bs with pair-completeness flags so "
        "incomplete timing is never silently aggregated.",
    ),
    "data/routing_shift.csv": (
        "routing",
        "secondary",
        "Per (eval, condition) required-ref / required-script recall and unexpected-resource "
        "counts at old vs new. Gated on transcripts on both sides.",
    ),
    "data/targeted_edits_long.csv": (
        "targeted_edits",
        "secondary",
        "Many-to-many (edit_id, eval_id) rows joining each declared edit to its "
        "ws/bs transitions and rubric drift flags.",
    ),
    "data/targeted_edits_summary.csv": (
        "targeted_edits",
        "primary",
        "One row per edit_id with transition counts, rubric-changed counts, and "
        "all/regressed rubric-friction counts. Renders c04.",
    ),
    "figures/c01_headline_shift.png": (
        "headline",
        "primary",
        "Paired ws/bs full-pass bars at old vs new with overlap-n callout.",
    ),
    "figures/c02_per_eval_transitions.png": (
        "transitions",
        "primary",
        "Per-overlap-eval ws transition strip, hatched on ws_rubric_changed.",
    ),
    "figures/c03_outcome_flow.png": (
        "outcome_flow",
        "primary",
        "Sankey-lite flow from old outcome buckets to new outcome buckets.",
    ),
    "figures/c04_targeted_edits.png": (
        "targeted_edits",
        "primary",
        "Per-edit_id outcome counts on overlap evals; hatched red marks rubric_friction.",
    ),
    "figures/c05_cost_shift_by_transition.png": (
        "cost",
        "secondary",
        "ws token delta per overlap eval, split by ws_transition. Excluded buckets "
        "are labeled in a footer rather than rendered as 'no evals'.",
    ),
    "figures/c06_routing_shift.png": (
        "routing",
        "secondary",
        "Two stacked bar panels: ws required-ref recall delta and required-script recall delta.",
    ),
}


def write_overlap_json(out_data: Path, overlap: OverlapAudit) -> None:
    out_data.joinpath("overlap.json").write_text(json.dumps(overlap, indent=2) + "\n")


def write_outcome_2x2_shift_json(out_data: Path, pairs: list[PerEvalPair]) -> None:
    """4-cell outcome counts at old vs new + 4x4 flow matrix on the joint set.

    Joint set = overlap evals where both ws and bs cells are present in both
    runs (so each eval has a well-defined 4-cell outcome on each side).
    Pairs with any missing cell are reported separately under `excluded` so
    consumers can see how many evals dropped out of the flow analysis.

    The flow matrix is keyed by old outcome -> new outcome with all 16
    combinations always present (zero-filled). Diagonal cells are stable;
    off-diagonal cells drive c03_outcome_flow.png.
    """
    joint = [
        p
        for p in pairs
        if not p["ws_missing_old"]
        and not p["ws_missing_new"]
        and not p["bs_missing_old"]
        and not p["bs_missing_new"]
    ]
    excluded = [p["eval_id"] for p in pairs if p not in joint]

    counts_old = {b: 0 for b in _OUTCOME_BUCKETS}
    counts_new = {b: 0 for b in _OUTCOME_BUCKETS}
    flow: dict[str, dict[str, int]] = {
        old_b: {new_b: 0 for new_b in _OUTCOME_BUCKETS} for old_b in _OUTCOME_BUCKETS
    }
    flow_examples: dict[str, dict[str, list[int]]] = {
        old_b: {new_b: [] for new_b in _OUTCOME_BUCKETS} for old_b in _OUTCOME_BUCKETS
    }
    for p in joint:
        counts_old[p["outcome_old"]] += 1
        counts_new[p["outcome_new"]] += 1
        flow[p["outcome_old"]][p["outcome_new"]] += 1
        flow_examples[p["outcome_old"]][p["outcome_new"]].append(p["eval_id"])

    n = len(joint)
    payload = {
        "n_joint": n,
        "buckets": list(_OUTCOME_BUCKETS),
        "counts_old": counts_old,
        "counts_new": counts_new,
        "deltas": {b: counts_new[b] - counts_old[b] for b in _OUTCOME_BUCKETS},
        "rates_old": _rates(counts_old, n),
        "rates_new": _rates(counts_new, n),
        "flow_matrix": flow,
        "flow_examples": flow_examples,
        "n_stable": sum(flow[b][b] for b in _OUTCOME_BUCKETS),
        "n_changed": n - sum(flow[b][b] for b in _OUTCOME_BUCKETS),
        "excluded_eval_ids": excluded,
        "note": (
            "Joint set requires both ws and bs cells present in both runs. "
            "flow_matrix[old_bucket][new_bucket] counts evals that moved from "
            "old_bucket to new_bucket; diagonal entries are stable."
        ),
    }
    out_data.joinpath("outcome_2x2_shift.json").write_text(
        json.dumps(payload, indent=2) + "\n"
    )


def _rates(counts: dict[str, int], n: int) -> dict[str, float]:
    return {b: round(100 * counts[b] / n, 2) if n else 0.0 for b in _OUTCOME_BUCKETS}


def write_cost_shift_csv(out_data: Path, pairs: list[PerEvalPair]) -> None:
    """Per-overlap-eval token deltas for ws and bs, joined with ws_transition.

    One row per overlap eval. token_delta_* is blank when either side's
    timing.json is absent (the corresponding *_pair_complete flag is false),
    so figure code can filter partial pairs without re-checking missing-cell
    flags. Skipped if there are no overlap pairs.
    """
    if not pairs:
        return
    columns = [
        "eval_id",
        "eval_name",
        "stage",
        "tier",
        "difficulty",
        "ws_transition",
        "bs_transition",
        "ws_pair_complete",
        "tokens_ws_old",
        "tokens_ws_new",
        "token_delta_ws",
        "bs_pair_complete",
        "tokens_bs_old",
        "tokens_bs_new",
        "token_delta_bs",
    ]
    rows: list[dict[str, object]] = []
    for p in pairs:
        ws_complete = p["tokens_ws_old"] is not None and p["tokens_ws_new"] is not None
        bs_complete = p["tokens_bs_old"] is not None and p["tokens_bs_new"] is not None
        rows.append(
            {
                "eval_id": p["eval_id"],
                "eval_name": p["eval_name"],
                "stage": p["stage"],
                "tier": p["tier"],
                "difficulty": p["difficulty"],
                "ws_transition": p["ws_transition"] or "",
                "bs_transition": p["bs_transition"] or "",
                "ws_pair_complete": _b(ws_complete),
                "tokens_ws_old": _maybe_int(p["tokens_ws_old"]),
                "tokens_ws_new": _maybe_int(p["tokens_ws_new"]),
                "token_delta_ws": _delta(p["tokens_ws_old"], p["tokens_ws_new"]),
                "bs_pair_complete": _b(bs_complete),
                "tokens_bs_old": _maybe_int(p["tokens_bs_old"]),
                "tokens_bs_new": _maybe_int(p["tokens_bs_new"]),
                "token_delta_bs": _delta(p["tokens_bs_old"], p["tokens_bs_new"]),
            }
        )
    _write_csv(out_data / "cost_shift.csv", columns, rows)


def write_headline_diff_json(
    out_data: Path,
    overlap: OverlapAudit,
    pairs: list[PerEvalPair],
    old: RunBundle,
    new: RunBundle,
) -> None:
    """Overlap-only headline shift; rubric-sensitive expectation deltas labeled."""
    n = overlap["n_overlap"]
    if n == 0:
        out_data.joinpath("headline_diff.json").write_text(
            json.dumps(_empty_headline(overlap, old, new), indent=2) + "\n"
        )
        return

    ws_pairs = [p for p in pairs if not p["ws_missing_old"] and not p["ws_missing_new"]]
    bs_pairs = [p for p in pairs if not p["bs_missing_old"] and not p["bs_missing_new"]]
    n_ws = len(ws_pairs)
    n_bs = len(bs_pairs)

    ws_rubric_sensitive = any(p["ws_rubric_changed"] for p in pairs)
    bs_rubric_sensitive = any(p["bs_rubric_changed"] for p in pairs)
    n_ws_rubric_changed = sum(1 for p in pairs if p["ws_rubric_changed"])
    n_bs_rubric_changed = sum(1 for p in pairs if p["bs_rubric_changed"])
    n_any_rubric_changed = sum(1 for p in pairs if p["rubric_changed"])

    ws_transitions = Counter(
        p["ws_transition"] for p in pairs if p["ws_transition"] is not None
    )
    bs_transitions = Counter(
        p["bs_transition"] for p in pairs if p["bs_transition"] is not None
    )
    n_ws_discordant = ws_transitions["improved"] + ws_transitions["regressed"]
    p_ws = (
        exact_mcnemar_p(ws_transitions["improved"], ws_transitions["regressed"])
        if n_ws_discordant
        else 1.0
    )

    payload = {
        "overlap_audit": overlap,
        "old_run": _run_block(old),
        "new_run": _run_block(new),
        "rubric_sensitive": {
            "ws": ws_rubric_sensitive,
            "bs": bs_rubric_sensitive,
            "any": ws_rubric_sensitive or bs_rubric_sensitive,
        },
        "n_evals_with_rubric_change": {
            "ws": n_ws_rubric_changed,
            "bs": n_bs_rubric_changed,
            "any": n_any_rubric_changed,
        },
        "missing_cells": _missing_cell_summary(pairs),
        "ws_full_pass": _full_pass_block(ws_pairs, "ws_pass_old", "ws_pass_new", n_ws, n),
        "bs_full_pass": _full_pass_block(bs_pairs, "bs_pass_old", "bs_pass_new", n_bs, n),
        "ws_expectations": _expectation_block(ws_pairs, "ws", ws_rubric_sensitive),
        "bs_expectations": _expectation_block(bs_pairs, "bs", bs_rubric_sensitive),
        "ws_transition_table": _transition_table(ws_transitions),
        "bs_transition_table": _transition_table(bs_transitions),
        "ws_mcnemar": {
            "test": "McNemar (exact, two-sided)",
            "improved": ws_transitions["improved"],
            "regressed": ws_transitions["regressed"],
            "n_discordant": n_ws_discordant,
            "p_value": p_ws,
            "diagnostic_only": True,
            "underpowered": n_ws_discordant < 25,
            "note": (
                "Pairs each overlap eval's ws outcome at old vs new. "
                "Reported diagnostic-only; transition_table is the headline. "
                "Treat p as suggestive when n_discordant < 25."
            ),
        },
        "tokens": _token_coverage_block(pairs),
    }
    out_data.joinpath("headline_diff.json").write_text(json.dumps(payload, indent=2) + "\n")


def write_transitions_csv(out_data: Path, pairs: list[PerEvalPair]) -> None:
    """One row per overlap eval, with all the joinable per-eval columns."""
    columns = [
        "eval_id",
        "eval_name",
        "stage",
        "tier",
        "difficulty",
        "ws_transition",
        "bs_transition",
        "ws_missing_old",
        "ws_missing_new",
        "bs_missing_old",
        "bs_missing_new",
        "ws_pass_old",
        "ws_pass_new",
        "bs_pass_old",
        "bs_pass_new",
        "ws_passed_old",
        "ws_total_old",
        "ws_passed_new",
        "ws_total_new",
        "bs_passed_old",
        "bs_total_old",
        "bs_passed_new",
        "bs_total_new",
        "ws_rubric_changed",
        "bs_rubric_changed",
        "rubric_changed",
        "tokens_ws_old",
        "tokens_ws_new",
        "token_delta_ws",
        "tokens_bs_old",
        "tokens_bs_new",
        "token_delta_bs",
        "outcome_old",
        "outcome_new",
        "failure_type_old",
        "failure_type_new",
        "regression_interpretation",
    ]
    rows: list[dict[str, object]] = []
    for p in pairs:
        rows.append(
            {
                "eval_id": p["eval_id"],
                "eval_name": p["eval_name"],
                "stage": p["stage"],
                "tier": p["tier"],
                "difficulty": p["difficulty"],
                "ws_transition": p["ws_transition"] or "",
                "bs_transition": p["bs_transition"] or "",
                "ws_missing_old": _b(p["ws_missing_old"]),
                "ws_missing_new": _b(p["ws_missing_new"]),
                "bs_missing_old": _b(p["bs_missing_old"]),
                "bs_missing_new": _b(p["bs_missing_new"]),
                "ws_pass_old": _b(p["ws_pass_old"]),
                "ws_pass_new": _b(p["ws_pass_new"]),
                "bs_pass_old": _b(p["bs_pass_old"]),
                "bs_pass_new": _b(p["bs_pass_new"]),
                "ws_passed_old": p["ws_passed_old"],
                "ws_total_old": p["ws_total_old"],
                "ws_passed_new": p["ws_passed_new"],
                "ws_total_new": p["ws_total_new"],
                "bs_passed_old": p["bs_passed_old"],
                "bs_total_old": p["bs_total_old"],
                "bs_passed_new": p["bs_passed_new"],
                "bs_total_new": p["bs_total_new"],
                "ws_rubric_changed": _b(p["ws_rubric_changed"]),
                "bs_rubric_changed": _b(p["bs_rubric_changed"]),
                "rubric_changed": _b(p["rubric_changed"]),
                "tokens_ws_old": _maybe_int(p["tokens_ws_old"]),
                "tokens_ws_new": _maybe_int(p["tokens_ws_new"]),
                "token_delta_ws": _delta(p["tokens_ws_old"], p["tokens_ws_new"]),
                "tokens_bs_old": _maybe_int(p["tokens_bs_old"]),
                "tokens_bs_new": _maybe_int(p["tokens_bs_new"]),
                "token_delta_bs": _delta(p["tokens_bs_old"], p["tokens_bs_new"]),
                "outcome_old": p["outcome_old"],
                "outcome_new": p["outcome_new"],
                "failure_type_old": p["failure_type_old"],
                "failure_type_new": p["failure_type_new"],
                "regression_interpretation": p["regression_interpretation"],
            }
        )
    _write_csv(out_data / "transitions.csv", columns, rows)


def write_targeted_edits_csvs(
    out_data: Path,
    pairs: list[PerEvalPair],
    edit_to_evals: dict[str, list[int]],
) -> None:
    """Many-to-many long table + per-edit summary table.

    Skipped (no files written) when edit_to_evals is empty.
    """
    if not edit_to_evals:
        return

    pair_by_id = {p["eval_id"]: p for p in pairs}

    long_columns = [
        "edit_id",
        "eval_id",
        "eval_name",
        "in_overlap",
        "ws_transition",
        "bs_transition",
        "ws_has_data",
        "bs_has_data",
        "ws_rubric_changed",
        "bs_rubric_changed",
        "regression_interpretation",
    ]
    long_rows: list[dict[str, object]] = []
    for edit_id, eval_ids in edit_to_evals.items():
        for eid in eval_ids:
            p = pair_by_id.get(eid)
            if p is None:
                long_rows.append(
                    {
                        "edit_id": edit_id,
                        "eval_id": eid,
                        "eval_name": "",
                        "in_overlap": "false",
                        "ws_transition": "",
                        "bs_transition": "",
                        "ws_has_data": "",
                        "bs_has_data": "",
                        "ws_rubric_changed": "",
                        "bs_rubric_changed": "",
                        "regression_interpretation": "",
                    }
                )
                continue
            long_rows.append(
                {
                    "edit_id": edit_id,
                    "eval_id": eid,
                    "eval_name": p["eval_name"],
                    "in_overlap": "true",
                    "ws_transition": p["ws_transition"] or "",
                    "bs_transition": p["bs_transition"] or "",
                    "ws_has_data": _b(not p["ws_missing_old"] and not p["ws_missing_new"]),
                    "bs_has_data": _b(not p["bs_missing_old"] and not p["bs_missing_new"]),
                    "ws_rubric_changed": _b(p["ws_rubric_changed"]),
                    "bs_rubric_changed": _b(p["bs_rubric_changed"]),
                    "regression_interpretation": p["regression_interpretation"],
                }
            )
    _write_csv(out_data / "targeted_edits_long.csv", long_columns, long_rows)

    summary_columns = [
        "edit_id",
        "n_evals_declared",
        "n_evals_in_overlap",
        "n_improved",
        "n_regressed",
        "n_stable_pass",
        "n_stable_fail",
        "n_ws_rubric_changed",
        "n_bs_rubric_changed",
        "n_failure_type_rubric_friction",
        "n_regressed_rubric_friction",
        "n_content_regression",
    ]
    summary_rows: list[dict[str, object]] = []
    for edit_id, eval_ids in edit_to_evals.items():
        in_overlap = [pair_by_id[e] for e in eval_ids if e in pair_by_id]
        ws = Counter(p["ws_transition"] for p in in_overlap)
        interp = Counter(p["regression_interpretation"] for p in in_overlap)
        summary_rows.append(
            {
                "edit_id": edit_id,
                "n_evals_declared": len(eval_ids),
                "n_evals_in_overlap": len(in_overlap),
                "n_improved": ws.get("improved", 0),
                "n_regressed": ws.get("regressed", 0),
                "n_stable_pass": ws.get("stable_pass", 0),
                "n_stable_fail": ws.get("stable_fail", 0),
                "n_ws_rubric_changed": sum(
                    1 for p in in_overlap if p["ws_rubric_changed"]
                ),
                "n_bs_rubric_changed": sum(
                    1 for p in in_overlap if p["bs_rubric_changed"]
                ),
                # Any new-run rubric_friction annotation, regardless of transition.
                # Targeted reruns frequently surface rubric friction as stable_fail
                # rather than regressed, so this complements n_regressed_rubric_friction.
                "n_failure_type_rubric_friction": sum(
                    1 for p in in_overlap if p["failure_type_new"] == "rubric_friction"
                ),
                # Strictly regressions (improved→regressed) labeled rubric_friction;
                # subset of n_regressed.
                "n_regressed_rubric_friction": interp.get("rubric_friction", 0),
                "n_content_regression": interp.get("content_regression", 0),
            }
        )
    _write_csv(out_data / "targeted_edits_summary.csv", summary_columns, summary_rows)


def _expectation_block(
    pairs: list[PerEvalPair], cond: str, rubric_sensitive: bool
) -> dict:
    """Aggregate expectation rates over evals where the condition's cell is present in both runs.

    cond is "ws" or "bs"; the function picks the matching count keys.
    """
    p_old_key, t_old_key = f"{cond}_passed_old", f"{cond}_total_old"
    p_new_key, t_new_key = f"{cond}_passed_new", f"{cond}_total_new"
    p_old = sum(p[p_old_key] for p in pairs)
    t_old = sum(p[t_old_key] for p in pairs)
    p_new = sum(p[p_new_key] for p in pairs)
    t_new = sum(p[t_new_key] for p in pairs)
    rate_old = round(100 * p_old / t_old, 2) if t_old else 0.0
    rate_new = round(100 * p_new / t_new, 2) if t_new else 0.0
    return {
        "n_evals": len(pairs),
        "passed_old": p_old,
        "total_old": t_old,
        "rate_old": rate_old,
        "passed_new": p_new,
        "total_new": t_new,
        "rate_new": rate_new,
        "delta_pp": round(rate_new - rate_old, 2),
        "rubric_sensitive": rubric_sensitive,
    }


def _full_pass_block(
    pairs: list[PerEvalPair], pass_old_key: str, pass_new_key: str, n_with_data: int, n_overlap: int
) -> dict:
    """Per-condition full-pass shift over evals where this condition's cell is present in both runs."""
    if n_with_data == 0:
        return {
            "old": 0,
            "new": 0,
            "n_with_data": 0,
            "n_overlap": n_overlap,
            "old_rate": 0.0,
            "new_rate": 0.0,
            "delta_pp": 0.0,
            "complete": False,
        }
    old_pass = sum(1 for p in pairs if p[pass_old_key])
    new_pass = sum(1 for p in pairs if p[pass_new_key])
    old_rate = round(100 * old_pass / n_with_data, 2)
    new_rate = round(100 * new_pass / n_with_data, 2)
    return {
        "old": old_pass,
        "new": new_pass,
        "n_with_data": n_with_data,
        "n_overlap": n_overlap,
        "old_rate": old_rate,
        "new_rate": new_rate,
        "delta_pp": round(new_rate - old_rate, 2),
        "complete": n_with_data == n_overlap,
    }


def _missing_cell_summary(pairs: list[PerEvalPair]) -> dict:
    return {
        "ws_missing_old_eval_ids": [p["eval_id"] for p in pairs if p["ws_missing_old"]],
        "ws_missing_new_eval_ids": [p["eval_id"] for p in pairs if p["ws_missing_new"]],
        "bs_missing_old_eval_ids": [p["eval_id"] for p in pairs if p["bs_missing_old"]],
        "bs_missing_new_eval_ids": [p["eval_id"] for p in pairs if p["bs_missing_new"]],
    }


def _transition_table(transitions: Counter) -> dict[str, int]:
    return {
        "stable_pass": transitions.get("stable_pass", 0),
        "stable_fail": transitions.get("stable_fail", 0),
        "improved": transitions.get("improved", 0),
        "regressed": transitions.get("regressed", 0),
    }


def _run_block(run: RunBundle) -> dict:
    return {
        "run_id": run["run_id"],
        "skill_commit": run["skill_commit"],
        "has_transcripts": run["has_transcripts"],
        "n_evals_total": len(run["per_eval"]),
    }


def _empty_headline(overlap: OverlapAudit, old: RunBundle, new: RunBundle) -> dict:
    return {
        "overlap_audit": overlap,
        "old_run": _run_block(old),
        "new_run": _run_block(new),
        "note": "n_overlap == 0; no comparable evals between these runs.",
    }


def _token_coverage_block(pairs: list[PerEvalPair]) -> dict:
    """Per-condition token totals labeled with available-timing coverage.

    Drops missing rows in the sum but reports n_with_timing and missing
    eval_ids per condition so a partial-coverage delta is never read as a
    direct comparison. delta_*_pct is only emitted when both sides cover
    every overlap eval; otherwise it is None and a `coverage` flag warns.
    """
    n = len(pairs)
    out: dict = {"n_overlap": n}
    for cond_label, key_old, key_new in (
        ("ws", "tokens_ws_old", "tokens_ws_new"),
        ("bs", "tokens_bs_old", "tokens_bs_new"),
    ):
        old_with = [p for p in pairs if p[key_old] is not None]
        new_with = [p for p in pairs if p[key_new] is not None]
        old_total = sum(p[key_old] for p in old_with)
        new_total = sum(p[key_new] for p in new_with)
        complete = len(old_with) == n and len(new_with) == n
        out[cond_label] = {
            "old_total": old_total,
            "new_total": new_total,
            "n_with_timing_old": len(old_with),
            "n_with_timing_new": len(new_with),
            "missing_old_eval_ids": [p["eval_id"] for p in pairs if p[key_old] is None],
            "missing_new_eval_ids": [p["eval_id"] for p in pairs if p[key_new] is None],
            "complete": complete,
            "delta_total": (new_total - old_total) if complete else None,
            "note": (
                "Direct delta over all overlap evals."
                if complete
                else "available-timing-only; delta omitted because at least one "
                "eval has missing timing.json on one side"
            ),
        }
    return out


def _delta(old, new) -> int | str:
    if old is None or new is None:
        return ""
    return new - old


def _b(value: bool) -> str:
    return "true" if value else "false"


def _maybe_int(value) -> int | str:
    return "" if value is None else value


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    path.write_text(buf.getvalue())


def write_routing_shift_csv(
    out_data: Path,
    pairs: list[PerEvalPair],
    old_routing: dict[tuple[int, str], TranscriptRecord],
    new_routing: dict[tuple[int, str], TranscriptRecord],
    expected_refs: ExpectedResources,
    expected_scripts: ExpectedResources,
    *,
    old_has_transcripts: bool,
    new_has_transcripts: bool,
) -> None:
    """Routing shift per overlap eval and condition.

    One row per (eval_id, condition) pair, with required-ref recall,
    required-script recall, and unexpected-resource counts at old vs new.

    Definitions (eval-level expectations come from the new run's
    evals_snapshot.json by default):
      required_ref_recall   = required_refs_opened / max(required_total, 1)
      required_script_recall = required_scripts_executed / max(required_total, 1)
      unexpected_ref_count  = opened refs not in required ∪ optional
      unexpected_script_count = executed scripts not in required ∪ optional

    Skipped (no file written) when either run is missing transcripts. Rows
    where one side has no transcript record carry routing_complete=false and
    blank deltas so figure code can filter on the flag.
    """
    if not (old_has_transcripts and new_has_transcripts):
        return
    if not pairs:
        return

    columns = [
        "eval_id",
        "eval_name",
        "stage",
        "tier",
        "condition",
        "routing_complete",
        "n_required_refs",
        "n_optional_refs",
        "has_required_refs",
        "required_ref_recall_old",
        "required_ref_recall_new",
        "required_ref_recall_delta",
        "unexpected_ref_count_old",
        "unexpected_ref_count_new",
        "unexpected_ref_count_delta",
        "n_required_scripts",
        "n_optional_scripts",
        "has_required_scripts",
        "required_script_recall_old",
        "required_script_recall_new",
        "required_script_recall_delta",
        "unexpected_script_count_old",
        "unexpected_script_count_new",
        "unexpected_script_count_delta",
    ]
    rows: list[dict[str, object]] = []
    for p in pairs:
        eid = p["eval_id"]
        ref_block = expected_refs.get(eid, {"required": [], "optional": [], "distractor": []})
        script_block = expected_scripts.get(
            eid, {"required": [], "optional": [], "distractor": []}
        )
        for cond in ("with_skill", "without_skill"):
            old_rec = old_routing.get((eid, cond))
            new_rec = new_routing.get((eid, cond))
            complete = old_rec is not None and new_rec is not None
            ref_old = _routing_metrics(old_rec, ref_block, "ref_opens") if old_rec else None
            ref_new = _routing_metrics(new_rec, ref_block, "ref_opens") if new_rec else None
            script_old = (
                _routing_metrics(old_rec, script_block, "script_executions")
                if old_rec
                else None
            )
            script_new = (
                _routing_metrics(new_rec, script_block, "script_executions")
                if new_rec
                else None
            )
            rows.append(
                {
                    "eval_id": eid,
                    "eval_name": p["eval_name"],
                    "stage": p["stage"],
                    "tier": p["tier"],
                    "condition": cond,
                    "routing_complete": _b(complete),
                    "n_required_refs": len(ref_block["required"]),
                    "n_optional_refs": len(ref_block["optional"]),
                    "has_required_refs": _b(bool(ref_block["required"])),
                    "required_ref_recall_old": _fmt_recall(ref_old, "recall"),
                    "required_ref_recall_new": _fmt_recall(ref_new, "recall"),
                    "required_ref_recall_delta": _fmt_delta(ref_old, ref_new, "recall"),
                    "unexpected_ref_count_old": _fmt_count(ref_old, "unexpected"),
                    "unexpected_ref_count_new": _fmt_count(ref_new, "unexpected"),
                    "unexpected_ref_count_delta": _fmt_delta(ref_old, ref_new, "unexpected"),
                    "n_required_scripts": len(script_block["required"]),
                    "n_optional_scripts": len(script_block["optional"]),
                    "has_required_scripts": _b(bool(script_block["required"])),
                    "required_script_recall_old": _fmt_recall(script_old, "recall"),
                    "required_script_recall_new": _fmt_recall(script_new, "recall"),
                    "required_script_recall_delta": _fmt_delta(
                        script_old, script_new, "recall"
                    ),
                    "unexpected_script_count_old": _fmt_count(script_old, "unexpected"),
                    "unexpected_script_count_new": _fmt_count(script_new, "unexpected"),
                    "unexpected_script_count_delta": _fmt_delta(
                        script_old, script_new, "unexpected"
                    ),
                }
            )
    _write_csv(out_data / "routing_shift.csv", columns, rows)


def _routing_metrics(
    record: TranscriptRecord | None,
    block: Mapping[str, list[str]],
    counter_key: str,
) -> dict[str, float | int] | None:
    """Compute (recall, n_opened_required, unexpected_count) for one cell.

    counter_key is "ref_opens" or "script_executions"; both are Counter[str]
    keyed by resource name. Recall is over the required set with denominator
    max(len(required), 1); unexpected count is opens/executions on names not
    in required ∪ optional.
    """
    if record is None:
        return None
    counter = record.get(counter_key)
    if counter is None:
        return {"recall": 0.0, "n_opened_required": 0, "unexpected": 0}
    required = list(block.get("required", []))
    optional = list(block.get("optional", []))
    expected_set = set(required) | set(optional)
    n_required_opened = sum(1 for r in required if counter.get(r, 0) > 0)
    recall = n_required_opened / max(len(required), 1)
    unexpected = sum(1 for name in counter if name not in expected_set and counter[name] > 0)
    return {
        "recall": round(recall, 4),
        "n_opened_required": n_required_opened,
        "unexpected": unexpected,
    }


def _fmt_recall(metrics: dict | None, key: str) -> object:
    if metrics is None:
        return ""
    return metrics[key]


def _fmt_count(metrics: dict | None, key: str) -> object:
    if metrics is None:
        return ""
    return metrics[key]


def _fmt_delta(old: dict | None, new: dict | None, key: str) -> object:
    if old is None or new is None:
        return ""
    diff = new[key] - old[key]
    if isinstance(diff, float):
        return round(diff, 4)
    return diff


def write_comparison_manifest_json(
    out_dir: Path,
    staged_data: Path,
    staged_figures: Path,
    overlap: OverlapAudit,
    old: RunBundle,
    new: RunBundle,
) -> None:
    """Write a manifest entry per generated comparison output.

    Each entry has filename, family, priority, purpose, and
    classification_source ("override" when matched to
    COMPARISON_MANIFEST_OVERRIDES, else "fallback"). Falls back to appendix
    classification for outputs not yet declared and prints those filenames
    so they can be promoted deliberately. Reads the staging dirs so the
    manifest reflects what was actually written this run.
    """
    filenames: set[str] = {"INDEX.md"}
    if staged_data.is_dir():
        filenames.update(f"data/{p.name}" for p in staged_data.iterdir() if p.is_file())
    if staged_figures.is_dir():
        filenames.update(
            f"figures/{p.name}" for p in staged_figures.iterdir() if p.is_file()
        )
    filenames.add("data/comparison_manifest.json")

    manifest: list[dict[str, object]] = []
    fallback_files: list[str] = []
    for filename in sorted(filenames):
        override = COMPARISON_MANIFEST_OVERRIDES.get(filename)
        if override is not None:
            family, priority, purpose = override
            classification_source = "override"
        else:
            family, priority, purpose = (
                "appendix",
                "appendix",
                "Comparison artifact not yet classified.",
            )
            classification_source = "fallback"
            fallback_files.append(filename)
        manifest.append(
            {
                "filename": filename,
                "family": family,
                "priority": priority,
                "purpose": purpose,
                "classification_source": classification_source,
            }
        )

    payload = {
        "old_run": _run_block(old),
        "new_run": _run_block(new),
        "overlap_audit": overlap,
        "outputs": manifest,
    }
    (staged_data / "comparison_manifest.json").write_text(json.dumps(payload, indent=2) + "\n")
    _write_comparison_index_md(out_dir, manifest, overlap, old, new)
    if fallback_files:
        print("Comparison manifest fallbacks:", ", ".join(fallback_files))


def _write_comparison_index_md(
    out_dir: Path,
    manifest: list[dict[str, object]],
    overlap: OverlapAudit,
    old: RunBundle,
    new: RunBundle,
) -> None:
    """Render INDEX.md to the staged location (committed atomically by caller).

    Writes to out_dir/.INDEX.tmp so commit_staged_outputs can rename it to
    out_dir/INDEX.md alongside data/ and figures/. Groups outputs by priority
    and includes the overlap audit + sample-size caveat at the top.
    """
    n = overlap["n_overlap"]
    underpowered = n < 25
    lines = [
        f"# Comparison: {old['run_id']} → {new['run_id']}",
        "",
        f"- old_run: `{old['run_id']}` (skill_commit `{old['skill_commit']}`, "
        f"n_evals={overlap['old_total']})",
        f"- new_run: `{new['run_id']}` (skill_commit `{new['skill_commit']}`, "
        f"n_evals={overlap['new_total']})",
        f"- n_overlap: **{n}**"
        + ("  *(underpowered for global significance; treat headline McNemar p as diagnostic only)*"
           if underpowered else ""),
    ]
    if overlap["old_only"]:
        lines.append(f"- old_only eval_ids ({len(overlap['old_only'])}): not in new run")
    if overlap["new_only"]:
        lines.append(f"- new_only eval_ids ({len(overlap['new_only'])}): not in old run")
    lines.extend(
        [
            "",
            "Read [`data/overlap.json`](data/overlap.json) first to confirm exactly "
            "what was compared. Then read [`data/headline_diff.json`](data/headline_diff.json) "
            "for the overlap-only shift, and [`data/transitions.csv`](data/transitions.csv) "
            "for the per-eval moves with rubric-drift and regression-interpretation columns.",
            "",
        ]
    )

    priority_order = {"primary": 0, "secondary": 1, "appendix": 2}
    rows = sorted(
        manifest,
        key=lambda r: (
            priority_order.get(str(r["priority"]), 99),
            str(r["family"]),
            str(r["filename"]),
        ),
    )
    for priority in ("primary", "secondary", "appendix"):
        priority_rows = [r for r in rows if r["priority"] == priority]
        if not priority_rows:
            continue
        lines.extend([f"## {priority.title()} Outputs", ""])
        for row in priority_rows:
            filename = str(row["filename"])
            lines.append(
                f"- [`{filename}`]({filename}) — {row['family']}: {row['purpose']}"
            )
        lines.append("")
    (out_dir / ".INDEX.tmp").write_text("\n".join(lines).rstrip() + "\n")
