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
    "data/provenance_diff.json": (
        "audit",
        "primary",
        "Skill / src / model / harness / prompt-template / evals-catalog drift "
        "between runs. causal_changed=true is the attribution warning; "
        "metadata_changed=true flags label-only differences (round_label / "
        "skill_branch) that do not undermine attribution.",
    ),
    "data/catalog_diff.json": (
        "audit",
        "primary",
        "Per-eval diff of evals_snapshot.json: added/removed evals plus "
        "field-level changes for name / eval_name / stage / tier / difficulty / "
        "prompt / expected_output / expectations / assertions / files / "
        "expected_refs / expected_scripts. Required reading when provenance_diff "
        "shows the causal evals_catalog_semantic_sha256 drifted.",
    ),
    "figures/c08_did_skill_lift_change.png": (
        "headline",
        "primary",
        "Skill-lift (ws_pass_rate - bs_pass_rate) at old vs new with the "
        "delta and 95% bootstrap CIs. Headline answer to 'did the skill "
        "help differently between commits?'",
    ),
    "data/category_shift.csv": (
        "category",
        "secondary",
        "Per-(stage, tier) ws + bs full-pass rates and ws transition counts at "
        "old vs new with rollups. Answers 'did stage X improve while tier Y regressed?'",
    ),
    "data/regression_review.csv": (
        "fix_priority",
        "primary",
        "Drill-down for ws regressions and rubric_friction stable_fails: paths to "
        "old/new response.md and grading.json so reviewers can open both side-by-side.",
    ),
    "figures/c07_where_does_category_drift.png": (
        "category",
        "secondary",
        "Heatmap of ws full-pass rate delta by stage x tier; n/a cells "
        "indicate no overlap evals with both ws cells present.",
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
    "figures/c01_did_the_headline_improve.png": (
        "headline",
        "primary",
        "Paired ws/bs full-pass bars at old vs new with overlap-n callout.",
    ),
    "figures/c02_did_outcomes_move_per_eval.png": (
        "transitions",
        "primary",
        "Per-overlap-eval ws transition strip, hatched on ws_rubric_changed.",
    ),
    "figures/c03_where_did_evals_move_in_2x2.png": (
        "outcome_flow",
        "primary",
        "Sankey-lite flow from old outcome buckets to new outcome buckets.",
    ),
    "figures/c04_did_targeted_edits_explain_movement.png": (
        "targeted_edits",
        "primary",
        "Per-edit_id outcome counts on overlap evals; hatched red marks rubric_friction.",
    ),
    "figures/c05_did_improvements_cost_more.png": (
        "cost",
        "secondary",
        "ws token delta per overlap eval, split by ws_transition. Excluded buckets "
        "are labeled in a footer rather than rendered as 'no evals'.",
    ),
    "figures/c06_did_routing_change.png": (
        "routing",
        "secondary",
        "Two stacked bar panels: ws required-ref recall delta and required-script recall delta.",
    ),
}


def write_overlap_json(out_data: Path, overlap: OverlapAudit) -> None:
    out_data.joinpath("overlap.json").write_text(json.dumps(overlap, indent=2) + "\n")


