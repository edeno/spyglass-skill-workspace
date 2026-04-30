"""CSV/JSON writer functions for eval summary outputs."""

from __future__ import annotations

import csv
import io
import json
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from _aggregations import (
    build_spend_by_outcome,
    count_outcomes,
    exact_mcnemar_p,
    summarize_benchmarks,
)
from _aggregations import (
    outcome_label as _outcome_label,
)
from _figures import setup_axes
from _schemas import (
    EVAL_METADATA_COLUMNS,
    EXPENSIVE_BOTH_PASS_EXTRA_TOKEN_FLOOR,
    FIX_PRIORITY_ACTION_ORDER,
    MANIFEST_OVERRIDES,
    SKIP_GATE_HIGH_BASELINE_PASS_RATE,
    SKIP_GATE_LOW_RESCUE_RATE,
    SKIP_GATE_MIN_EVALS,
    SKIP_GATE_STRONG_BASELINE_PASS_RATE,
    SKIP_GATE_TOTAL_EXTRA_TOKEN_FLOOR,
    WONG,
    EvalCategories,
    ExpectedResourceBlock,
    ExpectedResources,
    PerEvalResult,
    TranscriptRecord,
)
from _transcripts import TRACKED_SCRIPT_ROLES, TRACKED_SCRIPTS

_UNCONFIGURED = Path("/__not_configured__")
OUT: Path = _UNCONFIGURED
FIGURES: Path = _UNCONFIGURED
DATA: Path = _UNCONFIGURED
WORKSPACE: Path = _UNCONFIGURED
BATCH_ORDER: list[int] = []
BATCH_LABELS: dict[int, str] = {}


def configure_writers(
    out: Path, workspace: Path, batch_order: list[int], batch_labels: dict[int, str]
) -> None:
    """Set run-scoped writer globals."""
    global OUT, FIGURES, DATA, WORKSPACE, BATCH_ORDER, BATCH_LABELS
    OUT = out
    FIGURES = OUT / "figures"
    DATA = OUT / "data"
    FIGURES.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    WORKSPACE = workspace
    BATCH_ORDER = batch_order
    BATCH_LABELS = batch_labels


def figure_path(name: str) -> Path:
    """Return the path for a generated figure."""
    return FIGURES / name


def data_path(name: str) -> Path:
    """Return the path for generated machine-readable data."""
    return DATA / name


def output_path(name: str) -> Path:
    """Resolve a generated output name to its organized location."""
    path = Path(name)
    if path.parts and path.parts[0] in {"data", "figures"}:
        return OUT / path
    if path.suffix == ".png":
        return figure_path(path.name)
    if path.suffix in {".csv", ".json"}:
        return data_path(path.name)
    return OUT / path


