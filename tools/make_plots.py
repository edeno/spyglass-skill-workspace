"""Generate summary plots for a Spyglass skill eval sweep.

Run-agnostic: takes `--run <path-to-runs/<run-id>/>` and produces all
figures + the category CSV under `<run>/summary/` (or `--out`).

Reads `benchmark.json` from each `iteration-N/` under the run, plus the
eval source metadata from the spyglass-skill repo's
`skills/spyglass/evals/evals.json`. Produces twelve figures (per-batch,
cumulative, by-category, by-difficulty, per-eval, reference and script
utilization) plus `category_breakdown.csv`, `ref_utilization.json`, and
`script_utilization.json`.

The set of batches (`BATCH_ORDER`) is auto-discovered from
`<run>/iteration-*` dirs. Per-batch labels (`BATCH_LABELS`) come from
`<run>/run.json` under the optional top-level `batches` key, e.g.:

    "batches": {
      "1": {"label": "B1\\nkey hygiene\\n+ merge"},
      "2": {"label": "B2\\nhallucination"}
    }

If a batch has no entry, the label falls back to `f"B{i}"`.

Usage:
    uv run --with matplotlib --with numpy \\
        python tools/make_plots.py --run runs/round-c-2026-04-28/

    # override skill repo location
    python tools/make_plots.py --run runs/round-c-2026-04-28/ \\
        --skill-root /path/to/spyglass-skill
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from _util import discover_iterations, find_skill_root

# Sentinel placeholder lets the type checker see a concrete Path. Using one
# in a path op before configure_run() raises FileNotFoundError against
# `/__not_configured__/...` — clearly a marker, not a real bug.
_UNCONFIGURED = Path("/__not_configured__")
OUT: Path = _UNCONFIGURED
WORKSPACE: Path = _UNCONFIGURED
EVALS_PATH: Path = _UNCONFIGURED
BATCH_ORDER: list[int] = []
BATCH_LABELS: dict[int, str] = {}

WONG = {
    "ws": "#0072B2",
    "bs": "#D55E00",
    "delta_pos": "#009E73",
    "delta_neg": "#CC79A7",
    "neutral": "#999999",
    "both_pass": "#56B4E9",
    "both_fail": "#666666",
}


def delta_color(d: float) -> str:
    """WONG palette entry for a per-batch / per-category delta."""
    if d > 0:
        return WONG["delta_pos"]
    if d < 0:
        return WONG["delta_neg"]
    return WONG["neutral"]


def summarize_benchmarks(benchmarks: dict[int, dict]) -> dict:
    """Cumulative ws/bs counts across all batches.

    Used by `plot_cumulative_summary` and `write_cumulative_summary_json` —
    keeping the aggregation in one place avoids drift if the per-batch
    `benchmark.json` schema changes.
    """
    totals = {"ws": {}, "bs": {}}
    for cond_key, cond_name in (("ws", "with_skill"), ("bs", "without_skill")):
        totals[cond_key] = {
            "full_pass": sum(
                b["configurations"][cond_name]["evals_full_pass"]
                for b in benchmarks.values()
            ),
            "n_runs": sum(
                b["configurations"][cond_name]["n_runs"] for b in benchmarks.values()
            ),
            "exp_p": sum(
                b["configurations"][cond_name]["expectations_passed"]
                for b in benchmarks.values()
            ),
            "exp_t": sum(
                b["configurations"][cond_name]["expectations_total"]
                for b in benchmarks.values()
            ),
            "tokens": sum(
                b["configurations"][cond_name]["tokens_total"]
                for b in benchmarks.values()
            ),
        }
    return totals


def load_batch_labels(run_dir: Path, batch_order: list[int]) -> dict[int, str]:
    """Read run.json's optional `batches` block; fill missing entries with `B{i}`.

    The `batches` key maps str(batch_id) -> {"label": str, ...}. Anything
    not declared falls back to a generic label so the script still works
    on a freshly-dispatched sweep before labels have been authored.
    """
    run_meta_path = run_dir / "run.json"
    cfg: dict[str, dict] = {}
    if run_meta_path.is_file():
        try:
            cfg = json.loads(run_meta_path.read_text()).get("batches", {})
        except (json.JSONDecodeError, OSError):
            cfg = {}
    return {b: cfg.get(str(b), {}).get("label", f"B{b}") for b in batch_order}


def configure_run(run_dir: Path, out_dir: Path | None = None) -> None:
    """Populate the run-scoped module globals (OUT, WORKSPACE, BATCH_*)."""
    global OUT, WORKSPACE, BATCH_ORDER, BATCH_LABELS
    WORKSPACE = run_dir.resolve()
    OUT = (out_dir or WORKSPACE / "summary").resolve()
    OUT.mkdir(parents=True, exist_ok=True)
    BATCH_ORDER = discover_iterations(WORKSPACE)
    if not BATCH_ORDER:
        raise SystemExit(f"No iteration-N/ dirs found under {WORKSPACE}")
    BATCH_LABELS = load_batch_labels(WORKSPACE, BATCH_ORDER)


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


def load_benchmarks() -> dict[int, dict]:
    return {
        i: json.loads((WORKSPACE / f"iteration-{i}" / "benchmark.json").read_text())
        for i in BATCH_ORDER
    }


def load_eval_categories() -> dict[int, dict[str, str]]:
    """Map eval_id -> {stage, tier, difficulty}.

    Requires configure_skill_root() to have populated EVALS_PATH.
    """
    evals = json.loads(EVALS_PATH.read_text())["evals"]
    return {
        e["id"]: {
            "stage": e.get("stage", "unknown"),
            "tier": e.get("tier", "unknown"),
            "difficulty": e.get("difficulty", "unknown"),
        }
        for e in evals
    }


def load_per_eval_results(benchmarks: dict[int, dict]) -> list[dict]:
    """Flatten benchmarks into a list of per-eval dicts with both conditions."""
    results = []
    for batch_id, bench in benchmarks.items():
        ws_results = {
            e["eval_id"]: e
            for e in bench["configurations"]["with_skill"]["eval_results"]
        }
        bs_results = {
            e["eval_id"]: e
            for e in bench["configurations"]["without_skill"]["eval_results"]
        }
        for eid, ws_r in ws_results.items():
            bs_r = bs_results.get(
                eid, {"all_passed": False, "passed_count": 0, "total": 0}
            )
            results.append(
                {
                    "eval_id": eid,
                    "eval_name": ws_r["eval_name"],
                    "batch": batch_id,
                    "ws_pass": bool(ws_r["all_passed"]),
                    "bs_pass": bool(bs_r["all_passed"]),
                    "ws_exp_p": ws_r["passed_count"],
                    "ws_exp_t": ws_r["total"],
                    "bs_exp_p": bs_r["passed_count"],
                    "bs_exp_t": bs_r["total"],
                }
            )
    return results


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


def setup_axes(ax, title: str, xlabel: str = "", ylabel: str = "") -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_title(title, fontsize=11, loc="left", pad=8)
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=10)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=10)
    ax.tick_params(labelsize=9)


def plot_per_batch_pass_rate(benchmarks: dict[int, dict]) -> None:
    fig, ax = plt.subplots(figsize=(10, 5.5), constrained_layout=True)
    x = np.arange(len(BATCH_ORDER))
    width = 0.38
    ws_rates, bs_rates, n_evals = [], [], []
    for b in BATCH_ORDER:
        cfg = benchmarks[b]["configurations"]
        ws_rates.append(
            100 * cfg["with_skill"]["evals_full_pass"] / cfg["with_skill"]["n_runs"]
        )
        bs_rates.append(
            100
            * cfg["without_skill"]["evals_full_pass"]
            / cfg["without_skill"]["n_runs"]
        )
        n_evals.append(cfg["with_skill"]["n_runs"])
    ax.bar(x - width / 2, ws_rates, width, label="with skill", color=WONG["ws"])
    ax.bar(x + width / 2, bs_rates, width, label="baseline", color=WONG["bs"])
    for i, (ws_r, bs_r) in enumerate(zip(ws_rates, bs_rates)):
        ax.text(
            i - width / 2,
            ws_r + 1.5,
            f"{ws_r:.0f}%",
            ha="center",
            fontsize=8,
            color=WONG["ws"],
        )
        ax.text(
            i + width / 2,
            bs_r + 1.5,
            f"{bs_r:.0f}%",
            ha="center",
            fontsize=8,
            color=WONG["bs"],
        )
    ax.set_xticks(x)
    ax.set_xticklabels(
        [f"{BATCH_LABELS[b]}\n(n={n_evals[i]})" for i, b in enumerate(BATCH_ORDER)],
        fontsize=9,
    )
    ax.set_ylim(0, 115)
    ax.set_yticks(np.arange(0, 101, 20))
    setup_axes(ax, "Full-eval pass rate per batch", ylabel="evals fully passing (%)")
    ax.legend(loc="upper right", frameon=False, fontsize=10)
    ax.grid(axis="y", alpha=0.3, linestyle=":")
    n_total = sum(
        b["configurations"]["with_skill"]["n_runs"] for b in benchmarks.values()
    )
    fig.suptitle(
        f"Spyglass skill — full-eval pass rate per batch ({n_total} evals × 2 conditions)",
        fontsize=12,
        y=1.02,
    )
    fig.savefig(OUT / "01_per_batch_pass_rate.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def plot_delta_per_batch(benchmarks: dict[int, dict]) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5), constrained_layout=True)
    x = np.arange(len(BATCH_ORDER))
    behavioral_deltas = []
    for b in BATCH_ORDER:
        ws_p, ws_t, bs_p, bs_t = collect_behavioral(b)
        ws_pp = 100 * ws_p / ws_t if ws_t else 0
        bs_pp = 100 * bs_p / bs_t if bs_t else 0
        behavioral_deltas.append(ws_pp - bs_pp)
    # Compute expectation deltas directly from configurations (older batches store delta in
    # fractional form `expectation_pass_rate`, newer ones in percentage points
    # `expectation_pass_rate_pp`; recomputing avoids that schema drift).
    expectation_deltas = []
    for b in BATCH_ORDER:
        cfg = benchmarks[b]["configurations"]
        ws_pp = (
            100
            * cfg["with_skill"]["expectations_passed"]
            / cfg["with_skill"]["expectations_total"]
        )
        bs_pp = (
            100
            * cfg["without_skill"]["expectations_passed"]
            / cfg["without_skill"]["expectations_total"]
        )
        expectation_deltas.append(ws_pp - bs_pp)
    for ax, deltas, title in [
        (axes[0], behavioral_deltas, "Behavioral-check delta (with_skill − baseline)"),
        (
            axes[1],
            expectation_deltas,
            "Total expectation delta (with_skill − baseline)",
        ),
    ]:
        colors = [delta_color(d) for d in deltas]
        bars = ax.bar(x, deltas, color=colors, width=0.7)
        for bar, d in zip(bars, deltas):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                d + (0.6 if d >= 0 else -1.5),
                f"{d:+.1f}",
                ha="center",
                fontsize=9,
                fontweight="bold",
            )
        ax.axhline(0, color="black", linewidth=0.7)
        ax.set_xticks(x)
        ax.set_xticklabels([BATCH_LABELS[b] for b in BATCH_ORDER], fontsize=9)
        ax.set_ylim(-3, max(max(behavioral_deltas), max(expectation_deltas)) + 5)
        setup_axes(ax, title, ylabel="percentage points (pp)")
        ax.grid(axis="y", alpha=0.3, linestyle=":")
    fig.suptitle(
        "Skill delta per batch — where with_skill helped most", fontsize=12, y=1.02
    )
    fig.savefig(OUT / "02_delta_per_batch.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def plot_per_eval_outcomes(benchmarks: dict[int, dict]) -> None:
    fig, ax = plt.subplots(figsize=(10, 5.5), constrained_layout=True)
    x = np.arange(len(BATCH_ORDER))
    both_pass, skill_only, bs_only, both_fail = [], [], [], []
    for b in BATCH_ORDER:
        cfg = benchmarks[b]["configurations"]
        ws = {e["eval_id"]: e["all_passed"] for e in cfg["with_skill"]["eval_results"]}
        bs = {
            e["eval_id"]: e["all_passed"] for e in cfg["without_skill"]["eval_results"]
        }
        bp = so = bo = bf = 0
        for eid, ws_pass in ws.items():
            bs_pass = bs.get(eid, False)
            if ws_pass and bs_pass:
                bp += 1
            elif ws_pass:
                so += 1
            elif bs_pass:
                bo += 1
            else:
                bf += 1
        both_pass.append(bp)
        skill_only.append(so)
        bs_only.append(bo)
        both_fail.append(bf)
    bottom = np.zeros(len(BATCH_ORDER))
    series = [
        (both_pass, "both pass", WONG["both_pass"]),
        (skill_only, "skill only", WONG["delta_pos"]),
        (bs_only, "baseline only", WONG["delta_neg"]),
        (both_fail, "both fail", WONG["both_fail"]),
    ]
    for vals, lab, color in series:
        ax.bar(x, vals, width=0.7, bottom=bottom, label=lab, color=color)
        for i, v in enumerate(vals):
            if v > 0:
                ax.text(
                    i,
                    bottom[i] + v / 2,
                    str(v),
                    ha="center",
                    va="center",
                    fontsize=9,
                    color="white" if lab != "both pass" else "black",
                    fontweight="bold",
                )
        bottom = bottom + np.array(vals)
    ax.set_xticks(x)
    ax.set_xticklabels([BATCH_LABELS[b] for b in BATCH_ORDER], fontsize=9)
    setup_axes(ax, "Per-eval outcomes by batch", ylabel="number of evals")
    ax.legend(
        loc="upper left", frameon=False, fontsize=10, ncol=4, bbox_to_anchor=(0, 1.08)
    )
    ax.grid(axis="y", alpha=0.3, linestyle=":")
    fig.suptitle("Skill-only vs baseline-only wins per batch", fontsize=12, y=1.04)
    fig.savefig(OUT / "03_per_eval_outcomes.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def plot_tokens_and_duration(benchmarks: dict[int, dict]) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5), constrained_layout=True)
    x = np.arange(len(BATCH_ORDER))
    width = 0.38
    cfgs = [benchmarks[b]["configurations"] for b in BATCH_ORDER]
    ws_tokens = [c["with_skill"]["tokens_mean"] / 1000 for c in cfgs]
    bs_tokens = [c["without_skill"]["tokens_mean"] / 1000 for c in cfgs]
    ws_dur = [c["with_skill"]["duration_mean_s"] for c in cfgs]
    bs_dur = [c["without_skill"]["duration_mean_s"] for c in cfgs]
    axes[0].bar(x - width / 2, ws_tokens, width, label="with skill", color=WONG["ws"])
    axes[0].bar(x + width / 2, bs_tokens, width, label="baseline", color=WONG["bs"])
    axes[0].set_xticks(x)
    axes[0].set_xticklabels([BATCH_LABELS[b] for b in BATCH_ORDER], fontsize=9)
    setup_axes(axes[0], "Mean tokens per run", ylabel="tokens (thousands)")
    axes[0].legend(loc="upper left", frameon=False, fontsize=10)
    axes[0].grid(axis="y", alpha=0.3, linestyle=":")
    axes[1].bar(x - width / 2, ws_dur, width, label="with skill", color=WONG["ws"])
    axes[1].bar(x + width / 2, bs_dur, width, label="baseline", color=WONG["bs"])
    axes[1].set_xticks(x)
    axes[1].set_xticklabels([BATCH_LABELS[b] for b in BATCH_ORDER], fontsize=9)
    setup_axes(axes[1], "Mean wall-clock duration per run", ylabel="seconds")
    axes[1].legend(loc="upper left", frameon=False, fontsize=10)
    axes[1].grid(axis="y", alpha=0.3, linestyle=":")
    fig.suptitle("Cost: tokens and wall-clock per run", fontsize=12, y=1.02)
    fig.savefig(OUT / "04_cost_per_batch.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def plot_cumulative_summary(benchmarks: dict[int, dict]) -> None:
    fig, ax = plt.subplots(figsize=(10, 4.5), constrained_layout=True)
    totals = summarize_benchmarks(benchmarks)
    ws, bs = totals["ws"], totals["bs"]
    n_evals = ws["n_runs"]
    rows = [
        ("Evals fully pass", ws["full_pass"], n_evals, bs["full_pass"], n_evals),
        ("Expectations", ws["exp_p"], ws["exp_t"], bs["exp_p"], bs["exp_t"]),
    ]
    y_positions = np.arange(len(rows))
    bar_height = 0.36
    for i, (_, ws_p, ws_t, bs_p, bs_t) in enumerate(rows):
        ws_pct = 100 * ws_p / ws_t
        bs_pct = 100 * bs_p / bs_t
        ax.barh(y_positions[i] - bar_height / 2, ws_pct, bar_height, color=WONG["ws"])
        ax.barh(y_positions[i] + bar_height / 2, bs_pct, bar_height, color=WONG["bs"])
        ax.text(
            ws_pct + 0.5,
            y_positions[i] - bar_height / 2,
            f"{ws_p}/{ws_t} ({ws_pct:.1f}%)",
            va="center",
            fontsize=10,
            color=WONG["ws"],
            fontweight="bold",
        )
        ax.text(
            bs_pct + 0.5,
            y_positions[i] + bar_height / 2,
            f"{bs_p}/{bs_t} ({bs_pct:.1f}%)",
            va="center",
            fontsize=10,
            color=WONG["bs"],
            fontweight="bold",
        )
        ax.text(
            101,
            y_positions[i],
            f"Δ +{ws_pct - bs_pct:.1f}pp",
            va="center",
            fontsize=10,
            color="black",
            fontweight="bold",
        )
    ax.set_yticks(y_positions)
    ax.set_yticklabels([r[0] for r in rows], fontsize=11)
    ax.set_xlim(0, 120)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xlabel("% passing", fontsize=10)
    ax.invert_yaxis()
    setup_axes(ax, f"Cumulative — all {len(BATCH_ORDER)} batches, {n_evals} evals")
    handles = [
        plt.Rectangle((0, 0), 1, 1, color=WONG["ws"], label="with skill"),
        plt.Rectangle((0, 0), 1, 1, color=WONG["bs"], label="baseline"),
    ]
    ax.legend(handles=handles, loc="lower right", frameon=False, fontsize=10)
    ax.grid(axis="x", alpha=0.3, linestyle=":")
    fig.suptitle("Spyglass skill — final cumulative result", fontsize=13, y=1.02)
    fig.savefig(OUT / "05_cumulative_summary.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def plot_by_category(
    cats: dict[int, dict[str, str]], per_eval: list[dict]
) -> None:
    """Two-panel: per-eval pass rates grouped by stage and by tier."""

    def aggregate(key: str) -> list[tuple[str, int, int, int, int]]:
        """Return [(category, ws_pass_n, ws_total, bs_pass_n, bs_total), ...] sorted by total desc."""
        agg: dict[str, list[int]] = defaultdict(
            lambda: [0, 0, 0, 0]
        )  # [ws_pass, ws_total, bs_pass, bs_total]
        for r in per_eval:
            cat = cats.get(r["eval_id"], {}).get(key, "unknown")
            agg[cat][0] += int(r["ws_pass"])
            agg[cat][1] += 1
            agg[cat][2] += int(r["bs_pass"])
            agg[cat][3] += 1
        rows: list[tuple[str, int, int, int, int]] = [
            (c, vals[0], vals[1], vals[2], vals[3]) for c, vals in agg.items()
        ]
        rows.sort(key=lambda x: -x[2])
        return rows

    fig, axes = plt.subplots(2, 1, figsize=(12, 13), constrained_layout=True)

    for ax_i, key, title in [
        (0, "stage", "Pass rate by STAGE (high-level eval category)"),
        (1, "tier", "Pass rate by TIER (fine-grained eval category)"),
    ]:
        rows = aggregate(key)
        labels = [r[0] for r in rows]
        ws_rates = [100 * r[1] / r[2] for r in rows]
        bs_rates = [100 * r[3] / r[4] for r in rows]
        deltas = [w - b for w, b in zip(ws_rates, bs_rates)]
        counts = [r[2] for r in rows]

        y = np.arange(len(rows))
        height = 0.38
        ax = axes[ax_i]
        ax.barh(y - height / 2, ws_rates, height, color=WONG["ws"], label="with skill")
        ax.barh(y + height / 2, bs_rates, height, color=WONG["bs"], label="baseline")

        for i in range(len(rows)):
            ax.text(
                ws_rates[i] + 1,
                y[i] - height / 2,
                f"{ws_rates[i]:.0f}%",
                va="center",
                fontsize=8,
                color=WONG["ws"],
            )
            ax.text(
                bs_rates[i] + 1,
                y[i] + height / 2,
                f"{bs_rates[i]:.0f}%",
                va="center",
                fontsize=8,
                color=WONG["bs"],
            )
            d = deltas[i]
            ax.text(
                108,
                y[i],
                f"Δ {d:+.0f}pp",
                va="center",
                fontsize=9,
                color=delta_color(d),
                fontweight="bold",
            )

        ax.set_yticks(y)
        ax.set_yticklabels(
            [f"{lab}  (n={n})" for lab, n in zip(labels, counts)], fontsize=10
        )
        ax.set_xlim(0, 130)
        ax.set_xticks([0, 25, 50, 75, 100])
        ax.invert_yaxis()
        setup_axes(ax, title, xlabel="% of evals fully passing")
        ax.legend(loc="lower right", frameon=False, fontsize=10)
        ax.grid(axis="x", alpha=0.3, linestyle=":")

    fig.suptitle("Spyglass skill — pass rate by eval category", fontsize=13, y=1.01)
    fig.savefig(OUT / "06_by_category.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def plot_by_difficulty(
    cats: dict[int, dict[str, str]], per_eval: list[dict]
) -> None:
    """Per-difficulty pass rate (easy / medium / hard) and outcome breakdown."""
    diff_order = ["easy", "medium", "hard"]

    agg: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0, 0])
    # [ws_pass, total, bs_pass, both_pass, skill_only, bs_only, both_fail]
    outcomes: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])

    for r in per_eval:
        d = cats.get(r["eval_id"], {}).get("difficulty", "unknown")
        agg[d][0] += int(r["ws_pass"])
        agg[d][1] += 1
        agg[d][2] += int(r["bs_pass"])
        if r["ws_pass"] and r["bs_pass"]:
            outcomes[d][0] += 1
        elif r["ws_pass"]:
            outcomes[d][1] += 1
        elif r["bs_pass"]:
            outcomes[d][2] += 1
        else:
            outcomes[d][3] += 1

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5), constrained_layout=True)

    x = np.arange(len(diff_order))
    width = 0.38
    ws_rates = [100 * agg[d][0] / agg[d][1] if agg[d][1] else 0 for d in diff_order]
    bs_rates = [100 * agg[d][2] / agg[d][1] if agg[d][1] else 0 for d in diff_order]
    counts = [agg[d][1] for d in diff_order]
    axes[0].bar(x - width / 2, ws_rates, width, label="with skill", color=WONG["ws"])
    axes[0].bar(x + width / 2, bs_rates, width, label="baseline", color=WONG["bs"])
    for i, (ws_r, bs_r) in enumerate(zip(ws_rates, bs_rates)):
        axes[0].text(
            i - width / 2,
            ws_r + 1.5,
            f"{ws_r:.0f}%",
            ha="center",
            fontsize=9,
            color=WONG["ws"],
        )
        axes[0].text(
            i + width / 2,
            bs_r + 1.5,
            f"{bs_r:.0f}%",
            ha="center",
            fontsize=9,
            color=WONG["bs"],
        )
        axes[0].text(
            i, -8, f"Δ +{ws_r - bs_r:.0f}pp", ha="center", fontsize=9, fontweight="bold"
        )
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(
        [f"{d}\n(n={n})" for d, n in zip(diff_order, counts)], fontsize=10
    )
    axes[0].set_ylim(-15, 115)
    axes[0].set_yticks(np.arange(0, 101, 20))
    setup_axes(axes[0], "Full-eval pass rate by difficulty", ylabel="% passing")
    axes[0].legend(loc="lower right", frameon=False, fontsize=10)
    axes[0].grid(axis="y", alpha=0.3, linestyle=":")

    bottom = np.zeros(len(diff_order))
    series = [
        ([outcomes[d][0] for d in diff_order], "both pass", WONG["both_pass"]),
        ([outcomes[d][1] for d in diff_order], "skill only", WONG["delta_pos"]),
        ([outcomes[d][2] for d in diff_order], "baseline only", WONG["delta_neg"]),
        ([outcomes[d][3] for d in diff_order], "both fail", WONG["both_fail"]),
    ]
    for vals, lab, color in series:
        axes[1].bar(x, vals, width=0.6, bottom=bottom, label=lab, color=color)
        for i, v in enumerate(vals):
            if v > 0:
                axes[1].text(
                    i,
                    bottom[i] + v / 2,
                    str(v),
                    ha="center",
                    va="center",
                    fontsize=9,
                    color="white" if lab != "both pass" else "black",
                    fontweight="bold",
                )
        bottom = bottom + np.array(vals)
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(
        [f"{d}\n(n={n})" for d, n in zip(diff_order, counts)], fontsize=10
    )
    setup_axes(axes[1], "Outcome breakdown by difficulty", ylabel="number of evals")
    axes[1].legend(
        loc="upper left", frameon=False, fontsize=9, ncol=2, bbox_to_anchor=(0, 1.13)
    )
    axes[1].grid(axis="y", alpha=0.3, linestyle=":")

    fig.suptitle(
        "Spyglass skill — pass rate and outcomes by difficulty", fontsize=12, y=1.02
    )
    fig.savefig(OUT / "07_by_difficulty.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def plot_difficulty_x_stage_heatmap(
    cats: dict[int, dict[str, str]], per_eval: list[dict]
) -> None:
    """Heatmap: skill delta (pp) by difficulty × stage. Reveals where the skill helps on hard prompts."""
    diff_order = ["easy", "medium", "hard"]

    # Single pass: bucket every per_eval row into both stage_lift (for stage
    # ordering) and cell (stage, difficulty) totals.
    stage_lift: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    cell: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0, 0])
    for r in per_eval:
        cat = cats.get(r["eval_id"], {})
        s = cat.get("stage", "unknown")
        d = cat.get("difficulty", "unknown")
        ws_p, bs_p = int(r["ws_pass"]), int(r["bs_pass"])
        stage_lift[s][0] += ws_p
        stage_lift[s][1] += bs_p
        stage_lift[s][2] += 1
        cell[(s, d)][0] += ws_p
        cell[(s, d)][1] += bs_p
        cell[(s, d)][2] += 1

    stage_order = sorted(
        stage_lift.keys(),
        key=lambda s: -100 * (stage_lift[s][0] - stage_lift[s][1]) / stage_lift[s][2],
    )

    delta = np.full((len(stage_order), len(diff_order)), np.nan)
    counts = np.zeros((len(stage_order), len(diff_order)), dtype=int)
    for i, s in enumerate(stage_order):
        for j, d in enumerate(diff_order):
            ws_p, bs_p, n = cell.get((s, d), [0, 0, 0])
            counts[i, j] = n
            if n > 0:
                delta[i, j] = 100 * (ws_p - bs_p) / n

    fig, ax = plt.subplots(figsize=(8, 9), constrained_layout=True)
    cmap = plt.cm.RdYlGn
    im = ax.imshow(delta, cmap=cmap, vmin=-50, vmax=100, aspect="auto")
    ax.set_xticks(np.arange(len(diff_order)))
    ax.set_xticklabels(diff_order, fontsize=11)
    ax.set_yticks(np.arange(len(stage_order)))
    ax.set_yticklabels(stage_order, fontsize=10)
    for i in range(len(stage_order)):
        for j in range(len(diff_order)):
            n = counts[i, j]
            if n == 0:
                ax.text(
                    j, i, "—", ha="center", va="center", fontsize=10, color="#888888"
                )
            else:
                d = delta[i, j]
                color = "white" if d < -10 or d > 50 else "black"
                ax.text(
                    j,
                    i,
                    f"{d:+.0f}\nn={n}",
                    ha="center",
                    va="center",
                    fontsize=9,
                    color=color,
                    fontweight="bold" if d > 0 else "normal",
                )
    cbar = fig.colorbar(im, ax=ax, shrink=0.7, pad=0.02)
    cbar.set_label("skill delta (pp on full-eval pass)", fontsize=10)
    setup_axes(ax, "Skill delta by stage × difficulty (pp)", xlabel="difficulty")
    fig.suptitle(
        "Where does the skill help on HARD prompts vs EASY?", fontsize=12, y=1.01
    )
    fig.savefig(OUT / "08_difficulty_x_stage_heatmap.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def plot_per_eval_scatter(
    cats: dict[int, dict[str, str]], per_eval: list[dict]
) -> None:
    """Per-eval scatter: skill expectation pass rate vs baseline. Each dot is one eval."""

    ws_rates, bs_rates, sizes, colors, names = [], [], [], [], []
    diff_color = {
        "easy": "#56B4E9",
        "medium": "#F0E442",
        "hard": "#D55E00",
        "unknown": "#999999",
    }
    for r in per_eval:
        if r["ws_exp_t"] == 0:
            continue
        ws_r = 100 * r["ws_exp_p"] / r["ws_exp_t"]
        bs_r = 100 * r["bs_exp_p"] / r["bs_exp_t"] if r["bs_exp_t"] else 0
        ws_rates.append(ws_r)
        bs_rates.append(bs_r)
        sizes.append(60)
        d = cats.get(r["eval_id"], {}).get("difficulty", "unknown")
        colors.append(diff_color.get(d, "#999999"))
        names.append((r["eval_id"], r["eval_name"], ws_r, bs_r))

    fig, ax = plt.subplots(figsize=(8.5, 8.5), constrained_layout=True)

    # Diagonal y=x; above the line = skill helps.
    ax.plot(
        [0, 100],
        [0, 100],
        "--",
        color="#333333",
        linewidth=1,
        alpha=0.5,
        label="parity (y=x)",
    )
    # Jitter so 100/100 dots don't all stack on a single pixel.
    rng = np.random.default_rng(42)
    jitter_ws = np.array(ws_rates) + rng.uniform(-0.8, 0.8, len(ws_rates))
    jitter_bs = np.array(bs_rates) + rng.uniform(-0.8, 0.8, len(bs_rates))
    ax.scatter(
        jitter_bs,
        jitter_ws,
        s=sizes,
        c=colors,
        alpha=0.7,
        edgecolors="white",
        linewidths=0.5,
    )

    # Annotate the most interesting outliers: large skill wins (skill ≥ 90, baseline ≤ 50).
    for eid, _name, ws_r, bs_r in names:
        if ws_r >= 90 and bs_r <= 50:
            ax.annotate(
                f"#{eid}",
                (bs_r, ws_r),
                fontsize=8,
                ha="left",
                va="bottom",
                xytext=(3, 3),
                textcoords="offset points",
                color=WONG["delta_pos"],
            )
        elif ws_r < bs_r - 15:  # skill substantially worse
            ax.annotate(
                f"#{eid}",
                (bs_r, ws_r),
                fontsize=8,
                ha="left",
                va="top",
                xytext=(3, -3),
                textcoords="offset points",
                color=WONG["delta_neg"],
                fontweight="bold",
            )

    ax.set_xlim(-3, 103)
    ax.set_ylim(-3, 103)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_yticks([0, 25, 50, 75, 100])
    ax.set_xlabel("baseline expectation pass rate (%)", fontsize=11)
    ax.set_ylabel("with-skill expectation pass rate (%)", fontsize=11)
    n_total = len(ws_rates)
    setup_axes(ax, f"Per-eval scatter — each point is one of {n_total} evals")

    # Per-difficulty legend uses live counts from this run.
    diff_counts = Counter()
    for r in per_eval:
        if r["ws_exp_t"] == 0:
            continue
        diff_counts[cats.get(r["eval_id"], {}).get("difficulty", "unknown")] += 1
    handles = [
        plt.Line2D(
            [0],
            [0],
            marker="o",
            color="w",
            markerfacecolor=diff_color[d],
            markersize=10,
            label=f"{d} (n={diff_counts.get(d, 0)})",
        )
        for d in ("easy", "medium", "hard")
    ] + [plt.Line2D([0], [0], linestyle="--", color="#333333", label="parity (y=x)")]
    ax.legend(handles=handles, loc="lower right", frameon=False, fontsize=9)
    ax.text(
        2, 95, "skill helps\n(above line)", fontsize=9, color="#666666", style="italic"
    )
    ax.text(
        75, 5, "skill hurts\n(below line)", fontsize=9, color="#666666", style="italic"
    )

    fig.suptitle(
        "Skill vs baseline — per-eval scatter (color = difficulty)", fontsize=12, y=1.02
    )
    fig.savefig(OUT / "09_per_eval_scatter.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def plot_top_skill_wins(
    cats: dict[int, dict[str, str]], per_eval: list[dict]
) -> None:
    """Horizontal bar: top-15 evals where skill helped most (largest passed-count delta)."""

    items = []
    for r in per_eval:
        ws_pct = 100 * r["ws_exp_p"] / r["ws_exp_t"] if r["ws_exp_t"] else 0
        bs_pct = 100 * r["bs_exp_p"] / r["bs_exp_t"] if r["bs_exp_t"] else 0
        items.append(
            {
                "eval_id": r["eval_id"],
                "name": r["eval_name"],
                "ws_pct": ws_pct,
                "bs_pct": bs_pct,
                "delta": ws_pct - bs_pct,
                "stage": cats.get(r["eval_id"], {}).get("stage", "unknown"),
                "difficulty": cats.get(r["eval_id"], {}).get("difficulty", "unknown"),
            }
        )

    top = sorted(items, key=lambda x: -x["delta"])[:15]
    bottom = sorted(items, key=lambda x: x["delta"])[:5]
    bottom = [b for b in bottom if b["delta"] < 0]

    fig, axes = plt.subplots(
        2,
        1,
        figsize=(12, 9),
        gridspec_kw={"height_ratios": [3, max(1, len(bottom)) / 5]},
        constrained_layout=True,
    )

    for ax, rows, title, color in [
        (
            axes[0],
            top,
            "Top 15 evals where the SKILL helped most (ranked by Δ pp)",
            WONG["delta_pos"],
        ),
        (
            axes[1],
            bottom,
            "Evals where the SKILL scored WORSE than baseline",
            WONG["delta_neg"],
        ),
    ]:
        if not rows:
            ax.text(
                0.5,
                0.5,
                "(none — no eval where skill scored worse)",
                ha="center",
                va="center",
                fontsize=11,
                transform=ax.transAxes,
            )
            ax.axis("off")
            continue
        y = np.arange(len(rows))
        deltas = [r["delta"] for r in rows]
        labels = [
            f"#{r['eval_id']} {r['name']} ({r['stage']}/{r['difficulty']})"
            for r in rows
        ]
        ax.barh(y, deltas, color=color, edgecolor="white")
        for yi, r in enumerate(rows):
            ax.text(
                r["delta"] + (1 if r["delta"] > 0 else -1),
                yi,
                f"{r['delta']:+.0f} pp  (ws {r['ws_pct']:.0f}% vs bs {r['bs_pct']:.0f}%)",
                va="center",
                ha="left" if r["delta"] > 0 else "right",
                fontsize=8,
            )
        ax.set_yticks(y)
        ax.set_yticklabels(labels, fontsize=9)
        ax.invert_yaxis()
        ax.axvline(0, color="black", linewidth=0.7)
        setup_axes(ax, title, xlabel="Δ expectation pass rate (pp)")
        ax.grid(axis="x", alpha=0.3, linestyle=":")

    fig.suptitle(
        "Eval-level extremes — biggest skill wins and the rare losses",
        fontsize=12,
        y=1.01,
    )
    fig.savefig(OUT / "10_top_skill_wins.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


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


def parse_transcripts(
    snapshot_dir: Path, agent_to_run: dict[str, tuple[int, int, str]]
) -> list[dict]:
    """Single-pass parse of every snapshotted transcript that maps to a run.

    Returns one record per transcript file with all the tool-call counters
    that downstream plots and stats need. Sorted by agent_id so output JSONs
    are deterministic regardless of filesystem iteration order.
    """
    records: list[dict] = []
    for tf in sorted(snapshot_dir.iterdir()):
        if tf.suffix != ".jsonl":
            continue
        aid = tf.stem
        if aid not in agent_to_run:
            continue
        batch, eval_id, cond = agent_to_run[aid]
        rec: dict = {
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


def write_transcript_stats(records: list[dict], total_ws: int, total_bs: int) -> None:
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
    (OUT / "transcript_stats.json").write_text(json.dumps(payload, indent=2) + "\n")


def plot_reference_utilization(
    agent_to_run: dict[str, tuple[int, int, str]], records: list[dict]
) -> None:
    """Per-reference utilization plot + ref_utilization.json + transcript_stats.json."""
    total_ws = sum(1 for v in agent_to_run.values() if v[2] == "with_skill")
    total_bs = sum(1 for v in agent_to_run.values() if v[2] == "without_skill")

    ref_runs_using: Counter = Counter()
    for r in records:
        if r["condition"] != "with_skill":
            continue
        for ref in r["ref_opens"]:
            ref_runs_using[ref] += 1

    payload = {
        "total_ws_runs": total_ws,
        "ref_runs_using": dict(ref_runs_using.most_common()),
    }
    (OUT / "ref_utilization.json").write_text(json.dumps(payload, indent=2) + "\n")
    write_transcript_stats(records, total_ws, total_bs)

    # SKILL.md is always read by construction — show it in the footer text only.
    refs = [(r, n) for r, n in ref_runs_using.most_common() if r != "SKILL.md"][:20]

    fig, ax = plt.subplots(figsize=(11, 8), constrained_layout=True)
    y = np.arange(len(refs))
    pcts = [100 * n / total_ws for _, n in refs]
    ax.barh(y, pcts, color=WONG["ws"], edgecolor="white")
    for yi, (_ref, n) in enumerate(refs):
        ax.text(
            pcts[yi] + 0.5,
            yi,
            f"{n}/{total_ws} runs ({pcts[yi]:.1f}%)",
            va="center",
            fontsize=9,
            color=WONG["ws"],
        )
    ax.set_yticks(y)
    ax.set_yticklabels([r for r, _ in refs], fontsize=10, family="monospace")
    ax.invert_yaxis()
    ax.set_xlim(0, max(pcts) * 1.4 if pcts else 100)
    ax.set_xlabel("% of with_skill runs that opened the reference", fontsize=10)
    setup_axes(ax, f"Reference-file utilization across {total_ws} with_skill runs")
    ax.grid(axis="x", alpha=0.3, linestyle=":")
    ax.text(
        0.99,
        0.02,
        f"SKILL.md was read in {100 * ref_runs_using.get('SKILL.md', 0) / total_ws:.0f}% of runs (omitted from plot)",
        transform=ax.transAxes,
        ha="right",
        fontsize=9,
        style="italic",
        color="#666666",
    )

    fig.suptitle("Which reference files actually got read?", fontsize=12, y=1.01)
    fig.savefig(OUT / "11_reference_utilization.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


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


def plot_script_utilization(
    agent_to_run: dict[str, tuple[int, int, str]], records: list[dict]
) -> None:
    """Per-script utilization: bundled scripts under skills/spyglass/scripts/.

    Counts Bash tool calls that **executed** each script (not just mentioned its
    filename — see _is_script_execution), plus Read tool calls that opened the
    script source.
    """
    scripts = TRACKED_SCRIPTS
    role = TRACKED_SCRIPT_ROLES

    bash_inv: dict[str, Counter] = defaultdict(Counter)  # script -> {cond: count}
    bash_runs: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    read_inv: dict[str, Counter] = defaultdict(Counter)
    for r in records:
        cond = r["condition"]
        for s, n in r["script_executions"].items():
            bash_inv[s][cond] += n
            bash_runs[s][cond].add(r["agent_id"])
        for s, n in r["script_source_reads"].items():
            read_inv[s][cond] += n

    n_ws = sum(1 for v in agent_to_run.values() if v[2] == "with_skill")
    n_bs = sum(1 for v in agent_to_run.values() if v[2] == "without_skill")

    # Persist raw counts so the plot is reproducible without re-parsing transcripts.
    any_script_runs_ws: set[str] = set()
    for s in scripts:
        any_script_runs_ws |= bash_runs[s].get("with_skill", set())

    payload = {
        "n_with_skill_runs": n_ws,
        "n_without_skill_runs": n_bs,
        "any_script_with_skill_runs": len(any_script_runs_ws),
        "scripts": [
            {
                "name": s,
                "role": role[s],
                "with_skill": {
                    "bash_invocations": bash_inv[s].get("with_skill", 0),
                    "n_runs_invoking": len(bash_runs[s].get("with_skill", set())),
                    "source_only_reads": read_inv[s].get("with_skill", 0),
                },
                "without_skill": {
                    "bash_invocations": bash_inv[s].get("without_skill", 0),
                    "n_runs_invoking": len(bash_runs[s].get("without_skill", set())),
                    "source_only_reads": read_inv[s].get("without_skill", 0),
                },
            }
            for s in scripts
        ],
    }
    (OUT / "script_utilization.json").write_text(json.dumps(payload, indent=2) + "\n")

    fig, ax = plt.subplots(figsize=(11, 6.5), constrained_layout=True)
    y = np.arange(len(scripts))

    invokes_ws = [bash_inv[s].get("with_skill", 0) for s in scripts]
    runs_ws = [len(bash_runs[s].get("with_skill", set())) for s in scripts]
    reads_ws = [read_inv[s].get("with_skill", 0) for s in scripts]

    width = 0.5
    ax.barh(
        y,
        invokes_ws,
        width,
        color=WONG["ws"],
        edgecolor="white",
        label="Bash invocations (executed)",
    )
    ax.barh(
        y,
        reads_ws,
        width,
        left=invokes_ws,
        color=WONG["both_pass"],
        edgecolor="white",
        label="Read calls (inspected source only)",
    )

    for yi in range(len(scripts)):
        total = invokes_ws[yi] + reads_ws[yi]
        n_runs = runs_ws[yi]
        annotation = (
            f"{invokes_ws[yi]} invocations ({n_runs}/{n_ws} ws runs)"
            if invokes_ws[yi]
            else "never invoked"
        )
        if reads_ws[yi]:
            annotation += f"  +{reads_ws[yi]} source reads"
        ax.text(total + 0.5, yi, annotation, va="center", fontsize=9, color="#333333")

    ax.set_yticks(y)
    ax.set_yticklabels(
        [f"{s}\n({role[s]}-facing)" for s in scripts], fontsize=10, family="monospace"
    )
    ax.invert_yaxis()
    ax.set_xlim(0, max(max(invokes_ws), 1) * 1.6)
    ax.set_xlabel("# of tool calls across all with_skill runs", fontsize=10)
    setup_axes(ax, f"Bundled-script utilization across {n_ws} with_skill runs")
    ax.legend(loc="lower right", frameon=False, fontsize=9)
    ax.grid(axis="x", alpha=0.3, linestyle=":")

    any_script_runs = set()
    for s in scripts:
        any_script_runs |= bash_runs[s].get("with_skill", set())
    ax.text(
        0.99,
        0.02,
        f"{len(any_script_runs)}/{n_ws} ws runs ({100 * len(any_script_runs) / n_ws:.0f}%) invoked at least one script.\n"
        f"Baseline runs invoked 0 scripts (as expected — they have no skill exposure).",
        transform=ax.transAxes,
        ha="right",
        fontsize=9,
        style="italic",
        color="#666666",
    )

    fig.suptitle("Which bundled scripts actually got run?", fontsize=12, y=1.01)
    fig.savefig(OUT / "12_script_utilization.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def write_per_category_csv(
    cats: dict[int, dict[str, str]], per_eval: list[dict]
) -> None:
    """Side artifact: detailed numbers behind the category plot."""
    out_lines = ["category_kind,category,n_evals,ws_pass,bs_pass,delta_pp"]
    for kind in ("stage", "tier", "difficulty"):
        agg: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
        for r in per_eval:
            c = cats.get(r["eval_id"], {}).get(kind, "unknown")
            agg[c][0] += 1
            agg[c][1] += int(r["ws_pass"])
            agg[c][2] += int(r["bs_pass"])
        for c, (n, w, b) in sorted(agg.items(), key=lambda x: -x[1][0]):
            d = 100 * (w - b) / n
            out_lines.append(f"{kind},{c},{n},{w},{b},{d:.1f}")
    (OUT / "category_breakdown.csv").write_text("\n".join(out_lines) + "\n")


def write_batch_summary_csv(benchmarks: dict[int, dict]) -> None:
    """Per-batch row covering everything cited in BATCHES.md and §"Headline" tables.

    One row per batch with: full-eval pass counts and rates per condition,
    expectation pass rates, total/mean tokens per condition, mean wall-clock
    per condition, plus the ws-bs deltas. Lets the round-D author cite any
    per-batch number without opening a PNG.
    """
    rows = ["batch_id,label,n_evals,ws_full_pass,ws_full_rate,bs_full_pass,bs_full_rate,delta_full_pp,ws_exp_pass,ws_exp_total,ws_exp_rate,bs_exp_pass,bs_exp_total,bs_exp_rate,delta_exp_pp,ws_tokens_total,bs_tokens_total,ws_tokens_mean,bs_tokens_mean,ws_duration_mean_s,bs_duration_mean_s"]
    for b in BATCH_ORDER:
        cfg = benchmarks[b]["configurations"]
        ws = cfg["with_skill"]
        bs = cfg["without_skill"]
        n = ws["n_runs"]
        ws_full_rate = 100 * ws["evals_full_pass"] / n
        bs_full_rate = 100 * bs["evals_full_pass"] / n
        ws_exp_rate = 100 * ws["expectations_passed"] / ws["expectations_total"]
        bs_exp_rate = 100 * bs["expectations_passed"] / bs["expectations_total"]
        # Replace newlines in the label so the CSV stays one-line-per-row.
        label = BATCH_LABELS[b].replace("\n", " ")
        rows.append(
            f"{b},\"{label}\",{n},"
            f"{ws['evals_full_pass']},{ws_full_rate:.1f},"
            f"{bs['evals_full_pass']},{bs_full_rate:.1f},"
            f"{ws_full_rate - bs_full_rate:.1f},"
            f"{ws['expectations_passed']},{ws['expectations_total']},{ws_exp_rate:.1f},"
            f"{bs['expectations_passed']},{bs['expectations_total']},{bs_exp_rate:.1f},"
            f"{ws_exp_rate - bs_exp_rate:.1f},"
            f"{ws['tokens_total']},{bs['tokens_total']},"
            f"{ws['tokens_mean']:.1f},{bs['tokens_mean']:.1f},"
            f"{ws['duration_mean_s']:.2f},{bs['duration_mean_s']:.2f}"
        )
    (OUT / "batch_summary.csv").write_text("\n".join(rows) + "\n")


def write_cumulative_summary_json(benchmarks: dict[int, dict]) -> None:
    """Headline cumulative numbers — the SUMMARY.md headline table in JSON."""
    totals = summarize_benchmarks(benchmarks)
    ws, bs = totals["ws"], totals["bs"]
    ws_full, bs_full = ws["full_pass"], bs["full_pass"]
    n_evals = ws["n_runs"]
    ws_exp_p, ws_exp_t = ws["exp_p"], ws["exp_t"]
    bs_exp_p, bs_exp_t = bs["exp_p"], bs["exp_t"]
    ws_tokens, bs_tokens = ws["tokens"], bs["tokens"]
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
    }
    (OUT / "cumulative_summary.json").write_text(json.dumps(payload, indent=2) + "\n")


def write_top_skill_wins_csv(
    cats: dict[int, dict[str, str]], per_eval: list[dict]
) -> None:
    """Per-eval expectation deltas, sorted by delta desc.

    Covers the top-N table in SUMMARY.md and the figure-only data behind
    plot 10. Sorted by skill - baseline expectation delta (descending) so
    the largest skill wins are at the top, the largest skill losses (if
    any) at the bottom.
    """

    rows = ["rank,eval_id,eval_name,batch,stage,tier,difficulty,ws_pass,bs_pass,ws_exp_rate,bs_exp_rate,delta_pp"]
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
            f"{rank},{eid},{name},{batch},{stage},{tier},{diff},{wsp},{bsp},"
            f"{wsr:.1f},{bsr:.1f},{delta:.1f}"
        )
    (OUT / "top_skill_wins.csv").write_text("\n".join(rows) + "\n")


def main() -> None:
    args = parse_args()
    configure_run(args.run, args.out)
    configure_skill_root(args.skill_root)
    benchmarks = load_benchmarks()
    cats = load_eval_categories()
    per_eval = load_per_eval_results(benchmarks)

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

    snapshot_dir = OUT / "transcripts_snapshot"
    if snapshot_dir.exists() and any(snapshot_dir.iterdir()):
        agent_to_run = build_agent_to_run()
        records = parse_transcripts(snapshot_dir, agent_to_run)
        plot_reference_utilization(agent_to_run, records)
        plot_script_utilization(agent_to_run, records)
    else:
        print(f"Skipping transcript-derived plots: snapshot dir empty at {snapshot_dir}")
        print("  Run snapshot_transcripts.py first to populate it.")

    write_per_category_csv(cats, per_eval)
    write_batch_summary_csv(benchmarks)
    write_cumulative_summary_json(benchmarks)
    write_top_skill_wins_csv(cats, per_eval)
    print("Wrote plots + CSV/JSON exports to", OUT)


if __name__ == "__main__":
    main()
