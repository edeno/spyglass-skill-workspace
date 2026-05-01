"""Cross-run comparison for Spyglass skill eval sweeps.

Run-agnostic: takes --new <run-dir> and --old <run-dir> and produces all
comparison outputs under <new>/comparisons/<old-basename>/ (or --out).
Comparison is directional: "did the new run drift from the old run."

Aggregates are computed on the overlap subset only; full-run cumulative
JSON files are intentionally not consulted.
"""

from __future__ import annotations

import argparse
import contextlib
import shutil
from pathlib import Path

from _compare_figures import (
    plot_category_shift,
    plot_cost_shift_by_transition,
    plot_headline_shift,
    plot_outcome_flow,
    plot_per_eval_transitions,
    plot_regression_root_causes,
    plot_routing_shift,
    plot_skill_lift_change,
    plot_targeted_edits,
)
from _compare_io import (
    build_per_eval_pairs,
    compute_overlap,
    load_eval_catalog,
    load_expected_resources,
    load_routing_records,
    load_run_bundle,
)
from _compare_writers import (
    write_catalog_diff_json,
    write_category_shift_csv,
    write_comparison_manifest_json,
    write_cost_shift_csv,
    write_headline_diff_json,
    write_outcome_2x2_shift_json,
    write_overlap_json,
    write_provenance_diff_json,
    write_regression_review_csv,
    write_regression_root_cause_csv,
    write_routing_shift_csv,
    write_targeted_edits_csvs,
    write_transitions_csv,
)
from _staging import commit_staged_outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--new", type=Path, required=True, help="New (current) run-dir.")
    parser.add_argument("--old", type=Path, required=True, help="Old (reference) run-dir.")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help=(
            "Output dir. Defaults to <new>/comparisons/<old-basename>/. "
            "Always staged through .data_tmp/ + .figures_tmp/ and committed atomically."
        ),
    )
    return parser.parse_args()


def configure_out(new_dir: Path, old_dir: Path, override: Path | None) -> Path:
    """Resolve output dir and clear any leftover staging dirs from a prior failed run."""
    if override is not None:
        out = override.resolve()
    else:
        out = (new_dir.resolve() / "comparisons" / old_dir.resolve().name).resolve()
    out.mkdir(parents=True, exist_ok=True)
    for stale in (out / ".data_tmp", out / ".figures_tmp"):
        if stale.is_dir():
            shutil.rmtree(stale)
    stale_index = out / ".INDEX.tmp"
    if stale_index.exists():
        stale_index.unlink()
    (out / ".data_tmp").mkdir()
    (out / ".figures_tmp").mkdir()
    return out


def main() -> None:
    args = parse_args()
    out = configure_out(args.new, args.old, args.out)
    staged_data = out / ".data_tmp"
    staged_figures = out / ".figures_tmp"

    committed = False
    try:
        old = load_run_bundle(args.old)
        new = load_run_bundle(args.new)
        overlap = compute_overlap(old, new)
        pairs = build_per_eval_pairs(old, new, overlap)

        write_overlap_json(staged_data, overlap)
        write_provenance_diff_json(staged_data, old, new)
        write_catalog_diff_json(staged_data, load_eval_catalog(old), load_eval_catalog(new))
        write_headline_diff_json(staged_data, overlap, pairs, old, new)
        write_transitions_csv(staged_data, pairs)
        write_targeted_edits_csvs(staged_data, pairs, new["edit_to_evals"])
        write_outcome_2x2_shift_json(staged_data, pairs)
        write_cost_shift_csv(staged_data, pairs)
        write_category_shift_csv(staged_data, pairs)
        write_regression_review_csv(staged_data, pairs, old, new)

        # Routing shift + regression root-cause classifier: routing depends
        # on transcripts on both sides. The classifier always runs; with
        # missing transcripts / expected sets it falls back to "unknown"
        # buckets but still distinguishes rubric / synthesis (independent
        # of routing).
        if old["has_transcripts"] and new["has_transcripts"]:
            expected_refs, expected_scripts = load_expected_resources(new)
            if not expected_refs and not expected_scripts:
                expected_refs, expected_scripts = load_expected_resources(old)
            old_routing = load_routing_records(old)
            new_routing = load_routing_records(new)
            write_routing_shift_csv(
                staged_data,
                pairs,
                old_routing,
                new_routing,
                expected_refs,
                expected_scripts,
                old_has_transcripts=True,
                new_has_transcripts=True,
            )
        else:
            old_routing = {}
            new_routing = {}
            expected_refs = {}
            expected_scripts = {}
        write_regression_root_cause_csv(
            staged_data,
            pairs,
            old_routing,
            new_routing,
            expected_refs,
            expected_scripts,
        )

        plot_headline_shift(staged_figures, staged_data)
        plot_per_eval_transitions(staged_figures, staged_data)
        plot_outcome_flow(staged_figures, staged_data)
        plot_targeted_edits(staged_figures, staged_data)
        plot_cost_shift_by_transition(staged_figures, staged_data)
        plot_routing_shift(staged_figures, staged_data)
        plot_category_shift(staged_figures, staged_data)
        plot_skill_lift_change(staged_figures, staged_data)
        plot_regression_root_causes(staged_figures, staged_data)

        # Manifest + INDEX.md must be written last so they enumerate every
        # staged output. Both are committed atomically alongside data/ and
        # figures/.
        write_comparison_manifest_json(out, staged_data, staged_figures, overlap, old, new)

        commit_staged_outputs(
            [
                (staged_data, out / "data"),
                (staged_figures, out / "figures"),
                (out / ".INDEX.tmp", out / "INDEX.md"),
            ]
        )
        committed = True
    finally:
        # Clean staging dirs on any failure path. commit_staged_outputs
        # renames them on success, so they only linger if we never reached
        # the commit (or commit itself failed).
        if not committed:
            for staged in (staged_data, staged_figures):
                if staged.is_dir():
                    with contextlib.suppress(OSError):
                        shutil.rmtree(staged)
            staged_index = out / ".INDEX.tmp"
            if staged_index.exists():
                with contextlib.suppress(OSError):
                    staged_index.unlink()

    print(
        f"Wrote comparison ({old['run_id']} → {new['run_id']}, "
        f"n_overlap={overlap['n_overlap']}) to {out}"
    )


if __name__ == "__main__":
    main()