def unlink_outputs(*names: str) -> None:
    """Remove generated outputs that are invalid for the current input state."""
    for name in names:
        try:
            output_path(name).unlink()
        except FileNotFoundError:
            pass


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    """Write CSV rows with stable field order and robust quoting."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    path.write_text(buf.getvalue())

def _join_items(items) -> str:
    """Stable semicolon-delimited cell for list-like CSV fields."""
    return ";".join(sorted(str(x) for x in items))

def collect_behavioral(batch_id: int) -> tuple[int, int, int, int]:
    """Return (ws_pass, ws_total, bs_pass, bs_total) on behavioral checks for a batch.

    Walks each eval_dir/{with_skill,without_skill}/grading.json. Skips runs whose
    grading.json is missing (e.g. a malformed eval directory) — those should be
    rare; we log them but don't crash the pipeline.
    """
    ws_p = ws_t = bs_p = bs_t = 0
    for eval_dir in (WORKSPACE / f"iteration-{batch_id}").glob("eval-*"):
        for cond in ("with_skill", "without_skill"):
            grading_path = eval_dir / cond / "grading.json"
            if not grading_path.exists():
                continue
            grading = json.loads(grading_path.read_text())
            for e in grading["expectations"]:
                if not e["text"].startswith("behavioral_check:"):
                    continue
                if cond == "with_skill":
                    ws_t += 1
                    ws_p += int(bool(e["passed"]))
                else:
                    bs_t += 1
                    bs_p += int(bool(e["passed"]))
    return ws_p, ws_t, bs_p, bs_t

def write_per_category_csv(
    cats: EvalCategories, per_eval: list[PerEvalResult]
) -> None:
    """Side artifact: detailed numbers behind the category plot."""
    rows = []
    for kind in ("stage", "tier", "difficulty"):
        agg: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
        for r in per_eval:
            c = cats.get(r["eval_id"], {}).get(kind, "unknown")
            agg[c][0] += 1
            agg[c][1] += int(r["ws_pass"])
            agg[c][2] += int(r["bs_pass"])
        for c, (n, w, b) in sorted(agg.items(), key=lambda x: -x[1][0]):
            d = 100 * (w - b) / n
            rows.append(
                {
                    "category_kind": kind,
                    "category": c,
                    "n_evals": n,
                    "ws_pass": w,
                    "bs_pass": b,
                    "delta_pp": f"{d:.1f}",
                }
            )
    _write_csv(
        data_path("category_breakdown.csv"),
        ["category_kind", "category", "n_evals", "ws_pass", "bs_pass", "delta_pp"],
        rows,
    )

def write_batch_summary_csv(benchmarks: dict[int, dict]) -> None:
    """Per-batch row covering everything cited in BATCHES.md and §"Headline" tables.

    One row per batch with: full-eval pass counts and rates per condition,
    expectation pass counts (substring + behavioral combined), behavioral-only
    pass counts (the LLM-judge subset that's more sensitive than the full
    binary rubric), total/mean tokens per condition, mean wall-clock per
    condition, plus all the ws-bs deltas. Lets the summary author cite any
    per-batch number without opening a PNG.
    """
    rows = []
    for b in BATCH_ORDER:
        cfg = benchmarks[b]["configurations"]
        ws = cfg["with_skill"]
        bs = cfg["without_skill"]
        n = ws["n_runs"]
        ws_full_rate = 100 * ws["evals_full_pass"] / n
        bs_full_rate = 100 * bs["evals_full_pass"] / n
        ws_expectation_rate = 100 * ws["expectations_passed"] / ws["expectations_total"]
        bs_expectation_rate = 100 * bs["expectations_passed"] / bs["expectations_total"]
        ws_b_p, ws_b_t, bs_b_p, bs_b_t = collect_behavioral(b)
        ws_b_rate = 100 * ws_b_p / ws_b_t if ws_b_t else 0.0
        bs_b_rate = 100 * bs_b_p / bs_b_t if bs_b_t else 0.0
        # ws_b_t and bs_b_t are equal in well-formed batches (same eval, same
        # rubric), so we report a single behavioral_total.
        b_total = ws_b_t
        # Replace newlines in the label so the CSV stays one-line-per-row.
        label = BATCH_LABELS[b].replace("\n", " ")
        rows.append(
            {
                "batch_id": b,
                "label": label,
                "n_evals": n,
                "ws_full_pass": ws["evals_full_pass"],
                "ws_full_rate": f"{ws_full_rate:.1f}",
                "bs_full_pass": bs["evals_full_pass"],
                "bs_full_rate": f"{bs_full_rate:.1f}",
                "delta_full_pp": f"{ws_full_rate - bs_full_rate:.1f}",
                "ws_exp_pass": ws["expectations_passed"],
                "ws_exp_total": ws["expectations_total"],
                "ws_expectation_rate": f"{ws_expectation_rate:.1f}",
                "bs_exp_pass": bs["expectations_passed"],
                "bs_exp_total": bs["expectations_total"],
                "bs_expectation_rate": f"{bs_expectation_rate:.1f}",
                "delta_expectation_pp": f"{ws_expectation_rate - bs_expectation_rate:.1f}",
                "ws_behavioral_pass": ws_b_p,
                "bs_behavioral_pass": bs_b_p,
                "behavioral_total": b_total,
                "delta_behavioral_pp": f"{ws_b_rate - bs_b_rate:.1f}",
                "ws_tokens_total": ws["tokens_total"],
                "bs_tokens_total": bs["tokens_total"],
                "ws_tokens_mean": f"{ws['tokens_mean']:.1f}",
                "bs_tokens_mean": f"{bs['tokens_mean']:.1f}",
                "ws_duration_mean_s": f"{ws['duration_mean_s']:.2f}",
                "bs_duration_mean_s": f"{bs['duration_mean_s']:.2f}",
            }
        )
    _write_csv(
        data_path("batch_summary.csv"),
        [
            "batch_id",
            "label",
            "n_evals",
            "ws_full_pass",
            "ws_full_rate",
            "bs_full_pass",
            "bs_full_rate",
            "delta_full_pp",
            "ws_exp_pass",
            "ws_exp_total",
            "ws_expectation_rate",
            "bs_exp_pass",
            "bs_exp_total",
            "bs_expectation_rate",
            "delta_expectation_pp",
            "ws_behavioral_pass",
            "bs_behavioral_pass",
            "behavioral_total",
            "delta_behavioral_pp",
            "ws_tokens_total",
            "bs_tokens_total",
            "ws_tokens_mean",
            "bs_tokens_mean",
            "ws_duration_mean_s",
            "bs_duration_mean_s",
        ],
        rows,
    )

def write_cumulative_summary_json(
    benchmarks: dict[int, dict], per_eval: list[PerEvalResult], timing: dict[tuple[int, int, str], int]
) -> None:
    """Headline cumulative numbers — the SUMMARY.md headline table in JSON."""
    totals = summarize_benchmarks(benchmarks)
    ws, bs = totals["ws"], totals["bs"]
    ws_full, bs_full = ws["full_pass"], bs["full_pass"]
    n_evals = ws["n_runs"]
    ws_exp_p, ws_exp_t = ws["exp_p"], ws["exp_t"]
    bs_exp_p, bs_exp_t = bs["exp_p"], bs["exp_t"]
    ws_tokens, bs_tokens = ws["tokens"], bs["tokens"]

    both_pass = sum(1 for r in per_eval if r["ws_pass"] and r["bs_pass"])
    skill_only = sum(1 for r in per_eval if r["ws_pass"] and not r["bs_pass"])
    bs_only = sum(1 for r in per_eval if r["bs_pass"] and not r["ws_pass"])
    both_fail = sum(1 for r in per_eval if not r["ws_pass"] and not r["bs_pass"])
    payload = {
        "n_evals": n_evals,
        "n_batches": len(BATCH_ORDER),
        "with_skill": {
            "full_pass": ws_full,
            "full_pass_rate": round(100 * ws_full / n_evals, 2),
            "expectation_pass": ws_exp_p,
            "expectation_total": ws_exp_t,
            "expectation_pass_rate": round(100 * ws_exp_p / ws_exp_t, 2),
            "tokens_total": ws_tokens,
        },
        "without_skill": {
            "full_pass": bs_full,
            "full_pass_rate": round(100 * bs_full / n_evals, 2),
            "expectation_pass": bs_exp_p,
            "expectation_total": bs_exp_t,
            "expectation_pass_rate": round(100 * bs_exp_p / bs_exp_t, 2),
            "tokens_total": bs_tokens,
        },
        "delta": {
            "full_pass_pp": round(100 * (ws_full - bs_full) / n_evals, 2),
            "expectation_pp": round(
                100 * (ws_exp_p / ws_exp_t - bs_exp_p / bs_exp_t), 2
            ),
            "tokens_total": ws_tokens + bs_tokens,
        },
        "outcomes": {
            "both_pass": both_pass,
            "skill_only": skill_only,
            "baseline_only": bs_only,
            "both_fail": both_fail,
            "note": "Per-eval cross-tab. skill_only + baseline_only = discordant pairs that drive the McNemar test below.",
        },
        "spend_by_outcome": build_spend_by_outcome(per_eval, timing),
        "significance": {
            "test": "McNemar (exact, two-sided)",
            "discordant_skill_only": skill_only,
            "discordant_baseline_only": bs_only,
            "p_value": exact_mcnemar_p(skill_only, bs_only),
            "note": "Pairs each eval's ws and bs outcomes. p < 0.05 means the +full_pass_pp delta is unlikely under H0 (skill has no effect). Computed with stdlib math.comb; no scipy needed.",
        },
    }
    (data_path("cumulative_summary.json")).write_text(json.dumps(payload, indent=2) + "\n")

def write_stage_x_difficulty_csv(
    cats: EvalCategories, per_eval: list[PerEvalResult]
) -> None:
    """Flat CSV of plot 08's stage × difficulty heatmap cells.

    One row per (stage, difficulty) combination present in the eval set,
    with ws/bs/n/Δ. Lets the SUMMARY.md author cite specific cells (e.g.
    "hard pipeline-authoring: +50pp on 4 evals") without reading them off
    the heatmap.
    """
    cell: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0, 0])
    for r in per_eval:
        cat = cats.get(r["eval_id"], {})
        s = cat.get("stage", "unknown")
        d = cat.get("difficulty", "unknown")
        cell[(s, d)][0] += int(r["ws_pass"])
        cell[(s, d)][1] += int(r["bs_pass"])
        cell[(s, d)][2] += 1
    rows = []
    # Sort by total skill lift desc within each stage, then by stage name
    # so the CSV reads top-down like the heatmap (high-lift stages first).
    by_stage_lift: dict[str, int] = defaultdict(int)
    for (s, _), (ws_p, bs_p, _) in cell.items():
        by_stage_lift[s] += ws_p - bs_p
    diff_rank = {"easy": 0, "medium": 1, "hard": 2}
    sorted_keys = sorted(
        cell.keys(),
        key=lambda k: (-by_stage_lift[k[0]], k[0], diff_rank.get(k[1], 99)),
    )
    for s, d in sorted_keys:
        ws_p, bs_p, n = cell[(s, d)]
        delta = 100 * (ws_p - bs_p) / n if n else 0.0
        rows.append(
            {
                "stage": s,
                "difficulty": d,
                "n_evals": n,
                "ws_pass": ws_p,
                "bs_pass": bs_p,
                "delta_pp": f"{delta:.1f}",
            }
        )
    _write_csv(
        data_path("stage_x_difficulty.csv"),
        ["stage", "difficulty", "n_evals", "ws_pass", "bs_pass", "delta_pp"],
        rows,
    )

def write_per_eval_routing_csv(
    cats: EvalCategories,
    per_eval: list[PerEvalResult],
    records: list[TranscriptRecord] | None,
) -> None:
    """Per-eval × per-condition routing record.

    For each (eval_id, condition) joins the pass/fail outcome with what the
    transcript shows the agent actually reached for: top references opened,
    bundled scripts executed, tool-call counts, error count. The most
    actionable diagnostic for skill maintenance — when an eval fails,
    "what did the agent reach for?" is the immediate next question.

    Skipped entirely if no transcripts are available (records is None).
    """
    if records is None:
        unlink_outputs("per_eval_routing.csv")
        return
    by_key: dict[tuple[int, int, str], dict] = {}
    for r in records:
        key = (r["batch"], r["eval_id"], r["condition"])
        # If multiple transcripts exist for the same key (retries),
        # union the routing signals — the question is "did the agent
        # ever reach for this?", not "which retry attempt did so".
        cur = by_key.setdefault(
            key,
            {
                "ref_opens": Counter(),
                "script_executions": Counter(),
                "n_read": 0,
                "n_bash": 0,
                "n_errors": 0,
            },
        )
        cur["ref_opens"].update(r["ref_opens"])
        cur["script_executions"].update(r["script_executions"])
        cur["n_read"] += r["n_read_calls"]
        cur["n_bash"] += r["n_bash_calls"]
        cur["n_errors"] += r["n_tool_errors"]

    pass_by_key = {(r["batch"], r["eval_id"]): r for r in per_eval}
    rows = []
    for (batch, eid, cond), agg in sorted(by_key.items()):
        per = pass_by_key.get((batch, eid))
        if per is None:
            continue
        cat = cats.get(eid, {})
        passed = (
            int(per["ws_pass"]) if cond == "with_skill" else int(per["bs_pass"])
        )
        # Sort and join refs/scripts for stable CSV output.
        refs = ";".join(f"{ref}({n})" for ref, n in sorted(agg["ref_opens"].items()))
        scripts = ";".join(
            f"{s}({n})" for s, n in sorted(agg["script_executions"].items())
        )
        rows.append(
            {
                "eval_id": eid,
                "batch": batch,
                "eval_name": per["eval_name"],
                "stage": cat.get("stage", "unknown"),
                "tier": cat.get("tier", "unknown"),
                "difficulty": cat.get("difficulty", "unknown"),
                "condition": cond,
                "full_pass": passed,
                "n_read": agg["n_read"],
                "n_bash": agg["n_bash"],
                "n_errors": agg["n_errors"],
                "refs_opened": refs,
                "scripts_run": scripts,
            }
        )
    _write_csv(
        data_path("per_eval_routing.csv"),
        [
            *EVAL_METADATA_COLUMNS,
            "condition",
            "full_pass",
            "n_read",
            "n_bash",
            "n_errors",
            "refs_opened",
            "scripts_run",
        ],
        rows,
    )

def write_top_skill_wins_csv(
    cats: EvalCategories, per_eval: list[PerEvalResult]
) -> None:
    """Per-eval expectation deltas, sorted by delta desc.

    Covers the top-N table in SUMMARY.md and the figure-only data behind
    plot 10. Sorted by skill - baseline expectation delta (descending) so
    the largest skill wins are at the top, the largest skill losses (if
    any) at the bottom.
    """

    rows = []
    items = []
    for r in per_eval:
        if r["ws_exp_t"] == 0:
            continue
        ws_pct = 100 * r["ws_exp_p"] / r["ws_exp_t"]
        bs_pct = 100 * r["bs_exp_p"] / r["bs_exp_t"] if r["bs_exp_t"] else 0
        cat = cats.get(r["eval_id"], {})
        items.append(
            (
                ws_pct - bs_pct,
                r["eval_id"],
                r["eval_name"],
                r["batch"],
                cat.get("stage", "unknown"),
                cat.get("tier", "unknown"),
                cat.get("difficulty", "unknown"),
                int(r["ws_pass"]),
                int(r["bs_pass"]),
                ws_pct,
                bs_pct,
            )
        )
    items.sort(key=lambda x: -x[0])
    for rank, item in enumerate(items, start=1):
        delta, eid, name, batch, stage, tier, diff, wsp, bsp, wsr, bsr = item
        rows.append(
            {
                "rank": rank,
                "eval_id": eid,
                "batch": batch,
                "eval_name": name,
                "stage": stage,
                "tier": tier,
                "difficulty": diff,
                "ws_pass": wsp,
                "bs_pass": bsp,
                "ws_expectation_rate": f"{wsr:.1f}",
                "bs_expectation_rate": f"{bsr:.1f}",
                "delta_expectation_pp": f"{delta:.1f}",
            }
        )
    _write_csv(
        data_path("top_skill_wins.csv"),
        [
            "eval_id",
            "batch",
            "eval_name",
            "stage",
            "tier",
            "difficulty",
            "rank",
            "ws_pass",
            "bs_pass",
            "ws_expectation_rate",
            "bs_expectation_rate",
            "delta_expectation_pp",
        ],
        rows,
    )

def _classify_eval_failure_mode(batch: int, eval_id: int) -> str:
    """Inspect with_skill grading.json to label a failed eval's dominant failure mode.

    Returns one of:
    - "rubric"   — most failed expectations are required_substring /
                   forbidden_substring (literal-token strictness)
    - "content"  — most failed expectations are behavioral_check
                   (LLM-judge said the answer's substance was wrong)
    - "mixed"    — even split or grading.json missing
    The label is heuristic, not a verdict — use it to filter, not to grade.
    """
    for d in (WORKSPACE / f"iteration-{batch}").glob(f"eval-{eval_id:03d}-*"):
        gp = d / "with_skill" / "grading.json"
        if not gp.is_file():
            continue
        try:
            grading = json.loads(gp.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        n_subs = n_beh = 0
        for e in grading.get("expectations", []):
            if e.get("passed"):
                continue
            text = e.get("text", "")
            if text.startswith(("required_substring:", "forbidden_substring:")):
                n_subs += 1
            elif text.startswith("behavioral_check:"):
                n_beh += 1
        if n_subs == 0 and n_beh == 0:
            return "mixed"
        if n_subs > n_beh:
            return "rubric"
        if n_beh > n_subs:
            return "content"
        return "mixed"
    return "mixed"

def write_reference_effectiveness_csv(
    records: list[TranscriptRecord] | None,
    per_eval: list[PerEvalResult],
    cats: EvalCategories,
) -> None:
    """Per-reference: how often loaded, pass-rate when loaded, who failed despite loading.

    Distinguishes "reference exists but is ineffective" (loaded but eval still
    failed) from "reference not discovered" (eval failed AND ref not loaded).

    The `failed_modes` column (n_rubric / n_content / n_mixed) deflates apparent
    weakness: a reference flagged as "low pass rate" may simply be loaded by
    evals whose rubrics rely on literal substrings the agent didn't happen to
    cite. Use `failed_modes` to separate "needs reference content fix" (high
    n_content) from "rubric strictness made the ref look weak" (high n_rubric).
    """
    if records is None:
        unlink_outputs("reference_effectiveness.csv", "13_reference_effectiveness.png")
        return
    pass_by_eval: dict[int, bool] = {r["eval_id"]: bool(r["ws_pass"]) for r in per_eval}
    name_by_eval: dict[int, str] = {r["eval_id"]: r["eval_name"] for r in per_eval}
    batch_by_eval: dict[int, int] = {r["eval_id"]: r["batch"] for r in per_eval}

    # ws_loads_by_eval[ref] = set of eval_ids whose ws transcripts opened it.
    ws_loads_by_eval: dict[str, set[int]] = defaultdict(set)
    for r in records:
        if r["condition"] != "with_skill":
            continue
        for ref in r["ref_opens"]:
            ws_loads_by_eval[ref].add(r["eval_id"])

    # Cache failure-mode classification — many refs share the same failed evals.
    failure_mode_cache: dict[int, str] = {}

    def get_mode(eid: int) -> str:
        if eid not in failure_mode_cache:
            failure_mode_cache[eid] = _classify_eval_failure_mode(
                batch_by_eval.get(eid, 0), eid
            )
        return failure_mode_cache[eid]

    diff_score = {"easy": 1, "medium": 2, "hard": 3, "unknown": 2}

    rows = []
    payload = []
    for ref, eids in ws_loads_by_eval.items():
        passed = sum(1 for eid in eids if pass_by_eval.get(eid, False))
        failed = len(eids) - passed
        rate = 100 * passed / len(eids) if eids else 0.0
        # Mean difficulty score (1=easy, 2=medium, 3=hard) of evals that
        # opened this ref. A high-load ref with low avg difficulty is mostly
        # carrying easy questions; one with high avg difficulty is shouldering
        # the hard stuff and a 70% pass rate is more impressive than it looks.
        diffs = [
            diff_score.get(cats.get(eid, {}).get("difficulty", "unknown"), 2)
            for eid in eids
        ]
        avg_diff = sum(diffs) / len(diffs) if diffs else 2.0
        failed_eids = [eid for eid in eids if not pass_by_eval.get(eid, False)]
        mode_counts = Counter(get_mode(eid) for eid in failed_eids)
        modes_str = (
            f"rubric={mode_counts.get('rubric', 0)};"
            f"content={mode_counts.get('content', 0)};"
            f"mixed={mode_counts.get('mixed', 0)}"
        )
        failed_examples = sorted(failed_eids, key=lambda e: name_by_eval.get(e, ""))[:5]
        sample = ";".join(
            f"{eid}:{name_by_eval.get(eid, '?')}[{get_mode(eid)}]"
            for eid in failed_examples
        )
        rows.append(
            {
                "reference": ref,
                "ws_evals_loaded": len(eids),
                "ws_pass_when_loaded": passed,
                "ws_fail_when_loaded": failed,
                "pass_rate_when_loaded": f"{rate:.1f}",
                "avg_difficulty_when_loaded": f"{avg_diff:.2f}",
                "failed_modes": modes_str,
                "failed_evals_sample": sample,
            }
        )
        payload.append((ref, len(eids), passed, failed, rate))
    _write_csv(
        data_path("reference_effectiveness.csv"),
        [
            "reference",
            "ws_evals_loaded",
            "ws_pass_when_loaded",
            "ws_fail_when_loaded",
            "pass_rate_when_loaded",
            "avg_difficulty_when_loaded",
            "failed_modes",
            "failed_evals_sample",
        ],
        rows,
    )

    # Plot 13: bar chart sorted by load count, color by pass rate.
    if not payload:
        return
    payload.sort(key=lambda x: -x[1])
    payload = [p for p in payload if p[0] != "SKILL.md"][:25]
    refs = [p[0] for p in payload]
    loads = [p[1] for p in payload]
    rates = [p[4] for p in payload]
    fig, ax = plt.subplots(figsize=(11, 9), constrained_layout=True)
    y = np.arange(len(refs))
    cmap = plt.cm.RdYlGn
    bars = ax.barh(y, loads, color=[cmap(r / 100) for r in rates], edgecolor="white")
    for i, (bar, rate, n_pass, n_fail) in enumerate(
        zip(bars, rates, [p[2] for p in payload], [p[3] for p in payload], strict=True)
    ):
        ax.text(
            bar.get_width() + 0.4,
            i,
            f"{n_pass}/{n_pass + n_fail} pass ({rate:.0f}%)",
            va="center",
            fontsize=9,
        )
    ax.set_yticks(y)
    ax.set_yticklabels(refs, fontsize=10, family="monospace")
    ax.invert_yaxis()
    ax.set_xlim(0, max(loads) * 1.5 if loads else 10)
    ax.set_xlabel("# of distinct ws evals that opened the reference", fontsize=10)
    setup_axes(ax, "Reference effectiveness — loads vs pass rate when loaded")
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(0, 100))
    cbar = fig.colorbar(sm, ax=ax, shrink=0.5, pad=0.02)
    cbar.set_label("ws full-pass rate when loaded (%)", fontsize=9)
    ax.grid(axis="x", alpha=0.3, linestyle=":")
    fig.suptitle(
        "Did agents that opened a reference actually pass? (caveat: confounded by routing — high-rate refs may just be opened on easy evals)",
        fontsize=10,
        y=1.01,
    )
    fig.savefig(figure_path("13_reference_effectiveness.png"), dpi=160, bbox_inches="tight")
    plt.close(fig)

def write_cost_effectiveness_csv(
    cats: EvalCategories,
    per_eval: list[PerEvalResult],
    timing: dict[tuple[int, int, str], int],
) -> None:
    """Per-eval cost-vs-effect: extra tokens for ws over bs vs expectation Δ.

    Identifies high-cost / no-gain evals (skill spent tokens, no improvement)
    and high-value interventions (skill cheap and unlocking the answer).
    Skips evals whose ws or bs timing is missing from the run.
    """
    rows = []
    points = []
    for r in per_eval:
        ws_tok = timing.get((r["batch"], r["eval_id"], "with_skill"))
        bs_tok = timing.get((r["batch"], r["eval_id"], "without_skill"))
        if ws_tok is None or bs_tok is None:
            continue
        ws_pct = 100 * r["ws_exp_p"] / r["ws_exp_t"] if r["ws_exp_t"] else 0.0
        bs_pct = 100 * r["bs_exp_p"] / r["bs_exp_t"] if r["bs_exp_t"] else 0.0
        delta = ws_pct - bs_pct
        cat = cats.get(r["eval_id"], {})
        rows.append(
            {
                "eval_id": r["eval_id"],
                "batch": r["batch"],
                "eval_name": r["eval_name"],
                "stage": cat.get("stage", "unknown"),
                "tier": cat.get("tier", "unknown"),
                "difficulty": cat.get("difficulty", "unknown"),
                "ws_tokens": ws_tok,
                "bs_tokens": bs_tok,
                "extra_tokens": ws_tok - bs_tok,
                "delta_expectation_pp": f"{delta:.1f}",
                "both_pass": int(r["ws_pass"] and r["bs_pass"]),
                "skill_only": int(r["ws_pass"] and not r["bs_pass"]),
                "baseline_only": int(r["bs_pass"] and not r["ws_pass"]),
                "both_fail": int(not r["ws_pass"] and not r["bs_pass"]),
            }
        )
        points.append(
            (ws_tok - bs_tok, delta, cat.get("stage", "unknown"), r["eval_id"])
        )
    _write_csv(
        data_path("cost_effectiveness_per_eval.csv"),
        [
            *EVAL_METADATA_COLUMNS,
            "ws_tokens",
            "bs_tokens",
            "extra_tokens",
            "delta_expectation_pp",
            "both_pass",
            "skill_only",
            "baseline_only",
            "both_fail",
        ],
        rows,
    )

    if not points:
        unlink_outputs("14_cost_effectiveness_scatter.png")
        return

    fig, ax = plt.subplots(figsize=(10, 7), constrained_layout=True)
    stages = sorted({p[2] for p in points})
    palette = plt.cm.tab20(np.linspace(0, 1, len(stages)))
    for stage, color in zip(stages, palette, strict=True):
        xs = [p[0] / 1000 for p in points if p[2] == stage]
        ys = [p[1] for p in points if p[2] == stage]
        ax.scatter(xs, ys, label=stage, color=color, s=50, alpha=0.7, edgecolors="white", linewidths=0.5)
    ax.axhline(0, color="black", linewidth=0.7, linestyle="--")
    ax.axvline(0, color="black", linewidth=0.7, linestyle="--")
    # Annotate the cheap-win and expensive-no-gain corners.
    cheap_wins = sorted(
        (p for p in points if p[1] >= 30 and p[0] < 30000),
        key=lambda p: -p[1],
    )[:5]
    expensive_flat = sorted(
        (p for p in points if p[1] <= 0 and p[0] > 30000),
        key=lambda p: p[1],
    )[:5]
    for x, y, _stage, eid in cheap_wins + expensive_flat:
        ax.annotate(
            f"#{eid}", (x / 1000, y), fontsize=8, ha="left", va="bottom",
            xytext=(3, 3), textcoords="offset points",
        )
    ax.set_xlabel("extra tokens (ws − bs), thousands", fontsize=10)
    ax.set_ylabel("expectation delta (pp)", fontsize=10)
    setup_axes(ax, "Cost-effectiveness per eval — where does the skill pay off?")
    ax.legend(loc="lower right", frameon=False, fontsize=8, ncol=2)
    ax.grid(alpha=0.3, linestyle=":")
    ax.text(
        0.02, 0.98,
        "↑ skill helps  →  expensive\n← skill cheaper  →  ↓ skill hurts",
        transform=ax.transAxes, va="top", ha="left", fontsize=9, style="italic", color="#666666",
    )
    fig.suptitle("Where does the skill's extra cost actually buy correctness?", fontsize=12, y=1.01)
    fig.savefig(figure_path("14_cost_effectiveness_scatter.png"), dpi=160, bbox_inches="tight")
    plt.close(fig)

def write_outcome_by_category_csv(
    cats: EvalCategories, per_eval: list[PerEvalResult]
) -> None:
    """Per stage / per tier outcome cross-tab.

    Each (stage, tier) bucket gets counts of (both_pass, skill_only,
    baseline_only, both_fail). Tells you where the skill is uniquely helpful
    vs where the eval remains hard for everyone.
    """
    # skill_rescue_rate = skill_only / (skill_only + baseline_only + both_fail).
    # The fraction of evals NOT solved by baseline that the skill uniquely
    # rescues. A 100% rate means: anywhere bs fails in this category, the
    # skill always saves it. A 25% rate means: even when given the skill,
    # the agent co-fails on most bs failures — the category is hard for both.
    rows = []
    plot_data = {}
    for kind in ("stage", "tier"):
        grouped: dict[str, list[PerEvalResult]] = defaultdict(list)
        for r in per_eval:
            c = cats.get(r["eval_id"], {}).get(kind, "unknown")
            grouped[c].append(r)
        agg = {c: count_outcomes(vs) for c, vs in grouped.items()}
        plot_data[kind] = agg
        for c, ctr in sorted(agg.items(), key=lambda x: -x[1]["__total"]):
            unrescued = ctr["skill_only"] + ctr["baseline_only"] + ctr["both_fail"]
            rescue = (
                round(100 * ctr["skill_only"] / unrescued, 1) if unrescued else 0.0
            )
            rows.append(
                {
                    "category_kind": kind,
                    "category": c,
                    "n_evals": ctr["__total"],
                    "both_pass": ctr["both_pass"],
                    "skill_only": ctr["skill_only"],
                    "baseline_only": ctr["baseline_only"],
                    "both_fail": ctr["both_fail"],
                    "skill_rescue_rate_pct": rescue,
                }
            )
    _write_csv(
        data_path("outcome_by_category.csv"),
        [
            "category_kind",
            "category",
            "n_evals",
            "both_pass",
            "skill_only",
            "baseline_only",
            "both_fail",
            "skill_rescue_rate_pct",
        ],
        rows,
    )

    # Plot 15: stacked bars per stage (skill-only is the "where the skill earned its keep" signal).
    stage_agg = plot_data["stage"]
    if not stage_agg:
        return
    sorted_stages = sorted(stage_agg.items(), key=lambda x: -x[1]["skill_only"])
    labels = [s for s, _ in sorted_stages]
    bp = [s[1]["both_pass"] for s in sorted_stages]
    so = [s[1]["skill_only"] for s in sorted_stages]
    bo = [s[1]["baseline_only"] for s in sorted_stages]
    bf = [s[1]["both_fail"] for s in sorted_stages]

    fig, ax = plt.subplots(figsize=(11, 6), constrained_layout=True)
    y = np.arange(len(labels))
    bottom = np.zeros(len(labels))
    for vals, lab, color in [
        (bp, "both pass", WONG["both_pass"]),
        (so, "skill only (skill earned its keep)", WONG["delta_pos"]),
        (bo, "baseline only (skill regression)", WONG["delta_neg"]),
        (bf, "both fail (still hard)", WONG["both_fail"]),
    ]:
        ax.barh(y, vals, left=bottom, label=lab, color=color, edgecolor="white")
        for i, v in enumerate(vals):
            if v > 0:
                ax.text(
                    bottom[i] + v / 2, i, str(v), ha="center", va="center",
                    fontsize=9, color="white" if lab != "both pass" else "black",
                    fontweight="bold",
                )
        bottom = bottom + np.array(vals)
    ax.set_yticks(y)
    ax.set_yticklabels([f"{lab}  (n={s[1]['__total']})" for lab, s in zip(labels, sorted_stages, strict=True)], fontsize=10)
    ax.invert_yaxis()
    ax.set_xlabel("number of evals", fontsize=10)
    setup_axes(ax, "Outcome by stage — where did the skill uniquely help?")
    ax.legend(loc="upper left", frameon=False, fontsize=9, bbox_to_anchor=(0, 1.08), ncol=2)
    ax.grid(axis="x", alpha=0.3, linestyle=":")
    fig.suptitle("Skill-only wins concentrate where the skill matters most", fontsize=12, y=1.04)
    fig.savefig(figure_path("15_outcome_by_category.png"), dpi=160, bbox_inches="tight")
    plt.close(fig)

def write_baseline_source_split_json(
    per_eval: list[PerEvalResult], records: list[TranscriptRecord] | None
) -> None:
    """3-way split: baseline-no-source / baseline-source-touched / with-skill.

    Tests whether the skill's lift is just "agent reads source" or whether
    routing+workflow add something on top. Round-c expectation per SUMMARY:
    bs+source still trails ws meaningfully.
    """
    if records is None:
        unlink_outputs("baseline_source_split.json", "16_baseline_source_split.png")
        return
    bs_source_evals: set[int] = set()
    for r in records:
        if r["condition"] != "without_skill":
            continue
        if r["spyglass_src_reads"] > 0:
            bs_source_evals.add(r["eval_id"])
    bs_no_source_evals = {r["eval_id"] for r in per_eval} - bs_source_evals

    def stats(eids: set[int], cond: str) -> dict:
        subset = [r for r in per_eval if r["eval_id"] in eids]
        if not subset:
            return {"n": 0, "full_pass": 0, "full_pass_rate": 0.0}
        if cond == "with_skill":
            n_pass = sum(1 for r in subset if r["ws_pass"])
        else:
            n_pass = sum(1 for r in subset if r["bs_pass"])
        return {
            "n": len(subset),
            "full_pass": n_pass,
            "full_pass_rate": round(100 * n_pass / len(subset), 2),
        }

    payload = {
        "baseline_no_source_touched": stats(bs_no_source_evals, "without_skill"),
        "baseline_source_touched": stats(bs_source_evals, "without_skill"),
        "with_skill_all": stats({r["eval_id"] for r in per_eval}, "with_skill"),
        "note": (
            "Splits the without_skill condition by whether the agent's transcript "
            "touched /spyglass/src/ (Read, Bash, Glob, LS, Grep) or WebFetched the "
            "Spyglass GitHub. Tests whether the skill's lift reduces to 'agent has "
            "source access' — if bs_source_touched approaches with_skill, the skill "
            "is doing source delivery; if not, the skill adds routing/workflow value "
            "beyond source access."
        ),
    }
    (data_path("baseline_source_split.json")).write_text(json.dumps(payload, indent=2) + "\n")

    # Plot 16: three bars.
    groups = [
        ("baseline\nno source", payload["baseline_no_source_touched"]),
        ("baseline\nsource touched", payload["baseline_source_touched"]),
        ("with skill\n(all)", payload["with_skill_all"]),
    ]
    fig, ax = plt.subplots(figsize=(8, 5.5), constrained_layout=True)
    x = np.arange(len(groups))
    rates = [g[1]["full_pass_rate"] for g in groups]
    bars = ax.bar(x, rates, color=[WONG["bs"], WONG["neutral"], WONG["ws"]], edgecolor="white", width=0.6)
    for bar, (_, g) in zip(bars, groups, strict=True):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            g["full_pass_rate"] + 1.5,
            f"{g['full_pass']}/{g['n']}\n({g['full_pass_rate']:.1f}%)",
            ha="center", fontsize=10, fontweight="bold",
        )
    ax.set_xticks(x)
    ax.set_xticklabels([g[0] for g in groups], fontsize=10)
    ax.set_ylim(0, 110)
    ax.set_yticks([0, 25, 50, 75, 100])
    setup_axes(ax, "Three-way split — does the skill add value beyond source access?", ylabel="full-eval pass rate (%)")
    ax.grid(axis="y", alpha=0.3, linestyle=":")
    fig.suptitle("Skill's lift over baseline-with-source isolates routing/workflow value", fontsize=11, y=1.02)
    fig.savefig(figure_path("16_baseline_source_split.png"), dpi=160, bbox_inches="tight")
    plt.close(fig)

def write_headroom_evals_csv(
    cats: EvalCategories, per_eval: list[PerEvalResult]
) -> None:
    """Both-fail evals where neither ws nor bs passed, excluding adversarial-tier.

    Adversarial-tier both-fails are usually intended (the eval tests that the
    agent refuses, so a passing response is a refusal — both conditions
    refusing is a measurement-success-but-rubric-fail). The remaining
    both-fail set is the next refactor's biggest improvement headroom: improvements
    here move neither ws nor bs from the prior sweep, so any movement is new
    correctness gained.
    """
    rows = []
    n_total = 0
    for r in per_eval:
        if r["ws_pass"] or r["bs_pass"]:
            continue
        cat = cats.get(r["eval_id"], {})
        if cat.get("tier") == "adversarial":
            continue
        n_total += 1
        ws_pct = 100 * r["ws_exp_p"] / r["ws_exp_t"] if r["ws_exp_t"] else 0.0
        bs_pct = 100 * r["bs_exp_p"] / r["bs_exp_t"] if r["bs_exp_t"] else 0.0
        rows.append(
            {
                "eval_id": r["eval_id"],
                "batch": r["batch"],
                "eval_name": r["eval_name"],
                "stage": cat.get("stage", "unknown"),
                "tier": cat.get("tier", "unknown"),
                "difficulty": cat.get("difficulty", "unknown"),
                "ws_expectation_rate": f"{ws_pct:.1f}",
                "bs_expectation_rate": f"{bs_pct:.1f}",
            }
        )
    _write_csv(
        data_path("headroom_evals.csv"),
        [
            *EVAL_METADATA_COLUMNS,
            "ws_expectation_rate",
            "bs_expectation_rate",
        ],
        rows,
    )

def write_eval_coverage_csv(cats: EvalCategories) -> None:
    """Stage × tier eval-count matrix. Catches over/under-tested categories."""
    by_pair: Counter = Counter()
    for c in cats.values():
        by_pair[(c.get("stage", "unknown"), c.get("tier", "unknown"))] += 1
    rows = [
        {"stage": s, "tier": t, "n_evals": n}
        for (s, t), n in sorted(by_pair.items(), key=lambda x: (-x[1], x[0], x[1]))
    ]
    _write_csv(data_path("eval_coverage.csv"), ["stage", "tier", "n_evals"], rows)

    # Plot 17: heatmap of stage × tier counts.
    stages = sorted({s for s, _ in by_pair})
    tiers = sorted({t for _, t in by_pair})
    if not stages or not tiers:
        return
    matrix = np.zeros((len(stages), len(tiers)), dtype=int)
    for (s, t), n in by_pair.items():
        matrix[stages.index(s), tiers.index(t)] = n

    fig, ax = plt.subplots(figsize=(max(8, len(tiers) * 0.7), max(6, len(stages) * 0.5)), constrained_layout=True)
    masked = np.ma.masked_equal(matrix, 0)
    im = ax.imshow(masked, cmap="Blues", aspect="auto")
    ax.set_xticks(np.arange(len(tiers)))
    ax.set_xticklabels(tiers, rotation=40, ha="right", fontsize=9)
    ax.set_yticks(np.arange(len(stages)))
    ax.set_yticklabels(stages, fontsize=10)
    for i in range(len(stages)):
        for j in range(len(tiers)):
            n = matrix[i, j]
            if n > 0:
                ax.text(j, i, str(n), ha="center", va="center", fontsize=10,
                        color="white" if n > matrix.max() / 2 else "black")
    fig.colorbar(im, ax=ax, shrink=0.6, label="eval count")
    setup_axes(ax, "Eval coverage by stage × tier — where is the suite under-/over-testing?")
    fig.suptitle("Future sweeps should add evals to under-covered cells", fontsize=11, y=1.02)
    fig.savefig(figure_path("17_eval_coverage_map.png"), dpi=160, bbox_inches="tight")
    plt.close(fig)

def write_failure_taxonomy_stub_csv(
    cats: EvalCategories, per_eval: list[PerEvalResult]
) -> None:
    """Auto-generated stub for human annotation of with_skill failures.

    For each ws-failed eval, writes a row with empty `failure_type` and
    `notes` columns. Maintainers can fill these in manually
    (suggested values: wrong_factual, omitted_step, over_skeptical,
    wrong_tool, right_ref_no_verify, rubric_friction, eval_issue) and
    plot 18 will then aggregate them. Existing rows are preserved across
    re-runs so annotations don't get clobbered.
    """
    target = data_path("failure_taxonomy.csv")
    existing: dict[int, dict[str, str]] = {}
    if target.is_file():
        for row in csv.DictReader(io.StringIO(target.read_text())):
            eid = row.get("eval_id", "")
            if eid.isdigit():
                existing[int(eid)] = {
                    "failure_type": row.get("failure_type", ""),
                    "notes": row.get("notes", ""),
                }

    rows = []
    for r in per_eval:
        if r["ws_pass"]:
            continue
        cat = cats.get(r["eval_id"], {})
        prior = existing.get(r["eval_id"], {"failure_type": "", "notes": ""})
        rows.append(
            {
                "eval_id": r["eval_id"],
                "batch": r["batch"],
                "eval_name": r["eval_name"],
                "stage": cat.get("stage", "unknown"),
                "tier": cat.get("tier", "unknown"),
                "difficulty": cat.get("difficulty", "unknown"),
                "failure_type": prior["failure_type"],
                "notes": prior["notes"],
            }
        )
    _write_csv(
        target,
        [
            *EVAL_METADATA_COLUMNS,
            "failure_type",
            "notes",
        ],
        rows,
    )

    # Plot 18: render a placeholder until annotations exist, so the numbered
    # figure sequence stays complete.
    types = [r for r in rows if r["failure_type"]]
    if not types:
        fig, ax = plt.subplots(figsize=(9, 5), constrained_layout=True)
        ax.axis("off")
        ax.text(
            0.5,
            0.58,
            "No failure taxonomy annotations yet",
            ha="center",
            va="center",
            fontsize=14,
            fontweight="bold",
            transform=ax.transAxes,
        )
        ax.text(
            0.5,
            0.42,
            "Fill failure_taxonomy.csv and rerun make_plots.py.",
            ha="center",
            va="center",
            fontsize=11,
            transform=ax.transAxes,
        )
        fig.savefig(figure_path("18_failure_taxonomy.png"), dpi=160, bbox_inches="tight")
        plt.close(fig)
        return
    type_counts: Counter = Counter(t["failure_type"] for t in types)
    fig, ax = plt.subplots(figsize=(9, 5), constrained_layout=True)
    sorted_types = type_counts.most_common()
    labels = [t for t, _ in sorted_types]
    counts = [n for _, n in sorted_types]
    bars = ax.barh(np.arange(len(labels)), counts, color=WONG["delta_neg"], edgecolor="white")
    for bar, n in zip(bars, counts, strict=True):
        ax.text(bar.get_width() + 0.2, bar.get_y() + bar.get_height() / 2,
                str(n), va="center", fontsize=10, fontweight="bold")
    ax.set_yticks(np.arange(len(labels)))
    ax.set_yticklabels(labels, fontsize=10)
    ax.invert_yaxis()
    ax.set_xlabel("# of with_skill failures", fontsize=10)
    setup_axes(ax, f"With-skill failure taxonomy ({sum(counts)} of {sum(1 for r in per_eval if not r['ws_pass'])} ws-failed evals annotated)")
    ax.grid(axis="x", alpha=0.3, linestyle=":")
    fig.suptitle("Where to invest skill maintenance effort", fontsize=11, y=1.02)
    fig.savefig(figure_path("18_failure_taxonomy.png"), dpi=160, bbox_inches="tight")
    plt.close(fig)

def write_reference_expected_used_csv(
    per_eval: list[PerEvalResult],
    records: list[TranscriptRecord] | None,
    expected_refs: ExpectedResources,
) -> None:
    """Reference-expected-vs-used analysis. Skipped unless evals.json has labels.

    Per (reference, status), counts how often it was expected and how often
    actually opened. Separates routing failures (expected ref not opened)
    from reference weakness (expected ref opened but answer still failed)
    from overuse (distractor ref opened) from eval mismatch (expected ref
    not opened but answer passed).
    """
    if not expected_refs or records is None:
        unlink_outputs("reference_expected_used.csv", "19_reference_expected_used.png")
        return
    pass_by_eval: dict[int, bool] = {r["eval_id"]: bool(r["ws_pass"]) for r in per_eval}
    ws_opens_by_eval: dict[int, set[str]] = defaultdict(set)
    for r in records:
        if r["condition"] != "with_skill":
            continue
        for ref in r["ref_opens"]:
            ws_opens_by_eval[r["eval_id"]].add(ref)

    tally: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"expected": 0, "used": 0, "missed": 0, "passed_when_used": 0, "failed_when_used": 0}
    )
    for eid, blocks in expected_refs.items():
        opened = ws_opens_by_eval.get(eid, set())
        passed = pass_by_eval.get(eid, False)
        for status, refs in blocks.items():
            for ref in refs:
                t = tally[(ref, status)]
                t["expected"] += 1
                if ref in opened:
                    t["used"] += 1
                    if passed:
                        t["passed_when_used"] += 1
                    else:
                        t["failed_when_used"] += 1
                else:
                    t["missed"] += 1

    rows = []
    for (ref, status), t in sorted(tally.items()):
        rate = 100 * t["passed_when_used"] / t["used"] if t["used"] else 0.0
        rows.append(
            {
                "reference": ref,
                "status": status,
                "expected_count": t["expected"],
                "used_count": t["used"],
                "missed_count": t["missed"],
                "used_pass_rate": f"{rate:.1f}",
            }
        )
    _write_csv(
        data_path("reference_expected_used.csv"),
        [
            "reference",
            "status",
            "expected_count",
            "used_count",
            "missed_count",
            "used_pass_rate",
        ],
        rows,
    )

    # Plot 19: heatmap of (reference × status) discoverability if any annotations.
    refs = sorted({r for r, _ in tally})
    statuses = ["required", "optional", "distractor"]
    fig, axes = plt.subplots(1, 2, figsize=(13, max(4, len(refs) * 0.4)), constrained_layout=True)
    for ax_i, (metric, title, cmap) in enumerate([
        ("discoverability", "discoverability (used / expected)", "Greens"),
        ("effectiveness", "pass rate when expected ref was used", "RdYlGn"),
    ]):
        ax = axes[ax_i]
        m = np.full((len(refs), len(statuses)), np.nan)
        for i, ref in enumerate(refs):
            for j, status in enumerate(statuses):
                t = tally.get((ref, status))
                if not t or t["expected"] == 0:
                    continue
                if metric == "discoverability":
                    m[i, j] = 100 * t["used"] / t["expected"]
                elif t["used"] > 0:
                    m[i, j] = 100 * t["passed_when_used"] / t["used"]
        im = ax.imshow(m, cmap=cmap, vmin=0, vmax=100, aspect="auto")
        ax.set_xticks(np.arange(len(statuses)))
        ax.set_xticklabels(statuses, fontsize=10)
        ax.set_yticks(np.arange(len(refs)))
        ax.set_yticklabels(refs, fontsize=8, family="monospace")
        for i in range(len(refs)):
            for j in range(len(statuses)):
                if not np.isnan(m[i, j]):
                    ax.text(j, i, f"{m[i, j]:.0f}", ha="center", va="center",
                            fontsize=8, color="black")
        fig.colorbar(im, ax=ax, shrink=0.5, label="%")
        setup_axes(ax, title)
    fig.suptitle(
        "Expected vs actual reference use — routing-failure / reference-weakness diagnostic",
        fontsize=11, y=1.02,
    )
    fig.savefig(figure_path("19_reference_expected_used.png"), dpi=160, bbox_inches="tight")
    plt.close(fig)

def _expected_required(blocks: ExpectedResourceBlock) -> set[str]:
    """Resources that should count as expected-positive for a confusion matrix."""
    return set(blocks.get("required", []))

def _expected_optional(blocks: ExpectedResourceBlock) -> set[str]:
    """Resources that are useful but should not create false negatives."""
    return set(blocks.get("optional", []))

def _expected_negative(blocks: ExpectedResourceBlock) -> set[str]:
    """Resources explicitly labeled as should-not-call distractors."""
    return set(blocks.get("distractor", []))

def write_expected_call_confusion(
    *,
    per_eval: list[PerEvalResult],
    records: list[TranscriptRecord] | None,
    expected: ExpectedResources,
    kind: str,
) -> None:
    """Write called-vs-expected confusion matrices for references or scripts.

    The unit of analysis is a labeled eval-resource pair in the with_skill
    condition. Required resources are positives. Distractors and unlabeled
    resources are negatives. Optional resources are tracked separately but do
    not affect precision/recall. For scripts, "called" means executed via Bash;
    source-only reads do not count.
    """
    if not expected or records is None:
        prefix = "20_reference" if kind == "reference" else "21_script"
        unlink_outputs(f"{kind}_call_confusion.csv", f"{prefix}_call_confusion.png")
        return

    pass_by_eval: dict[int, bool] = {r["eval_id"]: bool(r["ws_pass"]) for r in per_eval}
    observed_by_eval: dict[int, set[str]] = defaultdict(set)
    for r in records:
        if r["condition"] != "with_skill":
            continue
        if kind == "reference":
            observed_by_eval[r["eval_id"]].update(
                ref for ref in r["ref_opens"] if ref != "SKILL.md"
            )
        elif kind == "script":
            observed_by_eval[r["eval_id"]].update(r["script_executions"])
        else:
            raise ValueError(f"unknown confusion kind: {kind}")

    labeled_evals = sorted(expected)
    universe = set()
    for eid in labeled_evals:
        universe |= _expected_required(expected[eid])
        universe |= _expected_optional(expected[eid])
        universe |= _expected_negative(expected[eid])
        universe |= observed_by_eval.get(eid, set())
    if kind == "script":
        universe |= {s for s in TRACKED_SCRIPTS if TRACKED_SCRIPT_ROLES[s] == "agent"}
    universe.discard("SKILL.md")
    if not universe:
        prefix = "20_reference" if kind == "reference" else "21_script"
        unlink_outputs(f"{kind}_call_confusion.csv", f"{prefix}_call_confusion.png")
        return

    per_resource: dict[str, dict[str, int]] = {
        r: {
            "expected_called": 0,
            "expected_not_called": 0,
            "unexpected_called": 0,
            "unexpected_not_called": 0,
            "optional_called": 0,
            "optional_not_called": 0,
            "failed_expected_not_called": 0,
            "failed_expected_called": 0,
            "passed_unexpected_called": 0,
        }
        for r in sorted(universe)
    }

    for eid in labeled_evals:
        positives = _expected_required(expected[eid])
        optional = _expected_optional(expected[eid])
        negatives = set(universe) - positives - optional
        called = observed_by_eval.get(eid, set())
        passed = pass_by_eval.get(eid, False)
        for resource in positives:
            if resource in called:
                per_resource[resource]["expected_called"] += 1
                if not passed:
                    per_resource[resource]["failed_expected_called"] += 1
            else:
                per_resource[resource]["expected_not_called"] += 1
                if not passed:
                    per_resource[resource]["failed_expected_not_called"] += 1
        for resource in optional:
            if resource in called:
                per_resource[resource]["optional_called"] += 1
            else:
                per_resource[resource]["optional_not_called"] += 1
        for resource in negatives:
            if resource in called:
                per_resource[resource]["unexpected_called"] += 1
                if passed:
                    per_resource[resource]["passed_unexpected_called"] += 1
            else:
                per_resource[resource]["unexpected_not_called"] += 1

    rows = []
    totals = Counter()
    for resource, counts in per_resource.items():
        tp = counts["expected_called"]
        fn = counts["expected_not_called"]
        fp = counts["unexpected_called"]
        tn = counts["unexpected_not_called"]
        precision = 100 * tp / (tp + fp) if tp + fp else 0.0
        recall = 100 * tp / (tp + fn) if tp + fn else 0.0
        fpr = 100 * fp / (fp + tn) if fp + tn else 0.0
        rows.append(
            {
                "resource": resource,
                "kind": kind,
                "n_labeled_evals": len(labeled_evals),
                "expected_called": tp,
                "expected_not_called": fn,
                "optional_called": counts["optional_called"],
                "optional_not_called": counts["optional_not_called"],
                "unexpected_called": fp,
                "unexpected_not_called": tn,
                "precision": f"{precision:.1f}",
                "recall": f"{recall:.1f}",
                "false_positive_rate": f"{fpr:.1f}",
                "failed_expected_not_called": counts["failed_expected_not_called"],
                "failed_expected_called": counts["failed_expected_called"],
                "passed_unexpected_called": counts["passed_unexpected_called"],
            }
        )
        totals.update(
            {
                "expected_called": tp,
                "expected_not_called": fn,
                "unexpected_called": fp,
                "unexpected_not_called": tn,
            }
        )
    _write_csv(
        data_path(f"{kind}_call_confusion.csv"),
        [
            "resource",
            "kind",
            "n_labeled_evals",
            "expected_called",
            "expected_not_called",
            "optional_called",
            "optional_not_called",
            "unexpected_called",
            "unexpected_not_called",
            "precision",
            "recall",
            "false_positive_rate",
            "failed_expected_not_called",
            "failed_expected_called",
            "passed_unexpected_called",
        ],
        rows,
    )

    matrix = np.array(
        [
            [totals["expected_called"], totals["expected_not_called"]],
            [totals["unexpected_called"], totals["unexpected_not_called"]],
        ],
        dtype=float,
    )
    fig, ax = plt.subplots(figsize=(6.5, 5.5), constrained_layout=True)
    im = ax.imshow(matrix, cmap="Blues", aspect="auto")
    ax.set_xticks([0, 1])
    ax.set_xticklabels(["called", "not called"], fontsize=10)
    ax.set_yticks([0, 1])
    ax.set_yticklabels(["expected", "not expected"], fontsize=10)
    for i in range(2):
        for j in range(2):
            ax.text(j, i, f"{int(matrix[i, j])}", ha="center", va="center", fontsize=13)
    fig.colorbar(im, ax=ax, shrink=0.7, label="# eval-resource pairs")
    setup_axes(
        ax,
        f"{kind.title()} called-vs-expected confusion matrix",
        xlabel="Observed in with_skill transcript",
        ylabel="Eval annotation",
    )
    recall = (
        100
        * totals["expected_called"]
        / (totals["expected_called"] + totals["expected_not_called"])
        if totals["expected_called"] + totals["expected_not_called"]
        else 0.0
    )
    precision = (
        100
        * totals["expected_called"]
        / (totals["expected_called"] + totals["unexpected_called"])
        if totals["expected_called"] + totals["unexpected_called"]
        else 0.0
    )
    ax.text(
        0.5,
        -0.22,
        f"{len(labeled_evals)} labeled evals; recall={recall:.1f}%, precision={precision:.1f}%",
        transform=ax.transAxes,
        ha="center",
        va="top",
        fontsize=9,
    )
    filename_prefix = "20_reference" if kind == "reference" else "21_script"
    fig.savefig(figure_path(f"{filename_prefix}_call_confusion.png"), dpi=160, bbox_inches="tight")
    plt.close(fig)

def observed_resources_by_eval(
    records: list[TranscriptRecord] | None, kind: str
) -> dict[int, set[str]]:
    """Map eval_id to refs opened or scripts executed in with_skill transcripts."""
    observed: dict[int, set[str]] = defaultdict(set)
    if records is None:
        return observed
    for r in records:
        if r["condition"] != "with_skill":
            continue
        if kind == "reference":
            observed[r["eval_id"]].update(
                ref for ref in r["ref_opens"] if ref != "SKILL.md"
            )
        elif kind == "script":
            observed[r["eval_id"]].update(r["script_executions"])
        else:
            raise ValueError(f"unknown resource kind: {kind}")
    return observed

def write_expected_by_eval_csv(
    *,
    cats: EvalCategories,
    per_eval: list[PerEvalResult],
    observed: dict[int, set[str]] | None,
    expected: ExpectedResources,
    kind: str,
) -> None:
    """Per-eval expected-vs-observed routing table.

    This is the actionable companion to the aggregate confusion matrix: it says
    exactly which evals missed a required ref/script, which optional resources
    were used, and which distractors were called/opened.
    """
    if not expected or observed is None:
        unlink_outputs(f"{kind}_expected_by_eval.csv")
        return

    by_eval = {r["eval_id"]: r for r in per_eval}
    rows = []
    for eid in sorted(expected):
        r = by_eval.get(eid, {})
        cat = cats.get(eid, {})
        block = expected[eid]
        required = _expected_required(block)
        optional = _expected_optional(block)
        distractor = _expected_negative(block)
        called = observed.get(eid, set())
        rows.append(
            {
                "eval_id": eid,
                "batch": r.get("batch", ""),
                "eval_name": r.get("eval_name", ""),
                "stage": cat.get("stage", "unknown"),
                "tier": cat.get("tier", "unknown"),
                "difficulty": cat.get("difficulty", "unknown"),
                "ws_pass": int(bool(r.get("ws_pass", False))),
                "bs_pass": int(bool(r.get("bs_pass", False))),
                "required": _join_items(required),
                "called_required": _join_items(required & called),
                "missed_required": _join_items(required - called),
                "optional": _join_items(optional),
                "optional_called": _join_items(optional & called),
                "optional_not_called": _join_items(optional - called),
                "distractor": _join_items(distractor),
                "distractor_called": _join_items(distractor & called),
                "observed_unlabeled": _join_items(called - required - optional - distractor),
            }
        )

    _write_csv(
        data_path(f"{kind}_expected_by_eval.csv"),
        [
            *EVAL_METADATA_COLUMNS,
            "ws_pass",
            "bs_pass",
            "required",
            "called_required",
            "missed_required",
            "optional",
            "optional_called",
            "optional_not_called",
            "distractor",
            "distractor_called",
            "observed_unlabeled",
        ],
        rows,
    )

def write_routing_failure_views(
    *,
    cats: EvalCategories,
    per_eval: list[PerEvalResult],
    refs_by_eval: dict[int, set[str]] | None,
    scripts_by_eval: dict[int, set[str]] | None,
    expected_refs: ExpectedResources,
    expected_scripts: ExpectedResources,
) -> None:
    """Classify ws failures as routing misses or loaded-but-not-synthesized."""
    if not expected_refs and not expected_scripts:
        unlink_outputs("routing_diagnosis.csv")
        return
    if refs_by_eval is None or scripts_by_eval is None:
        unlink_outputs("routing_diagnosis.csv")
        return

    rows = []
    for r in sorted(per_eval, key=lambda x: (x["batch"], x["eval_id"])):
        if r["ws_pass"]:
            continue
        eid = r["eval_id"]
        cat = cats.get(eid, {})
        req_refs = _expected_required(expected_refs.get(eid, {}))
        req_scripts = _expected_required(expected_scripts.get(eid, {}))
        called_refs = refs_by_eval.get(eid, set())
        called_scripts = scripts_by_eval.get(eid, set())
        missed_refs = req_refs - called_refs
        missed_scripts = req_scripts - called_scripts
        diagnosis = (
            "routing_miss"
            if missed_refs or missed_scripts
            else "loaded_required_but_failed"
        )
        rows.append(
            {
                "eval_id": eid,
                "batch": r["batch"],
                "eval_name": r["eval_name"],
                "stage": cat.get("stage", "unknown"),
                "tier": cat.get("tier", "unknown"),
                "difficulty": cat.get("difficulty", "unknown"),
                "bs_pass": int(bool(r["bs_pass"])),
                "outcome": _outcome_label(r),
                "diagnosis": diagnosis,
                "required_refs": _join_items(req_refs),
                "called_refs": _join_items(called_refs),
                "missed_required_refs": _join_items(missed_refs),
                "required_scripts": _join_items(req_scripts),
                "called_scripts": _join_items(called_scripts),
                "missed_required_scripts": _join_items(missed_scripts),
            }
        )

    fields = [
        *EVAL_METADATA_COLUMNS,
        "bs_pass",
        "outcome",
        "diagnosis",
        "required_refs",
        "called_refs",
        "missed_required_refs",
        "required_scripts",
        "called_scripts",
        "missed_required_scripts",
    ]
    _write_csv(data_path("routing_diagnosis.csv"), fields, rows)

def write_cost_by_outcome_csv(
    per_eval: list[PerEvalResult], timing: dict[tuple[int, int, str], int]
) -> None:
    """Flat CSV for the spend-by-outcome block in cumulative_summary.json."""
    spend = build_spend_by_outcome(per_eval, timing)
    rows = []
    for outcome in ("both_pass", "skill_only", "baseline_only", "both_fail"):
        v = spend[outcome]
        rows.append(
            {
                "outcome": outcome,
                "n": v["n"],
                "mean_extra_tokens": v["mean_extra_tokens"],
                "total_extra_tokens": v["total_extra_tokens"],
                "share_of_total_extra": v["share_of_total_extra"],
            }
        )
    _write_csv(
        data_path("cost_by_outcome.csv"),
        [
            "outcome",
            "n",
            "mean_extra_tokens",
            "total_extra_tokens",
            "share_of_total_extra",
        ],
        rows,
    )

def write_skip_gate_candidates_csv(
    cats: EvalCategories,
    per_eval: list[PerEvalResult],
    timing: dict[tuple[int, int, str], int],
) -> None:
    """Find categories where baseline is already strong and skill spend is high.

    Thresholds live in module-level constants so future rounds can tune the
    policy without hunting magic numbers in the writer body.
    """
    rows = []
    for kind in ("stage", "tier", "difficulty"):
        grouped: dict[str, list[PerEvalResult]] = defaultdict(list)
        for r in per_eval:
            grouped[cats.get(r["eval_id"], {}).get(kind, "unknown")].append(r)
        for category, vals in grouped.items():
            n = len(vals)
            outcomes = count_outcomes(vals)
            bs_pass = outcomes["both_pass"] + outcomes["baseline_only"]
            ws_pass = outcomes["both_pass"] + outcomes["skill_only"]
            skill_only = outcomes["skill_only"]
            baseline_only = outcomes["baseline_only"]
            both_fail = outcomes["both_fail"]
            extras = []
            for r in vals:
                ws_tok = timing.get((r["batch"], r["eval_id"], "with_skill"))
                bs_tok = timing.get((r["batch"], r["eval_id"], "without_skill"))
                if ws_tok is not None and bs_tok is not None:
                    extras.append(ws_tok - bs_tok)
            bs_rate = 100 * bs_pass / n if n else 0.0
            ws_rate = 100 * ws_pass / n if n else 0.0
            unrescued = skill_only + baseline_only + both_fail
            rescue_rate = (
                100 * skill_only / unrescued
                if unrescued
                else 0.0
            )
            candidate_reason = ""
            if (
                n >= SKIP_GATE_MIN_EVALS
                and bs_rate >= SKIP_GATE_STRONG_BASELINE_PASS_RATE
                and skill_only == 0
            ):
                candidate_reason = "baseline_strong_no_rescues"
            elif (
                n >= SKIP_GATE_MIN_EVALS
                and bs_rate >= SKIP_GATE_HIGH_BASELINE_PASS_RATE
                and rescue_rate <= SKIP_GATE_LOW_RESCUE_RATE
                and sum(extras) > SKIP_GATE_TOTAL_EXTRA_TOKEN_FLOOR
            ):
                candidate_reason = "high_cost_low_rescue"
            rows.append(
                {
                    "category_kind": kind,
                    "category": category,
                    "n_evals": n,
                    "ws_pass_rate": f"{ws_rate:.1f}",
                    "bs_pass_rate": f"{bs_rate:.1f}",
                    "skill_only": skill_only,
                    "baseline_only": baseline_only,
                    "rescue_rate": f"{rescue_rate:.1f}",
                    "total_extra_tokens": sum(extras),
                    "mean_extra_tokens": round(sum(extras) / len(extras)) if extras else "",
                    "candidate_reason": candidate_reason,
                }
            )
    rows.sort(
        key=lambda r: (
            r["candidate_reason"] == "",
            -int(r["total_extra_tokens"]),
            r["category_kind"],
            r["category"],
        )
    )
    _write_csv(
        data_path("skip_gate_candidates.csv"),
        [
            "category_kind",
            "category",
            "n_evals",
            "ws_pass_rate",
            "bs_pass_rate",
            "skill_only",
            "baseline_only",
            "rescue_rate",
            "total_extra_tokens",
            "mean_extra_tokens",
            "candidate_reason",
        ],
        rows,
    )

def write_ws_regressions_csv(
    cats: EvalCategories, per_eval: list[PerEvalResult]
) -> None:
    """Evals where with_skill underperforms baseline at full-pass or expectation level."""
    rows = []
    for r in sorted(per_eval, key=lambda x: (x["batch"], x["eval_id"])):
        ws_pct = 100 * r["ws_exp_p"] / r["ws_exp_t"] if r["ws_exp_t"] else 0.0
        bs_pct = 100 * r["bs_exp_p"] / r["bs_exp_t"] if r["bs_exp_t"] else 0.0
        full_regression = bool(r["bs_pass"] and not r["ws_pass"])
        expectation_regression = ws_pct < bs_pct
        if not full_regression and not expectation_regression:
            continue
        cat = cats.get(r["eval_id"], {})
        rows.append(
            {
                "eval_id": r["eval_id"],
                "batch": r["batch"],
                "eval_name": r["eval_name"],
                "stage": cat.get("stage", "unknown"),
                "tier": cat.get("tier", "unknown"),
                "difficulty": cat.get("difficulty", "unknown"),
                "ws_pass": int(bool(r["ws_pass"])),
                "bs_pass": int(bool(r["bs_pass"])),
                "ws_expectation_rate": f"{ws_pct:.1f}",
                "bs_expectation_rate": f"{bs_pct:.1f}",
                "delta_expectation_pp": f"{ws_pct - bs_pct:.1f}",
                "full_pass_regression": int(full_regression),
                "expectation_regression": int(expectation_regression),
            }
        )
    _write_csv(
        data_path("ws_regressions.csv"),
        [
            *EVAL_METADATA_COLUMNS,
            "ws_pass",
            "bs_pass",
            "ws_expectation_rate",
            "bs_expectation_rate",
            "delta_expectation_pp",
            "full_pass_regression",
            "expectation_regression",
        ],
        rows,
    )

def write_fix_priority_csv(
    *,
    cats: EvalCategories,
    per_eval: list[PerEvalResult],
    refs_by_eval: dict[int, set[str]] | None,
    scripts_by_eval: dict[int, set[str]] | None,
    expected_refs: ExpectedResources,
    expected_scripts: ExpectedResources,
    timing: dict[tuple[int, int, str], int],
) -> None:
    """Decision table for next skill edits.

    Sort order puts direct fixes first: regressions, transcript-inspection
    blockers, missed-script routing, missed-reference routing, and
    loaded-but-failed synthesis/content. Expensive both-pass rows follow as
    cost inspections, then idle rows with no likely action.
    """
    refs_observed = refs_by_eval is not None
    scripts_observed = scripts_by_eval is not None
    refs_by_eval = refs_by_eval or {}
    scripts_by_eval = scripts_by_eval or {}
    rows = []
    for r in sorted(per_eval, key=lambda x: (x["batch"], x["eval_id"])):
        ws_pct = 100 * r["ws_exp_p"] / r["ws_exp_t"] if r["ws_exp_t"] else 0.0
        bs_pct = 100 * r["bs_exp_p"] / r["bs_exp_t"] if r["bs_exp_t"] else 0.0
        ws_tok = timing.get((r["batch"], r["eval_id"], "with_skill"))
        bs_tok = timing.get((r["batch"], r["eval_id"], "without_skill"))
        req_refs = _expected_required(expected_refs.get(r["eval_id"], {}))
        req_scripts = _expected_required(expected_scripts.get(r["eval_id"], {}))
        missed_refs = (
            req_refs - refs_by_eval.get(r["eval_id"], set())
            if refs_observed
            else set()
        )
        missed_scripts = (
            req_scripts - scripts_by_eval.get(r["eval_id"], set())
            if scripts_observed
            else set()
        )
        outcome = _outcome_label(r)
        extra_tokens_known = ws_tok is not None and bs_tok is not None
        extra_tokens = (ws_tok - bs_tok) if extra_tokens_known else 0
        if outcome == "baseline_only":
            likely_action = "investigate_regression"
        elif not r["ws_pass"] and not (refs_observed and scripts_observed):
            likely_action = "inspect_transcripts"
        elif not r["ws_pass"] and missed_scripts:
            likely_action = "fix_script_routing"
        elif not r["ws_pass"] and missed_refs:
            likely_action = "fix_reference_routing"
        elif not r["ws_pass"]:
            likely_action = "fix_template_or_reference_content"
        elif outcome == "both_pass" and extra_tokens > EXPENSIVE_BOTH_PASS_EXTRA_TOKEN_FLOOR:
            likely_action = "expensive_both_pass"
        else:
            likely_action = ""
        cat = cats.get(r["eval_id"], {})
        rows.append(
            {
                "eval_id": r["eval_id"],
                "batch": r["batch"],
                "eval_name": r["eval_name"],
                "stage": cat.get("stage", "unknown"),
                "tier": cat.get("tier", "unknown"),
                "difficulty": cat.get("difficulty", "unknown"),
                "outcome": outcome,
                "ws_expectation_rate": f"{ws_pct:.1f}",
                "bs_expectation_rate": f"{bs_pct:.1f}",
                "delta_expectation_pp": f"{ws_pct - bs_pct:.1f}",
                "routing_observed": int(refs_observed and scripts_observed),
                "extra_tokens_known": int(extra_tokens_known),
                "extra_tokens": extra_tokens,
                "missed_required_refs": _join_items(missed_refs),
                "missed_required_scripts": _join_items(missed_scripts),
                "likely_action": likely_action,
            }
        )
    rows.sort(
        key=lambda r: (
            FIX_PRIORITY_ACTION_ORDER.get(r["likely_action"], 99),
            r["batch"],
            r["eval_id"],
        )
    )
    _write_csv(
        data_path("fix_priority.csv"),
        [
            *EVAL_METADATA_COLUMNS,
            "outcome",
            "ws_expectation_rate",
            "bs_expectation_rate",
            "delta_expectation_pp",
            "routing_observed",
            "extra_tokens_known",
            "extra_tokens",
            "missed_required_refs",
            "missed_required_scripts",
            "likely_action",
        ],
        rows,
    )
    action_rows = [r for r in rows if r["likely_action"]]
    if not action_rows:
        return
    counts = Counter(r["likely_action"] for r in action_rows)
    labels = sorted(counts, key=lambda a: FIX_PRIORITY_ACTION_ORDER.get(a, 99))
    values = [counts[label] for label in labels]
    fig, ax = plt.subplots(figsize=(9, 4.8), constrained_layout=True)
    colors = [
        WONG["delta_neg"] if label == "investigate_regression"
        else WONG["delta_pos"] if label.startswith("fix_")
        else WONG["neutral"]
        for label in labels
    ]
    bars = ax.barh(np.arange(len(labels)), values, color=colors, edgecolor="white")
    for bar, value in zip(bars, values, strict=True):
        ax.text(
            bar.get_width() + 0.2,
            bar.get_y() + bar.get_height() / 2,
            str(value),
            va="center",
            fontsize=10,
        )
    ax.set_yticks(np.arange(len(labels)))
    ax.set_yticklabels(labels, fontsize=10, family="monospace")
    ax.invert_yaxis()
    ax.set_xlabel("# evals", fontsize=10)
    setup_axes(ax, "Fix-priority actions — what should the next refactor inspect first?")
    ax.grid(axis="x", alpha=0.3, linestyle=":")
    fig.savefig(figure_path("22_fix_priority_actions.png"), dpi=160, bbox_inches="tight")
    plt.close(fig)

def write_summary_manifest_json() -> None:
    """Document output purpose and priority so plots are not over-interpreted.

    New outputs intentionally fall back to appendix classification, but the
    manifest marks those entries with `classification_source=fallback` and
    prints their filenames so maintainers can promote them deliberately.
    """
    overrides = MANIFEST_OVERRIDES
    manifest = []
    filenames = set()
    for root_name in ("INDEX.md", "SUMMARY.md"):
        if root_name == "INDEX.md" or (OUT / root_name).is_file():
            filenames.add(root_name)
    if DATA.is_dir():
        filenames.update(f"data/{p.name}" for p in DATA.iterdir() if p.is_file())
    if FIGURES.is_dir():
        filenames.update(f"figures/{p.name}" for p in FIGURES.iterdir() if p.is_file())
    filenames.add("data/summary_manifest.json")

    fallback_files = []
    for filename in sorted(filenames):
        override_key = Path(filename).name
        if override_key in overrides:
            family, priority, purpose = overrides[override_key]
            classification_source = "override"
        else:
            family, priority, purpose = (
                "appendix",
                "appendix",
                "Generated summary artifact not yet classified.",
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
    data_path("summary_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    _write_summary_index_md(manifest)
    if fallback_files:
        print("Manifest fallback classifications:", ", ".join(sorted(fallback_files)))

def _write_summary_index_md(manifest: list[dict[str, str]]) -> None:
    """Render a human-readable index from summary_manifest.json metadata."""
    priority_order = {"primary": 0, "secondary": 1, "appendix": 2}
    rows = sorted(
        manifest,
        key=lambda r: (
            priority_order.get(r["priority"], 99),
            r["family"],
            r["filename"],
        ),
    )
    lines = [
        "# Summary Output Index",
        "",
        "Generated by `tools/make_plots.py` from `data/summary_manifest.json`.",
        "",
    ]
    for priority in ("primary", "secondary", "appendix"):
        group = [r for r in rows if r["priority"] == priority]
        if not group:
            continue
        lines.extend([f"## {priority.title()}", ""])
        for r in group:
            lines.append(
                f"- [`{r['filename']}`]({r['filename']}) — "
                f"{r['family']}: {r['purpose']}"
            )
        lines.append("")
    (OUT / "INDEX.md").write_text("\n".join(lines).rstrip() + "\n")