def write_category_shift_csv(out_data: Path, pairs: list[PerEvalPair]) -> None:
    """Per-(stage, tier) ws + bs aggregate at old vs new on overlap evals.

    Aggregates each overlap eval by its (stage, tier) bucket and reports
    per-bucket counts of: total evals, ws full pass at old vs new, ws
    full-pass-rate delta, ws transition counts, and rubric-changed counts.
    Cells where the corresponding condition is missing on either side are
    excluded from that condition's full-pass count and tracked in
    n_ws_with_data / n_bs_with_data so a partial dispatch does not
    silently shrink the bucket.

    For larger reruns this answers "did stage X improve while tier Y
    regressed?" without leaving readers to reaggregate transitions.csv.
    Also includes overall (stage="*", tier="*") roll-up rows.
    """
    if not pairs:
        return

    grouped: dict[tuple[str, str], list[PerEvalPair]] = {}
    for p in pairs:
        grouped.setdefault((p["stage"], p["tier"]), []).append(p)
    # Roll-ups: per stage with tier="*", per tier with stage="*", and overall.
    by_stage: dict[str, list[PerEvalPair]] = {}
    by_tier: dict[str, list[PerEvalPair]] = {}
    for p in pairs:
        by_stage.setdefault(p["stage"], []).append(p)
        by_tier.setdefault(p["tier"], []).append(p)
    rollups: dict[tuple[str, str], list[PerEvalPair]] = {}
    for stage, plist in by_stage.items():
        rollups[(stage, "*")] = plist
    for tier, plist in by_tier.items():
        rollups[("*", tier)] = plist
    rollups[("*", "*")] = list(pairs)

    columns = [
        "stage",
        "tier",
        "scope",
        "n_evals",
        "n_ws_with_data",
        "ws_pass_old",
        "ws_pass_new",
        "ws_rate_old",
        "ws_rate_new",
        "ws_delta_pp",
        "n_bs_with_data",
        "bs_pass_old",
        "bs_pass_new",
        "bs_rate_old",
        "bs_rate_new",
        "bs_delta_pp",
        "n_improved",
        "n_regressed",
        "n_stable_pass",
        "n_stable_fail",
        "n_ws_rubric_changed",
        "n_bs_rubric_changed",
    ]
    rows: list[dict[str, object]] = []
    for (stage, tier), plist in sorted(grouped.items()):
        rows.append(_category_row(stage, tier, plist, scope="cell"))
    for (stage, tier), plist in sorted(rollups.items()):
        rows.append(_category_row(stage, tier, plist, scope="rollup"))
    _write_csv(out_data / "category_shift.csv", columns, rows)


def _category_row(
    stage: str, tier: str, plist: list[PerEvalPair], *, scope: str
) -> dict[str, object]:
    """Compute one category_shift.csv row."""
    ws_with = [p for p in plist if not p["ws_missing_old"] and not p["ws_missing_new"]]
    bs_with = [p for p in plist if not p["bs_missing_old"] and not p["bs_missing_new"]]
    ws_old = sum(1 for p in ws_with if p["ws_pass_old"])
    ws_new = sum(1 for p in ws_with if p["ws_pass_new"])
    bs_old = sum(1 for p in bs_with if p["bs_pass_old"])
    bs_new = sum(1 for p in bs_with if p["bs_pass_new"])
    ws_rate_old = round(100 * ws_old / len(ws_with), 2) if ws_with else 0.0
    ws_rate_new = round(100 * ws_new / len(ws_with), 2) if ws_with else 0.0
    bs_rate_old = round(100 * bs_old / len(bs_with), 2) if bs_with else 0.0
    bs_rate_new = round(100 * bs_new / len(bs_with), 2) if bs_with else 0.0
    transitions = Counter(
        p["ws_transition"] for p in plist if p["ws_transition"] is not None
    )
    return {
        "stage": stage,
        "tier": tier,
        "scope": scope,
        "n_evals": len(plist),
        "n_ws_with_data": len(ws_with),
        "ws_pass_old": ws_old,
        "ws_pass_new": ws_new,
        "ws_rate_old": ws_rate_old,
        "ws_rate_new": ws_rate_new,
        "ws_delta_pp": round(ws_rate_new - ws_rate_old, 2),
        "n_bs_with_data": len(bs_with),
        "bs_pass_old": bs_old,
        "bs_pass_new": bs_new,
        "bs_rate_old": bs_rate_old,
        "bs_rate_new": bs_rate_new,
        "bs_delta_pp": round(bs_rate_new - bs_rate_old, 2),
        "n_improved": transitions.get("improved", 0),
        "n_regressed": transitions.get("regressed", 0),
        "n_stable_pass": transitions.get("stable_pass", 0),
        "n_stable_fail": transitions.get("stable_fail", 0),
        "n_ws_rubric_changed": sum(1 for p in plist if p["ws_rubric_changed"]),
        "n_bs_rubric_changed": sum(1 for p in plist if p["bs_rubric_changed"]),
    }


