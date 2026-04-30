"""Shared schemas, constants, and output metadata for eval summaries."""

from __future__ import annotations

from collections import Counter
from typing import Literal, TypedDict


class PerEvalResult(TypedDict):
    """Flattened per-eval result with both with-skill and baseline outcomes."""

    eval_id: int
    eval_name: str
    batch: int
    ws_pass: bool
    bs_pass: bool
    ws_exp_p: int
    ws_exp_t: int
    bs_exp_p: int
    bs_exp_t: int


class EvalCategory(TypedDict):
    """Stage/tier/difficulty metadata from evals.json."""

    stage: str
    tier: str
    difficulty: str


class ExpectedResourceBlock(TypedDict):
    """Expected reference/script annotations for one eval."""

    required: list[str]
    optional: list[str]
    distractor: list[str]


class TranscriptRecord(TypedDict):
    """Parsed transcript counters for one agent transcript."""

    agent_id: str
    batch: int
    eval_id: int
    condition: Literal["with_skill", "without_skill"]
    n_read_calls: int
    n_bash_calls: int
    n_tool_errors: int
    ref_opens: Counter[str]
    script_executions: Counter[str]
    script_source_reads: Counter[str]
    spyglass_src_reads: int
    skill_dir_touches: int


EvalCategories = dict[int, EvalCategory]
ExpectedResources = dict[int, ExpectedResourceBlock]

WONG = {
    "ws": "#0072B2",
    "bs": "#D55E00",
    "delta_pos": "#009E73",
    "delta_neg": "#CC79A7",
    "neutral": "#999999",
    "both_pass": "#56B4E9",
    "both_fail": "#666666",
}

SKIP_GATE_MIN_EVALS = 3
SKIP_GATE_STRONG_BASELINE_PASS_RATE = 90.0
SKIP_GATE_HIGH_BASELINE_PASS_RATE = 80.0
SKIP_GATE_LOW_RESCUE_RATE = 10.0
SKIP_GATE_TOTAL_EXTRA_TOKEN_FLOOR = 100_000

EXPENSIVE_BOTH_PASS_EXTRA_TOKEN_FLOOR = 20_000

FIX_PRIORITY_ACTION_ORDER = {
    "investigate_regression": 0,
    "inspect_transcripts": 1,
    "fix_script_routing": 2,
    "fix_reference_routing": 3,
    "fix_template_or_reference_content": 4,
    "expensive_both_pass": 5,
    "": 6,
}

EVAL_METADATA_COLUMNS = ["eval_id", "batch", "eval_name", "stage", "tier", "difficulty"]

FIGURE_DPI = 160
SIZE_SINGLE = (10, 5.5)
SIZE_WIDE = (13, 5.5)
SIZE_COMPACT = (9, 5)
SIZE_SQUARE = (8.5, 8.5)
SIZE_TALL = (12, 9)
GRID_STYLE = {"alpha": 0.3, "linestyle": ":"}
ANNOTATION_FONTSIZE = 9


