"""Generate summary plots for a Spyglass skill eval sweep.

Run-agnostic: takes `--run <path-to-runs/<run-id>/>` and produces all
figures under `<run>/summary/figures/` and CSV/JSON data under `<run>/summary/data/` (or `--out`).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from _eval_io import (
    load_batch_labels,
    load_benchmarks,
    load_eval_categories,
    load_expected_refs,
    load_expected_scripts,
    load_per_eval_results,
    load_per_eval_timing,
)
from _figures import (
    configure_figures,
    plot_baseline_source_split,
    plot_by_category,
    plot_by_difficulty,
    plot_cost_effectiveness_scatter,
    plot_cost_reduction_candidates,
    plot_cumulative_summary,
    plot_delta_per_batch,
    plot_difficulty_x_stage_heatmap,
    plot_eval_coverage_map,
    plot_expected_call_confusion,
    plot_extra_tokens_by_outcome,
    plot_failure_routing_vs_synthesis,
    plot_failure_taxonomy,
    plot_fix_priority_actions,
    plot_missed_reference_routes,
    plot_missed_script_routes,
    plot_near_miss_evals,
    plot_outcome_by_category,
    plot_per_batch_pass_rate,
    plot_per_eval_outcomes,
    plot_per_eval_scatter,
    plot_reference_effectiveness,
    plot_reference_expected_used,
    plot_reference_utilization,
    plot_script_utilization,
    plot_tokens_and_duration,
    plot_top_skill_wins,
)
from _schemas import TranscriptRecord
from _transcripts import build_agent_to_run, configure_transcripts, parse_transcripts
from _util import discover_iterations, find_skill_root
from _writers import (
    configure_writers,
    observed_resources_by_eval,
    unlink_outputs,
    write_baseline_source_split_json,
    write_batch_summary_csv,
    write_cost_by_outcome_csv,
    write_cost_effectiveness_csv,
    write_cumulative_summary_json,
    write_eval_coverage_csv,
    write_expected_by_eval_csv,
    write_expected_call_confusion,
    write_failure_taxonomy_stub_csv,
    write_fix_priority_csv,
    write_headroom_evals_csv,
    write_outcome_by_category_csv,
    write_per_category_csv,
    write_per_eval_routing_csv,
    write_reference_effectiveness_csv,
    write_reference_expected_used_csv,
    write_routing_failure_views,
    write_skip_gate_candidates_csv,
    write_stage_x_difficulty_csv,
    write_summary_manifest_json,
    write_top_skill_wins_csv,
    write_ws_regressions_csv,
)

_UNCONFIGURED = Path("/__not_configured__")
OUT: Path = _UNCONFIGURED
WORKSPACE: Path = _UNCONFIGURED
EVALS_PATH: Path = _UNCONFIGURED
BATCH_ORDER: list[int] = []
BATCH_LABELS: dict[int, str] = {}



def configure_run(run_dir: Path, out_dir: Path | None = None) -> None:
    """Populate the run-scoped module globals and configure submodules."""
    global OUT, WORKSPACE, BATCH_ORDER, BATCH_LABELS
    WORKSPACE = run_dir.resolve()
    OUT = (out_dir or WORKSPACE / "summary").resolve()
    OUT.mkdir(parents=True, exist_ok=True)
    BATCH_ORDER = discover_iterations(WORKSPACE)
    if not BATCH_ORDER:
        raise SystemExit(f"No iteration-N/ dirs found under {WORKSPACE}")
    BATCH_LABELS = load_batch_labels(WORKSPACE, BATCH_ORDER)
    configure_figures(OUT, WORKSPACE, BATCH_ORDER, BATCH_LABELS)
    configure_transcripts(OUT, WORKSPACE, BATCH_ORDER)
    configure_writers(OUT, WORKSPACE, BATCH_ORDER, BATCH_LABELS)


def configure_skill_root(skill_root: Path | None = None) -> None:
    """Resolve the skill repo and set EVALS_PATH."""
    global EVALS_PATH
    repo = find_skill_root(skill_root)
    EVALS_PATH = repo / "skills" / "spyglass" / "evals" / "evals.json"


def parse_args() -> argparse.Namespace:
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
        help="Output dir for figures and CSV/JSON. Defaults to <run>/summary/.",
    )
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        default=None,
        help=(
            "Directory holding snapshotted subagent transcripts. Defaults to "
            "<run>/transcripts_snapshot/."
        ),
    )
    parser.add_argument(
        "--skill-root",
        type=Path,
        default=None,
        help=(
            "Path to the spyglass-skill repo. Defaults to ../spyglass-skill/ "
            "as a sibling of the workspace repo. Override via this flag or "
            "the SPYGLASS_SKILL environment variable."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    configure_run(args.run, args.out)
    configure_skill_root(args.skill_root)
    benchmarks = load_benchmarks(WORKSPACE, BATCH_ORDER)
    cats = load_eval_categories(EVALS_PATH)
    per_eval = load_per_eval_results(benchmarks)
    timing = load_per_eval_timing(WORKSPACE, BATCH_ORDER)

    plot_per_batch_pass_rate(benchmarks)
    plot_delta_per_batch(benchmarks)
    plot_per_eval_outcomes(benchmarks)
    plot_tokens_and_duration(benchmarks)
    plot_cumulative_summary(benchmarks)
    plot_by_category(cats, per_eval)
    plot_by_difficulty(cats, per_eval)
    plot_difficulty_x_stage_heatmap(cats, per_eval)
    plot_per_eval_scatter(cats, per_eval)
    plot_top_skill_wins(cats, per_eval)

    if args.snapshot_dir:
        snapshot_dir = args.snapshot_dir.resolve()
    else:
        snapshot_dir = (WORKSPACE / "transcripts_snapshot").resolve()
    records: list[TranscriptRecord] | None = None
    if snapshot_dir.exists() and any(snapshot_dir.iterdir()):
        agent_to_run = build_agent_to_run()
        records = parse_transcripts(snapshot_dir, agent_to_run)
        plot_reference_utilization(agent_to_run, records, per_eval)
        plot_script_utilization(agent_to_run, records)
    else:
        unlink_outputs(
            "appendix_raw_reference_utilization.png",
            "appendix_raw_script_utilization.png",
            "ref_utilization.json",
            "script_utilization.json",
            "transcript_stats.json",
        )
        print(f"Skipping transcript-derived plots: snapshot dir empty at {snapshot_dir}")
        print("  Run snapshot_transcripts.py first to populate it.")

    write_per_category_csv(cats, per_eval)
    write_batch_summary_csv(benchmarks)
    write_cumulative_summary_json(benchmarks, per_eval, timing)
    write_top_skill_wins_csv(cats, per_eval)
    write_stage_x_difficulty_csv(cats, per_eval)
    write_per_eval_routing_csv(cats, per_eval, records)

    expected_refs = load_expected_refs(EVALS_PATH)
    expected_scripts = load_expected_scripts(EVALS_PATH)
    refs_by_eval = observed_resources_by_eval(records, "reference") if records else None
    scripts_by_eval = observed_resources_by_eval(records, "script") if records else None
    write_reference_effectiveness_csv(records, per_eval, cats)
    write_cost_effectiveness_csv(cats, per_eval, timing)
    write_cost_by_outcome_csv(per_eval, timing)
    write_skip_gate_candidates_csv(cats, per_eval, timing)
    write_outcome_by_category_csv(cats, per_eval)
    write_ws_regressions_csv(cats, per_eval)
    write_baseline_source_split_json(per_eval, records)
    write_eval_coverage_csv(cats)
    write_headroom_evals_csv(cats, per_eval)
    write_failure_taxonomy_stub_csv(cats, per_eval)
    write_reference_expected_used_csv(per_eval, records, expected_refs)
    write_expected_call_confusion(
        per_eval=per_eval,
        records=records,
        expected=expected_refs,
        kind="reference",
    )
    write_expected_call_confusion(
        per_eval=per_eval,
        records=records,
        expected=expected_scripts,
        kind="script",
    )
    write_expected_by_eval_csv(
        cats=cats,
        per_eval=per_eval,
        observed=refs_by_eval,
        expected=expected_refs,
        kind="reference",
    )
    write_expected_by_eval_csv(
        cats=cats,
        per_eval=per_eval,
        observed=scripts_by_eval,
        expected=expected_scripts,
        kind="script",
    )
    write_routing_failure_views(
        cats=cats,
        per_eval=per_eval,
        refs_by_eval=refs_by_eval,
        scripts_by_eval=scripts_by_eval,
        expected_refs=expected_refs,
        expected_scripts=expected_scripts,
    )
    write_fix_priority_csv(
        cats=cats,
        per_eval=per_eval,
        refs_by_eval=refs_by_eval,
        scripts_by_eval=scripts_by_eval,
        expected_refs=expected_refs,
        expected_scripts=expected_scripts,
        timing=timing,
    )

    plot_reference_effectiveness()
    plot_cost_effectiveness_scatter()
    plot_outcome_by_category()
    plot_baseline_source_split()
    plot_eval_coverage_map()
    plot_failure_taxonomy()
    plot_reference_expected_used()
    plot_expected_call_confusion("reference")
    plot_expected_call_confusion("script")
    plot_fix_priority_actions()
    plot_extra_tokens_by_outcome()
    plot_cost_reduction_candidates()
    plot_failure_routing_vs_synthesis()
    plot_near_miss_evals()
    plot_missed_reference_routes()
    plot_missed_script_routes()

    write_summary_manifest_json()
    print("Wrote plots + CSV/JSON exports to", OUT)


if __name__ == "__main__":
    main()