def write_regression_review_csv(
    out_data: Path,
    pairs: list[PerEvalPair],
    old: RunBundle,
    new: RunBundle,
) -> None:
    """Drill-down CSV: one row per ws-regressed or rubric_friction-labeled eval.

    Columns include the regression_interpretation, ws/bs transitions, ws
    token + duration deltas (when timing is complete), and concrete
    relative paths to the old and new ``response.md`` and ``grading.json``
    so a reviewer can open the artifacts for both runs side by side.

    Skipped if no overlap eval needs review.
    """
    review_rows: list[dict[str, object]] = []
    for p in pairs:
        if not (
            p["ws_transition"] == "regressed"
            or p["failure_type_new"] == "rubric_friction"
        ):
            continue
        review_rows.append(
            {
                "eval_id": p["eval_id"],
                "eval_name": p["eval_name"],
                "stage": p["stage"],
                "tier": p["tier"],
                "ws_transition": p["ws_transition"] or "",
                "bs_transition": p["bs_transition"] or "",
                "regression_interpretation": p["regression_interpretation"],
                "failure_type_old": p["failure_type_old"],
                "failure_type_new": p["failure_type_new"],
                "ws_rubric_changed": _b(p["ws_rubric_changed"]),
                "bs_rubric_changed": _b(p["bs_rubric_changed"]),
                "ws_passed_old": p["ws_passed_old"],
                "ws_total_old": p["ws_total_old"],
                "ws_passed_new": p["ws_passed_new"],
                "ws_total_new": p["ws_total_new"],
                "token_delta_ws": _delta(p["tokens_ws_old"], p["tokens_ws_new"]),
                "duration_delta_ws": _delta_round(
                    p["duration_ws_old"], p["duration_ws_new"], 1
                ),
                "old_response_path": _eval_artifact_path(old, p, "with_skill", "outputs/response.md"),
                "new_response_path": _eval_artifact_path(new, p, "with_skill", "outputs/response.md"),
                "old_grading_path": _eval_artifact_path(old, p, "with_skill", "grading.json"),
                "new_grading_path": _eval_artifact_path(new, p, "with_skill", "grading.json"),
            }
        )
    if not review_rows:
        return
    columns = list(review_rows[0].keys())
    _write_csv(out_data / "regression_review.csv", columns, review_rows)


def _eval_artifact_path(
    bundle: RunBundle, pair: PerEvalPair, condition: str, suffix: str
) -> str:
    """Return a path to an artifact like outputs/response.md, or "" if absent.

    Looks under each iteration-N/ for an ``eval-{eid:03d}-{name}/{cond}/{suffix}``
    file. Returns the first match as a path *relative to the workspace
    root* so the comparison output stays stable regardless of where it
    was generated. Returns "" when nothing matches (e.g. partial dispatch).
    """
    eid = pair["eval_id"]
    workspace_root = bundle["run_dir"].parent.parent  # repo root or absolute parent
    for batch in bundle["batch_order"]:
        for cand in (bundle["run_dir"] / f"iteration-{batch}").glob(f"eval-{eid:03d}-*"):
            target = cand / condition / suffix
            if target.is_file():
                try:
                    return str(target.relative_to(workspace_root))
                except ValueError:
                    return str(target)
    return ""


def write_catalog_diff_json(
    out_data: Path,
    old_catalog: dict[int, dict],
    new_catalog: dict[int, dict],
) -> None:
    """Per-eval diff of evals_snapshot.json between two runs.

    Surfaces what *specifically* changed when provenance_diff.json reports
    that the evals_snapshot hash drifted. Reports added / removed / changed
    eval ids and per-eval field changes for: name, stage, tier, difficulty,
    expectations text + count, expected_refs (required/optional/distractor),
    expected_scripts. Skipped (no file written) when both catalogs are empty.
    """
    if not old_catalog and not new_catalog:
        return
    old_ids = set(old_catalog)
    new_ids = set(new_catalog)
    added = sorted(new_ids - old_ids)
    removed = sorted(old_ids - new_ids)
    common = sorted(old_ids & new_ids)

    changed: list[dict[str, object]] = []
    unchanged_count = 0
    for eid in common:
        diff = _eval_field_diff(old_catalog[eid], new_catalog[eid])
        if diff["fields_changed"]:
            diff["eval_id"] = eid
            changed.append(diff)
        else:
            unchanged_count += 1

    payload = {
        "old_catalog_loaded": bool(old_catalog),
        "new_catalog_loaded": bool(new_catalog),
        "old_evals_total": len(old_catalog),
        "new_evals_total": len(new_catalog),
        "n_added": len(added),
        "n_removed": len(removed),
        "n_changed": len(changed),
        "n_unchanged": unchanged_count,
        "added_eval_ids": added,
        "removed_eval_ids": removed,
        "changed_evals": changed,
        "note": (
            "Per-eval diff of evals_snapshot.json. fields_changed lists "
            "the field names that differ between old and new; the *_old "
            "and *_new keys carry the actual values for each. expectations_count "
            "tracks rubric-size changes; expectations_text_changed indicates "
            "any expectation text differs (rubric content edits)."
        ),
    }
    out_data.joinpath("catalog_diff.json").write_text(json.dumps(payload, indent=2) + "\n")