MANIFEST_OVERRIDES = {
    "appendix_per_batch_pass_rate.png": ("batch_health", "appendix", "Operational batch-health pass-rate view."),
    "appendix_delta_per_batch.png": ("batch_health", "appendix", "Per-batch skill lift for spotting run or batch anomalies."),
    "appendix_per_eval_outcomes_by_batch.png": ("headline", "appendix", "Per-eval outcome strip for visual scan of wins/regressions by batch."),
    "appendix_cost_per_batch.png": ("batch_health", "appendix", "Batch-level token and duration profile."),
    "q01_how_much_does_the_skill_help.png": ("headline", "primary", "Headline ws/bs full-pass, expectation, and token totals."),
    "appendix_dense_pass_rate_by_category.png": ("category", "appendix", "Dense stage/tier pass-rate view; use outcome_by_category for primary decisions."),
    "q03_does_it_help_on_harder_evals.png": ("category", "primary", "Skill value by eval difficulty."),
    "appendix_difficulty_x_stage_heatmap.png": ("coverage", "appendix", "Stage x difficulty performance and coverage map."),
    "appendix_per_eval_expectation_scatter.png": ("headline", "appendix", "Exploratory per-eval ws vs bs expectation-rate scatter."),
    "appendix_top_skill_wins.png": ("headline", "appendix", "Largest per-eval skill wins by expectation delta."),
    "appendix_raw_reference_utilization.png": ("utilization", "appendix", "Raw reference open counts; use routing outputs for expected-vs-called analysis."),
    "appendix_raw_script_utilization.png": ("utilization", "appendix", "Raw bundled-script executions/source-reads; use script confusion for routing analysis."),
    "appendix_reference_effectiveness_when_loaded.png": ("utilization", "appendix", "Reference loads vs pass-rate-when-loaded; confounded by eval difficulty."),
    "q04_what_does_the_extra_cost_buy.png": ("cost", "primary", "Per-eval extra tokens vs expectation delta."),
    "q02_where_does_the_skill_help.png": ("category", "primary", "Where the skill uniquely helps, regresses, or still fails by stage/tier."),
    "q05_is_value_more_than_source_access.png": ("headline", "primary", "Whether skill value is source-delivery vs workflow/routing."),
    "q10_where_are_eval_coverage_gaps.png": ("coverage", "secondary", "Stage x tier eval-count map for future eval-set design."),
    "appendix_failure_taxonomy_placeholder.png": ("fix_priority", "appendix", "Manual failure-type distribution; placeholder until failure_taxonomy.csv is annotated."),
    "q09_how_well_are_expected_references_used.png": ("routing", "secondary", "Dense reference expected-vs-opened heatmap by required/optional/distractor status."),
    "q06_are_reference_routes_working.png": ("routing", "primary", "Required reference opened vs missed; optional references are neutral."),
    "q07_are_script_routes_working.png": ("routing", "primary", "Required bundled script executed vs missed."),
    "q08_what_should_we_fix_next.png": ("fix_priority", "primary", "Likely-action distribution from fix_priority.csv."),
    "q11_where_are_skill_regressions.png": ("headline", "secondary", "Eval-level cases where with_skill scored below baseline."),
    "INDEX.md": ("headline", "primary", "Generated guide to summary outputs grouped by priority."),
    "SUMMARY.md": ("headline", "primary", "Human-authored narrative summary and recommendations."),
    "baseline_source_split.json": ("headline", "secondary", "Machine-readable source-delivery vs workflow/routing split."),
    "batch_summary.csv": ("batch_health", "secondary", "Per-batch full-pass, expectation, behavioral, token, and duration metrics."),
    "category_breakdown.csv": ("category", "secondary", "Pass-rate counts by stage/tier/difficulty."),
    "cost_by_outcome.csv": ("cost", "primary", "Extra ws tokens split by both-pass / skill-only / baseline-only / both-fail."),
    "cost_effectiveness_per_eval.csv": ("cost", "primary", "Per-eval cost-effectiveness data."),
    "cumulative_summary.json": ("headline", "primary", "Machine-readable headline totals, outcome cross-tab, spend by outcome, and McNemar test."),
    "eval_coverage.csv": ("coverage", "secondary", "Stage x tier eval-count matrix."),
    "failure_taxonomy.csv": ("fix_priority", "secondary", "Manual annotation stub for ws-failed eval failure modes."),
    "fix_priority.csv": ("fix_priority", "primary", "Combined next-action table with outcome, cost, and routing misses."),
    "headroom_evals.csv": ("fix_priority", "primary", "Failed or weak evals where skill edits may still improve outcomes."),
    "outcome_by_category.csv": ("category", "primary", "CSV behind the outcome-by-category plot."),
    "per_eval_routing.csv": ("routing", "secondary", "Per-eval refs opened, scripts run, source touches, and tool errors."),
    "ref_utilization.json": ("utilization", "appendix", "Raw per-reference transcript open counts."),
    "reference_call_confusion.csv": ("routing", "primary", "Reference expected-vs-opened confusion matrix."),
    "reference_effectiveness.csv": ("utilization", "appendix", "Per-reference loads and pass-rate-when-loaded."),
    "reference_expected_by_eval.csv": ("routing", "primary", "Per-eval reference routing diagnosis."),
    "reference_expected_used.csv": ("routing", "secondary", "Per-reference expected/opened/pass-rate table by status."),
    "routing_diagnosis.csv": ("routing", "primary", "Canonical ws-failure routing-vs-synthesis diagnosis table."),
    "script_call_confusion.csv": ("routing", "primary", "Bundled-script expected-vs-executed confusion matrix."),
    "script_expected_by_eval.csv": ("routing", "primary", "Per-eval bundled-script routing diagnosis."),
    "script_utilization.json": ("utilization", "appendix", "Raw bundled-script execution and source-read counts."),
    "skip_gate_candidates.csv": ("cost", "primary", "High-cost categories where baseline already performs strongly."),
    "stage_x_difficulty.csv": ("coverage", "secondary", "Flat data behind the stage x difficulty heatmap."),
    "summary_manifest.json": ("headline", "primary", "Output family/priority/purpose index."),
    "top_skill_wins.csv": ("headline", "secondary", "Per-eval expectation-delta ranking."),
    "transcript_stats.json": ("utilization", "appendix", "Tool-call totals, source assistance, contamination, and activation metrics."),
    "ws_regressions.csv": ("fix_priority", "primary", "Full-pass or expectation-level regressions against baseline."),
}