def _eval_field_diff(old: dict, new: dict) -> dict[str, object]:
    """Compare two eval-catalog entries; return a dict of field-level diffs.

    Returns {"fields_changed": [...], plus per-field <field>_old/<field>_new
    pairs for each changed field}. Only fields that differ appear.
    """
    diff: dict[str, object] = {"fields_changed": []}
    fields_changed: list[str] = diff["fields_changed"]  # type: ignore[assignment]

    # Scalar text fields the catalog declares per eval. Includes prompt and
    # expected_output so a silent prompt edit or expected-answer change is
    # visible. Handle both `name` (older) and `eval_name` (current) shapes.
    scalar_fields = (
        "name",
        "eval_name",
        "stage",
        "tier",
        "difficulty",
        "prompt",
        "expected_output",
    )
    for key in scalar_fields:
        old_val = old.get(key)
        new_val = new.get(key)
        if old_val != new_val:
            fields_changed.append(key)
            diff[f"{key}_old"] = old_val
            diff[f"{key}_new"] = new_val

    old_exp = list(old.get("expectations", []) or [])
    new_exp = list(new.get("expectations", []) or [])
    if len(old_exp) != len(new_exp):
        fields_changed.append("expectations_count")
        diff["expectations_count_old"] = len(old_exp)
        diff["expectations_count_new"] = len(new_exp)
    old_texts = sorted(_expectation_text(e) for e in old_exp)
    new_texts = sorted(_expectation_text(e) for e in new_exp)
    if old_texts != new_texts:
        if "expectations_count" not in fields_changed:
            fields_changed.append("expectations_text")
        diff["expectations_added"] = sorted(set(new_texts) - set(old_texts))
        diff["expectations_removed"] = sorted(set(old_texts) - set(new_texts))

    # List or dict-of-lists fields. The real catalog shape stores assertions
    # as ``{"required_substrings": [...], "forbidden_substrings": [...],
    # "behavioral_checks": [...]}`` rather than a flat list, so we must walk
    # dict keys per-sub-list. files is a flat list of strings in the
    # observed shape but the same code path handles both.
    for list_field in ("assertions", "files"):
        old_val = old.get(list_field)
        new_val = new.get(list_field)
        for sub_field, old_items, new_items in _enumerate_listish_subfields(
            list_field, old_val, new_val
        ):
            if old_items == new_items:
                continue
            fields_changed.append(sub_field)
            diff[f"{sub_field}_added"] = sorted(set(new_items) - set(old_items))
            diff[f"{sub_field}_removed"] = sorted(set(old_items) - set(new_items))
            if len(old_items) != len(new_items):
                diff[f"{sub_field}_count_old"] = len(old_items)
                diff[f"{sub_field}_count_new"] = len(new_items)

    for kind in ("expected_refs", "expected_scripts"):
        old_block = old.get(kind) or {}
        new_block = new.get(kind) or {}
        for slot in ("required", "optional", "distractor"):
            old_set = set(old_block.get(slot, []) or [])
            new_set = set(new_block.get(slot, []) or [])
            if old_set != new_set:
                field = f"{kind}.{slot}"
                fields_changed.append(field)
                diff[f"{field}_added"] = sorted(new_set - old_set)
                diff[f"{field}_removed"] = sorted(old_set - new_set)
    return diff


def _canonical_list_texts(values: object) -> list[str]:
    """Render a list of strings or dicts to a stable list of text representations.

    Output is sorted so order-only differences do not surface as catalog
    drift. This must stay in lockstep with _canonical_list in _compare_io.py
    so the diff and the semantic hash agree on what counts as a change.
    """
    if not isinstance(values, list):
        return []
    out = []
    for v in values:
        if isinstance(v, dict):
            out.append(json.dumps(v, sort_keys=True, ensure_ascii=False))
        else:
            out.append(str(v))
    out.sort()
    return out


def _enumerate_listish_subfields(
    field: str, old: object, new: object
) -> list[tuple[str, list[str], list[str]]]:
    """Yield (label, old_items, new_items) tuples for a list- or dict-shaped field.

    For a flat list (``files``) emits a single tuple with label = ``field``.
    For a dict-of-lists (``assertions = {"required_substrings": [...], ...}``)
    emits one tuple per sub-key with label = ``f"{field}.{subkey}"``. Sub-keys
    that exist on only one side still surface as a tuple so the writer can
    record them as added/removed. Non-list, non-dict inputs degrade to an
    empty single-tuple emission.
    """
    if isinstance(old, dict) or isinstance(new, dict):
        old_dict = old if isinstance(old, dict) else {}
        new_dict = new if isinstance(new, dict) else {}
        keys = sorted({str(k) for k in old_dict} | {str(k) for k in new_dict})
        return [
            (
                f"{field}.{k}",
                _canonical_list_texts(old_dict.get(k) or []),
                _canonical_list_texts(new_dict.get(k) or []),
            )
            for k in keys
        ]
    return [
        (
            field,
            _canonical_list_texts(old or []),
            _canonical_list_texts(new or []),
        )
    ]


def _expectation_text(expectation: object) -> str:
    """Best-effort string representation of one expectation row.

    Round-c shape is `{text, kind, ...}`; round-d uses similar.
    Falls back to repr() when the shape is unrecognized.
    """
    if isinstance(expectation, dict):
        text = expectation.get("text")
        if isinstance(text, str):
            return text
        return json.dumps(expectation, sort_keys=True)
    return repr(expectation)


def write_provenance_diff_json(out_data: Path, old: RunBundle, new: RunBundle) -> None:
    """Emit a provenance comparison so silent skill / catalog / model drift is visible.

    Fields are split into two buckets:
    - causal: things whose change can plausibly move headline / transition
      deltas (skill commit, src commit, model, harness, prompt template,
      evals catalog hash).
    - metadata: things that change naturally between runs without affecting
      what was measured (round_label, branch).

    Each field reports old, new, and changed (true when the strings differ
    and both are non-empty). Top-level `causal_changed` summarizes only the
    causal bucket — that's the flag readers should consult before
    attributing headline shifts to skill changes. `metadata_changed` is
    surfaced separately so label-only differences are visible without
    triggering attribution warnings.
    """
    causal_fields = [
        "skill_commit_at_sweep_end",
        "skill_commit_at_sweep_start",
        "spyglass_src_commit",
        "model",
        "harness",
        "dispatch_prompt_template",
        # Hash of the canonical *semantic* representation of the evals catalog
        # (id / name / stage / tier / difficulty / expectations / expected
        # refs+scripts), stable under wrapper / formatting noise. Drift here
        # corresponds to real eval changes — see catalog_diff.json for the
        # added / removed / changed eval ids and field-level deltas.
        "evals_catalog_semantic_sha256",
    ]
    # Metadata-only: round_label / skill_branch are labels; the raw snapshot
    # bytes hash flips on reformatting / source-path changes that do NOT
    # correspond to actual eval drift, so it stays out of causal_changed.
    metadata_fields = ["skill_branch", "round_label", "evals_snapshot_sha256_raw"]
    rows: dict[str, dict[str, object]] = {}
    causal_changed = False
    metadata_changed = False
    for field in causal_fields + metadata_fields:
        old_v = old["provenance"].get(field, "")
        new_v = new["provenance"].get(field, "")
        changed = bool(old_v) and bool(new_v) and old_v != new_v
        kind = "causal" if field in causal_fields else "metadata"
        rows[field] = {"old": old_v, "new": new_v, "changed": changed, "kind": kind}
        if changed and kind == "causal":
            causal_changed = True
        if changed and kind == "metadata":
            metadata_changed = True
    payload = {
        "old_run_id": old["run_id"],
        "new_run_id": new["run_id"],
        "fields": rows,
        "causal_changed": causal_changed,
        "metadata_changed": metadata_changed,
        "note": (
            "causal_changed=true means at least one dimension that can "
            "plausibly shift headline / transition deltas (skill, src, "
            "model, harness, prompt template, evals catalog) differs "
            "between runs; treat headline shifts skeptically. "
            "metadata_changed=true reflects label-only differences "
            "(round_label, skill_branch) and does NOT undermine "
            "attribution by itself."
        ),
    }
    out_data.joinpath("provenance_diff.json").write_text(json.dumps(payload, indent=2) + "\n")


def write_outcome_2x2_shift_json(out_data: Path, pairs: list[PerEvalPair]) -> None:
    """4-cell outcome counts at old vs new + 4x4 flow matrix on the joint set.

    Joint set = overlap evals where both ws and bs cells are present in both
    runs (so each eval has a well-defined 4-cell outcome on each side).
    Pairs with any missing cell are reported separately under `excluded` so
    consumers can see how many evals dropped out of the flow analysis.

    The flow matrix is keyed by old outcome -> new outcome with all 16
    combinations always present (zero-filled). Diagonal cells are stable;
    off-diagonal cells drive c03_where_did_evals_move_in_2x2.png.
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
    """Per-overlap-eval token + duration deltas for ws and bs, joined with ws_transition.

    One row per overlap eval. token_delta_* / duration_delta_* are blank
    when either side's timing.json is absent or the corresponding fields
    are missing; the *_pair_complete flag tracks token-pair completeness
    so cost-by-transition figures can filter without re-checking
    missing-cell flags. duration_*_pair_complete is tracked separately
    because round-c-era timing.json predates the duration field.
    Skipped if there are no overlap pairs.
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
        "ws_duration_pair_complete",
        "duration_ws_old",
        "duration_ws_new",
        "duration_delta_ws",
        "bs_duration_pair_complete",
        "duration_bs_old",
        "duration_bs_new",
        "duration_delta_bs",
    ]
    rows: list[dict[str, object]] = []
    for p in pairs:
        ws_complete = p["tokens_ws_old"] is not None and p["tokens_ws_new"] is not None
        bs_complete = p["tokens_bs_old"] is not None and p["tokens_bs_new"] is not None
        ws_dur_complete = p["duration_ws_old"] is not None and p["duration_ws_new"] is not None
        bs_dur_complete = p["duration_bs_old"] is not None and p["duration_bs_new"] is not None
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
                "ws_duration_pair_complete": _b(ws_dur_complete),
                "duration_ws_old": _maybe_round(p["duration_ws_old"], 1),
                "duration_ws_new": _maybe_round(p["duration_ws_new"], 1),
                "duration_delta_ws": _delta_round(
                    p["duration_ws_old"], p["duration_ws_new"], 1
                ),
                "bs_duration_pair_complete": _b(bs_dur_complete),
                "duration_bs_old": _maybe_round(p["duration_bs_old"], 1),
                "duration_bs_new": _maybe_round(p["duration_bs_new"], 1),
                "duration_delta_bs": _delta_round(
                    p["duration_bs_old"], p["duration_bs_new"], 1
                ),
            }
        )
    _write_csv(out_data / "cost_shift.csv", columns, rows)


def _maybe_round(value, ndigits: int):
    return "" if value is None else round(value, ndigits)


def _delta_round(old, new, ndigits: int):
    if old is None or new is None:
        return ""
    return round(new - old, ndigits)


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
    # Joint pairs: all 4 cells present (ws old, ws new, bs old, bs new). This
    # is the set used for skill-lift shift so old and new lifts share a
    # denominator and are directly comparable.
    joint_pairs = [
        p
        for p in pairs
        if not p["ws_missing_old"]
        and not p["ws_missing_new"]
        and not p["bs_missing_old"]
        and not p["bs_missing_new"]
    ]
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
        "skill_lift": _skill_lift_block(joint_pairs, n_overlap=n),
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
    old_vec = [int(bool(p[pass_old_key])) for p in pairs]
    new_vec = [int(bool(p[pass_new_key])) for p in pairs]
    old_pass = sum(old_vec)
    new_pass = sum(new_vec)
    old_rate = round(100 * old_pass / n_with_data, 2)
    new_rate = round(100 * new_pass / n_with_data, 2)
    # Paired bootstrap CIs: resample evals with replacement, recompute the
    # rate or delta on the resampled set. Useful at full-run scale; flagged
    # underpowered when n_with_data < 25.
    old_ci = _bootstrap_paired_ci(old_vec, old_vec, lambda a, _b: sum(a) / n_with_data)
    new_ci = _bootstrap_paired_ci(new_vec, new_vec, lambda a, _b: sum(a) / n_with_data)
    delta_ci = _bootstrap_paired_ci(
        old_vec, new_vec, lambda o, n: (sum(n) - sum(o)) / n_with_data
    )
    return {
        "old": old_pass,
        "new": new_pass,
        "n_with_data": n_with_data,
        "n_overlap": n_overlap,
        "old_rate": old_rate,
        "new_rate": new_rate,
        "delta_pp": round(new_rate - old_rate, 2),
        "old_rate_ci95": [round(100 * old_ci[0], 2), round(100 * old_ci[1], 2)],
        "new_rate_ci95": [round(100 * new_ci[0], 2), round(100 * new_ci[1], 2)],
        "delta_pp_ci95": [round(100 * delta_ci[0], 2), round(100 * delta_ci[1], 2)],
        "underpowered": n_with_data < 25,
        "complete": n_with_data == n_overlap,
    }


def _missing_cell_summary(pairs: list[PerEvalPair]) -> dict:
    return {
        "ws_missing_old_eval_ids": [p["eval_id"] for p in pairs if p["ws_missing_old"]],
        "ws_missing_new_eval_ids": [p["eval_id"] for p in pairs if p["ws_missing_new"]],
        "bs_missing_old_eval_ids": [p["eval_id"] for p in pairs if p["bs_missing_old"]],
        "bs_missing_new_eval_ids": [p["eval_id"] for p in pairs if p["bs_missing_new"]],
    }


def _skill_lift_block(joint_pairs: list[PerEvalPair], n_overlap: int) -> dict:
    """Skill-lift = ws_pass_rate - bs_pass_rate, computed at old vs new on the joint set.

    Joint set = overlap evals where all 4 cells (ws_old, ws_new, bs_old,
    bs_new) are present, so old and new lifts share a denominator and the
    delta is directly comparable. Bootstrap 95% CIs (1000 paired
    resamples, deterministic seed) accompany each rate and the delta;
    they are exact when n_joint is large and approximate-but-honest when
    small. The delta_pp answers the comparison's central question: did
    the skill help differently between commits?
    """
    n = len(joint_pairs)
    if n == 0:
        return {
            "n_joint": 0,
            "n_overlap": n_overlap,
            "complete": False,
            "old_pp": 0.0,
            "new_pp": 0.0,
            "delta_pp": 0.0,
            "note": "n_joint=0; no overlap eval has all 4 cells present.",
        }
    ws_old = [int(p["ws_pass_old"]) for p in joint_pairs]
    bs_old = [int(p["bs_pass_old"]) for p in joint_pairs]
    ws_new = [int(p["ws_pass_new"]) for p in joint_pairs]
    bs_new = [int(p["bs_pass_new"]) for p in joint_pairs]
    ws_pass_old = sum(ws_old)
    bs_pass_old = sum(bs_old)
    ws_pass_new = sum(ws_new)
    bs_pass_new = sum(bs_new)
    old_pp = 100 * (ws_pass_old - bs_pass_old) / n
    new_pp = 100 * (ws_pass_new - bs_pass_new) / n
    delta_pp = new_pp - old_pp

    old_lift_ci = _bootstrap_paired_ci(
        ws_old, bs_old, lambda ws, bs: (sum(ws) - sum(bs)) / n
    )
    new_lift_ci = _bootstrap_paired_ci(
        ws_new, bs_new, lambda ws, bs: (sum(ws) - sum(bs)) / n
    )
    delta_ci = _bootstrap_skill_lift_delta_ci(joint_pairs)

    return {
        "n_joint": n,
        "n_overlap": n_overlap,
        "complete": n == n_overlap,
        "ws_pass_old": ws_pass_old,
        "bs_pass_old": bs_pass_old,
        "ws_pass_new": ws_pass_new,
        "bs_pass_new": bs_pass_new,
        "old_pp": round(old_pp, 2),
        "new_pp": round(new_pp, 2),
        "delta_pp": round(delta_pp, 2),
        "old_pp_ci95": [round(100 * old_lift_ci[0], 2), round(100 * old_lift_ci[1], 2)],
        "new_pp_ci95": [round(100 * new_lift_ci[0], 2), round(100 * new_lift_ci[1], 2)],
        "delta_pp_ci95": [round(100 * delta_ci[0], 2), round(100 * delta_ci[1], 2)],
        "underpowered": n < 25,
        "note": (
            "skill_lift_pp = (ws_pass_rate - bs_pass_rate) at the run, on the "
            "joint set where all 4 cells are present. delta_pp is the shift "
            "in skill lift between commits. CIs are 95% percentile "
            "bootstrap (1000 paired resamples, seed=0); treat as approximate "
            "when n_joint < 25."
        ),
    }


def _bootstrap_paired_ci(
    a: list[int],
    b: list[int],
    statistic,
    *,
    n_resamples: int = 1000,
    confidence: float = 0.95,
) -> tuple[float, float]:
    """Percentile bootstrap CI for a paired statistic over (a, b).

    Resamples eval indices with replacement (preserving the (a[i], b[i])
    pairing), recomputes the statistic, returns (low, high) percentiles.
    Deterministic seed so the JSON output is reproducible.
    """
    import random  # local import keeps unrelated callers cheap

    n = len(a)
    if n == 0:
        return (0.0, 0.0)
    rng = random.Random(0)
    samples = []
    for _ in range(n_resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        sa = [a[i] for i in idx]
        sb = [b[i] for i in idx]
        samples.append(statistic(sa, sb))
    samples.sort()
    alpha = (1 - confidence) / 2
    lo_idx = max(0, int(round(alpha * n_resamples)) - 1)
    hi_idx = min(n_resamples - 1, int(round((1 - alpha) * n_resamples)) - 1)
    return (samples[lo_idx], samples[hi_idx])


def _bootstrap_skill_lift_delta_ci(
    joint_pairs: list[PerEvalPair],
    *,
    n_resamples: int = 1000,
    confidence: float = 0.95,
) -> tuple[float, float]:
    """Percentile bootstrap CI for the skill-lift delta on the joint set.

    Resamples eval indices with replacement, then recomputes both old and
    new skill-lift on the same resampled indices and reports the delta.
    Pairing across all 4 cells is preserved per resample.
    """
    import random

    n = len(joint_pairs)
    if n == 0:
        return (0.0, 0.0)
    ws_old = [int(p["ws_pass_old"]) for p in joint_pairs]
    bs_old = [int(p["bs_pass_old"]) for p in joint_pairs]
    ws_new = [int(p["ws_pass_new"]) for p in joint_pairs]
    bs_new = [int(p["bs_pass_new"]) for p in joint_pairs]
    rng = random.Random(0)
    samples = []
    for _ in range(n_resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        old_lift = (sum(ws_old[i] for i in idx) - sum(bs_old[i] for i in idx)) / n
        new_lift = (sum(ws_new[i] for i in idx) - sum(bs_new[i] for i in idx)) / n
        samples.append(new_lift - old_lift)
    samples.sort()
    alpha = (1 - confidence) / 2
    lo_idx = max(0, int(round(alpha * n_resamples)) - 1)
    hi_idx = min(n_resamples - 1, int(round((1 - alpha) * n_resamples)) - 1)
    return (samples[lo_idx], samples[hi_idx])


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
    # Subset-rerun: when the new run is markedly smaller than the old run,
    # the comparison is verification of *those specific evals*, not a claim
    # about global skill quality. Threshold matches the round-d shape (16/130).
    is_subset_rerun = (
        overlap["new_total"] > 0
        and overlap["new_total"] < 0.5 * overlap["old_total"]
    )
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
    if is_subset_rerun:
        lines.extend(
            [
                "",
                f"> ⚠ Subset rerun: the new run covers {overlap['new_total']} of "
                f"{overlap['old_total']} old-run evals. Treat this comparison as "
                "**verification of the targeted evals**, not a claim about global "
                "skill quality. Use the parent run's full summary for headline numbers.",
            ]
        )
    # Provenance summary: surface causal drift (skill / src / model /
    # harness / prompt template / evals catalog) up front so movement
    # isn't accidentally attributed to skill changes when something else
    # also changed. round_label / skill_branch are label-only and tracked
    # separately so they don't trigger attribution warnings.
    causal_keys = (
        "skill_commit_at_sweep_end",
        "spyglass_src_commit",
        "model",
        "harness",
        "dispatch_prompt_template",
        "evals_catalog_semantic_sha256",
    )
    drifted = [
        field
        for field in causal_keys
        if old["provenance"].get(field) and new["provenance"].get(field)
        and old["provenance"][field] != new["provenance"][field]
    ]
    metadata_drifted = [
        field
        for field in ("round_label", "skill_branch")
        if old["provenance"].get(field) and new["provenance"].get(field)
        and old["provenance"][field] != new["provenance"][field]
    ]
    lines.extend(["", f"- causal provenance dimensions changed: **{len(drifted)}**"])
    if drifted:
        lines.append(
            f"  - {', '.join(drifted)} — see [`data/provenance_diff.json`](data/provenance_diff.json)"
        )
    else:
        lines.append("  - none — see [`data/provenance_diff.json`](data/provenance_diff.json)")
    if metadata_drifted:
        lines.append(
            f"- metadata-only differences (do not undermine attribution): {', '.join(metadata_drifted)}"
        )
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
